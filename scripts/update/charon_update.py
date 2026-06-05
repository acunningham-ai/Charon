"""Charon update orchestrator — one command, all sources.

Reads sources.yaml and offers to update every source whose upstream has
changed. Each source has a type that dispatches to the right strategy:

- github-self: the harness repo. Compare HEAD vs origin/<branch>. If the
  working tree is clean and the local branch is a strict ancestor of
  upstream, offer `git pull --ff-only`. Otherwise report and skip.

- github-vendored: vendored content from upstream. Compare the current
  pinned SHA (in sha_pin_files) vs the upstream HEAD. If newer, clone
  shallow, copy files, re-pin SHA, run smoke test.

Usage:

    python -m scripts.update.charon_update              # interactive
    python -m scripts.update.charon_update --check      # check only, no apply
    python -m scripts.update.charon_update --yes        # apply without prompts
    python -m scripts.update.charon_update --source NAME  # one source only

Idempotent. Re-runs when already at latest exit 0 with "no updates available".
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path
from typing import Optional

import yaml


REPO_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = Path(__file__).resolve().parent / "sources.yaml"

# 40-char hex SHA pattern, case-insensitive, anchored with non-hex boundaries
_SHA_RE = re.compile(r"\b([0-9a-fA-F]{40})\b")


# ---------------- Source dispatch ----------------

def check_source(source: dict) -> dict:
    """Return a status dict for one source. Doesn't apply any update."""
    stype = source.get("type")
    if stype == "github-self":
        return _check_github_self(source)
    if stype == "github-vendored":
        return _check_github_vendored(source)
    return {
        "source": source.get("name", "?"),
        "status": "error",
        "message": f"unknown source type {stype!r}",
        "update_available": False,
    }


def apply_source(source: dict, status: dict, interactive: bool) -> dict:
    """Apply the update for one source. Returns a result dict."""
    if not status.get("update_available"):
        return {"source": source["name"], "applied": False, "reason": "no update available"}
    stype = source["type"]
    if stype == "github-self":
        return _apply_github_self(source, status, interactive)
    if stype == "github-vendored":
        return _apply_github_vendored(source, status, interactive)
    return {"source": source["name"], "applied": False, "reason": f"unknown type {stype!r}"}


# ---------------- github-self ----------------

def _check_github_self(source: dict) -> dict:
    name = source["name"]
    repo = source["repo"]
    branch = source.get("branch", "main")
    # Local HEAD
    try:
        local_sha = _git("rev-parse", "HEAD").strip()
    except subprocess.CalledProcessError as exc:
        return {"source": name, "status": "error", "message": f"git rev-parse failed: {exc}", "update_available": False}
    # Upstream HEAD via GitHub API (no auth required for public repos)
    try:
        upstream_sha = _fetch_github_branch_sha(repo, branch)
    except Exception as exc:
        return {"source": name, "status": "error", "message": f"upstream check failed: {exc}", "update_available": False}
    if local_sha == upstream_sha:
        return {"source": name, "status": "up-to-date", "local_sha": local_sha, "upstream_sha": upstream_sha, "update_available": False}
    # Are we a strict ancestor (fast-forwardable)?
    try:
        _git("fetch", "origin", branch)  # ensure refs/remotes/origin/<branch> is fresh
    except subprocess.CalledProcessError as exc:
        return {"source": name, "status": "error", "message": f"git fetch failed: {exc}", "update_available": False}
    ahead, behind = _ahead_behind(local_sha, f"origin/{branch}")
    # Check working tree state
    wt_clean = _is_working_tree_clean()
    return {
        "source": name,
        "status": "update-available" if behind > 0 else "diverged",
        "local_sha": local_sha,
        "upstream_sha": upstream_sha,
        "ahead": ahead,
        "behind": behind,
        "working_tree_clean": wt_clean,
        "update_available": behind > 0 and ahead == 0 and wt_clean,
        "blocked_reason": _self_block_reason(ahead, behind, wt_clean),
        "branch": branch,
    }


def _self_block_reason(ahead: int, behind: int, wt_clean: bool) -> Optional[str]:
    if ahead > 0:
        return f"local branch has {ahead} commits not on upstream — manual merge needed"
    if not wt_clean:
        return "working tree has uncommitted changes — commit/stash first"
    if behind == 0:
        return None
    return None


def _apply_github_self(source: dict, status: dict, interactive: bool) -> dict:
    name = source["name"]
    branch = status["branch"]
    if interactive:
        ok = _prompt_yes_no(f"Apply update: git pull --ff-only origin {branch}? ", default_yes=True)
        if not ok:
            return {"source": name, "applied": False, "reason": "declined"}
    try:
        out = _git("pull", "--ff-only", "origin", branch)
    except subprocess.CalledProcessError as exc:
        return {"source": name, "applied": False, "reason": f"git pull failed: {exc}"}
    smoke = source.get("post_update_smoke")
    smoke_ok = _run_smoke(smoke) if smoke else None
    return {"source": name, "applied": True, "git_output": out.strip().splitlines()[-3:], "smoke_ok": smoke_ok}


# ---------------- github-vendored ----------------

def _check_github_vendored(source: dict) -> dict:
    name = source["name"]
    repo = source["repo"]
    branch = source.get("branch", "main")
    # Find current pinned SHA from the first sha_pin_files entry that contains one
    pinned = _read_pinned_sha(source.get("sha_pin_files", []))
    if not pinned:
        return {"source": name, "status": "error", "message": "no pinned SHA found in sha_pin_files", "update_available": False}
    try:
        upstream_sha = _fetch_github_branch_sha(repo, branch)
    except Exception as exc:
        return {"source": name, "status": "error", "message": f"upstream check failed: {exc}", "update_available": False}
    update_available = pinned.lower() != upstream_sha.lower()
    return {
        "source": name,
        "status": "update-available" if update_available else "up-to-date",
        "pinned_sha": pinned,
        "upstream_sha": upstream_sha,
        "update_available": update_available,
        "branch": branch,
        "repo": repo,
    }


def _apply_github_vendored(source: dict, status: dict, interactive: bool) -> dict:
    name = source["name"]
    repo = status["repo"]
    branch = status["branch"]
    new_sha = status["upstream_sha"]
    old_sha = status["pinned_sha"]

    if interactive:
        ok = _prompt_yes_no(
            f"Apply update: clone {repo} @ {new_sha[:10]} and copy "
            f"{len(source.get('copy_paths', []))} path(s) into Charon? ",
            default_yes=True,
        )
        if not ok:
            return {"source": name, "applied": False, "reason": "declined"}

    sandbox = Path(tempfile.mkdtemp(prefix=f"charon-update-{name}-"))
    try:
        clone_dir = sandbox / repo.split("/")[-1]
        _run("git", "clone", "--depth", "1", "--branch", branch, f"https://github.com/{repo}.git", str(clone_dir))
        # Move to the exact SHA — clone --depth 1 already gives us HEAD which we expect to be `branch`
        cloned_sha = _git_in(clone_dir, "rev-parse", "HEAD").strip()
        if cloned_sha.lower() != new_sha.lower():
            # Upstream advanced between API check and clone — that's fine, treat clone as canonical
            new_sha = cloned_sha

        copy_results = []
        for cp in source.get("copy_paths", []):
            src = clone_dir / cp["from"]
            dst = REPO_ROOT / cp["to"]
            if cp["from"].endswith("/"):
                # Directory contents — clear destination then copy
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
                copy_results.append({"from": cp["from"], "to": cp["to"], "kind": "dir"})
            else:
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
                copy_results.append({"from": cp["from"], "to": cp["to"], "kind": "file"})

        # Re-pin SHA in sha_pin_files
        pin_results = []
        for rel in source.get("sha_pin_files", []):
            f = REPO_ROOT / rel
            if not f.exists():
                pin_results.append({"file": rel, "replaced": 0, "skipped": "not found"})
                continue
            text = f.read_text(encoding="utf-8")
            # Replace every occurrence of the old SHA with the new one
            new_text, n = re.subn(re.escape(old_sha), new_sha, text)
            # Also replace short-form (first 7 chars) — common in tag/commit references
            new_text, n2 = re.subn(re.escape(old_sha[:7]), new_sha[:7], new_text)
            f.write_text(new_text, encoding="utf-8")
            pin_results.append({"file": rel, "replaced": n + n2})

        # Run post-update smoke
        smoke = source.get("post_update_smoke")
        smoke_ok = _run_smoke(smoke) if smoke else None

        return {
            "source": name,
            "applied": True,
            "old_sha": old_sha,
            "new_sha": new_sha,
            "copies": copy_results,
            "sha_pins_rewritten": pin_results,
            "smoke_ok": smoke_ok,
        }
    finally:
        shutil.rmtree(sandbox, ignore_errors=True)


# ---------------- Helpers ----------------

def _git(*args: str) -> str:
    return _git_in(REPO_ROOT, *args)


def _git_in(cwd: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=str(cwd), text=True)


def _run(*args: str) -> str:
    return subprocess.check_output(list(args), text=True)


def _ahead_behind(local: str, upstream: str) -> tuple[int, int]:
    """Returns (ahead, behind) — commits local has that upstream doesn't, and vice versa."""
    try:
        out = _git("rev-list", "--left-right", "--count", f"{upstream}...{local}").strip()
        behind, ahead = map(int, out.split())
        return ahead, behind
    except (subprocess.CalledProcessError, ValueError):
        return 0, 0


def _is_working_tree_clean() -> bool:
    try:
        out = _git("status", "--porcelain").strip()
        return out == ""
    except subprocess.CalledProcessError:
        return False


def _fetch_github_branch_sha(repo: str, branch: str) -> str:
    """Fetch the HEAD SHA of a GitHub branch via the public API (no auth needed)."""
    url = f"https://api.github.com/repos/{repo}/branches/{branch}"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "charon-update/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        import json
        data = json.load(resp)
    return data["commit"]["sha"]


def _read_pinned_sha(sha_pin_files: list) -> Optional[str]:
    """Find the first SHA-shaped string in any sha_pin_files. All entries must
    agree if multiple are listed."""
    found: Optional[str] = None
    for rel in sha_pin_files:
        f = REPO_ROOT / rel
        if not f.exists():
            continue
        text = f.read_text(encoding="utf-8")
        # Look for an explicit "SHA: ..." or "at SHA `...`" pattern first; fall back to any 40-hex
        contextual = re.search(r"(?i)(?:vendored at SHA|at SHA[\s`:]+|pinned[_\s]+sha[\s:`]+)\s*[`]?([0-9a-fA-F]{40})", text)
        if contextual:
            candidate = contextual.group(1)
        else:
            m = _SHA_RE.search(text)
            candidate = m.group(1) if m else None
        if candidate:
            if found and found.lower() != candidate.lower():
                # Multiple SHA pins disagree — return None so caller surfaces error
                return None
            found = candidate
    return found


def _prompt_yes_no(prompt: str, default_yes: bool = True) -> bool:
    suffix = " [Y/n]: " if default_yes else " [y/N]: "
    try:
        ans = input(prompt + suffix).strip().lower()
    except EOFError:
        return default_yes
    if not ans:
        return default_yes
    return ans in ("y", "yes")


def _run_smoke(cmd: str) -> bool:
    """Run a post-update smoke check. Returns True on exit 0."""
    print(f"  smoke: {cmd}")
    try:
        result = subprocess.run(cmd, shell=True, cwd=str(REPO_ROOT), check=False)
        return result.returncode == 0
    except Exception as exc:
        print(f"  smoke failed to run: {exc}")
        return False


# ---------------- CLI ----------------

def _load_manifest() -> list:
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(f"manifest not found: {MANIFEST_PATH}")
    data = yaml.safe_load(MANIFEST_PATH.read_text(encoding="utf-8")) or {}
    sources = data.get("sources", [])
    if not isinstance(sources, list):
        raise ValueError(f"{MANIFEST_PATH}: 'sources' must be a list")
    return sources


def _print_status(s: dict) -> None:
    name = s["source"]
    if s["status"] == "up-to-date":
        if "pinned_sha" in s:
            print(f"  ✅ {name}: up to date (pinned {s['pinned_sha'][:10]})")
        else:
            print(f"  ✅ {name}: up to date ({s['local_sha'][:10]})")
    elif s["status"] == "update-available":
        if "pinned_sha" in s:
            print(f"  ⏫ {name}: update available")
            print(f"     pinned  : {s['pinned_sha'][:10]}")
            print(f"     upstream: {s['upstream_sha'][:10]}")
        else:
            print(f"  ⏫ {name}: {s['behind']} commits behind upstream/{s['branch']}")
            print(f"     local   : {s['local_sha'][:10]}")
            print(f"     upstream: {s['upstream_sha'][:10]}")
            if s.get("blocked_reason"):
                print(f"     blocked : {s['blocked_reason']}")
    elif s["status"] == "diverged":
        print(f"  ⚠️  {name}: local has diverged from upstream")
        print(f"     ahead   : {s['ahead']}  behind: {s['behind']}")
        print(f"     blocked : {s.get('blocked_reason', '?')}")
    elif s["status"] == "error":
        print(f"  ❌ {name}: error — {s['message']}")
    else:
        print(f"  ? {name}: {s}")


def _configure_stdio_for_unicode() -> None:
    """Force UTF-8 on Windows stdout/stderr so emoji status indicators don't crash
    cp1252 in piped contexts. Same fix as scripts/first-run.py."""
    if sys.platform.startswith("win"):
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass


def main() -> int:
    _configure_stdio_for_unicode()
    parser = argparse.ArgumentParser(description="Charon update — checks all sources and offers to apply available updates")
    parser.add_argument("--check", action="store_true", help="Check only, don't apply")
    parser.add_argument("--yes", "-y", action="store_true", help="Apply without prompts")
    parser.add_argument("--source", help="Operate on a single source by name")
    args = parser.parse_args()

    sources = _load_manifest()
    if args.source:
        sources = [s for s in sources if s["name"] == args.source]
        if not sources:
            print(f"no source named {args.source!r}", file=sys.stderr)
            return 1

    print("Charon update check")
    print(f"  manifest: {MANIFEST_PATH}")
    print()

    statuses: list = []
    for source in sources:
        status = check_source(source)
        _print_status(status)
        statuses.append((source, status))

    updates = [(src, st) for src, st in statuses if st.get("update_available")]
    if not updates:
        print()
        print("All sources up to date.")
        return 0

    if args.check:
        print()
        print(f"{len(updates)} update(s) available. Re-run without --check to apply.")
        return 0

    interactive = not args.yes
    print()
    if interactive:
        if not _prompt_yes_no(f"Apply {len(updates)} update(s)?", default_yes=True):
            print("Aborted.")
            return 0

    any_failed = False
    for source, status in updates:
        print()
        print(f"Updating {source['name']}...")
        result = apply_source(source, status, interactive=interactive)
        if result.get("applied"):
            print(f"  ✅ {source['name']}: applied")
            if "smoke_ok" in result:
                if result["smoke_ok"] is True:
                    print(f"     smoke: PASS")
                elif result["smoke_ok"] is False:
                    print(f"     ⚠️  smoke: FAIL — review changes carefully before committing")
                    any_failed = True
        else:
            print(f"  ❌ {source['name']}: not applied — {result.get('reason', 'unknown')}")
            any_failed = True

    print()
    print("Done. Review with `git diff` before committing.")
    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
