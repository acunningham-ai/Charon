"""Charon update orchestrator — one command, all sources.

Reads sources.yaml and offers to update every source whose upstream has
changed. Each source has a type that dispatches to the right strategy:

- github-self: the harness repo. Compare HEAD vs origin/<branch>. If no
  TRACKED file is modified and the local branch is a strict ancestor of
  upstream, offer `git pull --ff-only`. Untracked files (wizard-made folders,
  your own notes) are listed as a warning and do not block: `git pull
  --ff-only` itself refuses to overwrite an untracked file. After a good pull
  it re-checks the Claude Code wiring (scripts/post_install_wiring.py
  --mode update) and reports the result loudly.

- github-vendored: vendored content from upstream. Compare the current
  pinned SHA (in sha_pin_files) vs the upstream HEAD. If newer, clone
  shallow, check out exactly the approved commit (or ask again if upstream
  moved), pre-flight every copy_paths source (no links anywhere in the
  upstream tree, destinations only under VENDORED_DEST_PREFIXES, none nested,
  no .git in any case), stage every copy in a temp sibling, swap all of them
  in, and only then re-pin the SHA. Any failure, Ctrl-C included, rolls every
  destination back, so a half-applied corpus cannot happen.

Prompts need a person at a terminal: with no terminal, or at end of input,
the answer is no. Use --yes for an unattended run.

Usage (run from the Charon folder; the launcher finds python3, python or py):

    sh scripts/hook scripts/update/charon_update.py                # interactive
    sh scripts/hook scripts/update/charon_update.py --check        # check only, no apply
    sh scripts/hook scripts/update/charon_update.py --yes          # apply without prompts
    sh scripts/hook scripts/update/charon_update.py --source NAME  # one source only

`python3 -m scripts.update.charon_update` still works where python3 exists.

Idempotent. Re-runs when already at latest exit 0 with "no updates available".
"""

from __future__ import annotations

import argparse
import os
import re
import shlex
import shutil
import stat
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
    try:
        _validate_source(source)
    except ValueError as exc:
        name = source.get("name")
        return {
            "source": name if isinstance(name, str) and _NAME_RE.match(name) else "?",
            "status": "error",
            "message": str(exc),
            "update_available": False,
        }
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

    # Version-level info — read the nearest tag reachable from local HEAD
    # and compare to the highest semver tag on the remote. This separates
    # "capability update" (new release tag) from "unreleased-commit update"
    # (commits past the latest tag).
    local_tag = _get_local_nearest_tag()
    latest_release_tag = _get_latest_remote_release_tag()
    release_change = None
    if local_tag and latest_release_tag and local_tag != latest_release_tag:
        release_change = (local_tag, latest_release_tag)

    if local_sha == upstream_sha:
        # Up to date at commit level. Even when synced, surface the version
        # the user is on for confidence in the report.
        return {
            "source": name,
            "status": "up-to-date",
            "local_sha": local_sha,
            "upstream_sha": upstream_sha,
            "local_tag": local_tag,
            "latest_release_tag": latest_release_tag,
            "release_change": release_change,
            "update_available": False,
        }

    # Are we a strict ancestor (fast-forwardable)?
    try:
        _git("fetch", "origin", branch)  # ensure refs/remotes/origin/<branch> is fresh
    except subprocess.CalledProcessError as exc:
        return {"source": name, "status": "error", "message": f"git fetch failed: {exc}", "update_available": False}
    ahead, behind = _ahead_behind(local_sha, f"origin/{branch}")
    tracked_dirty, untracked = _working_tree_state()
    # Only modified TRACKED files block. Untracked files are a warning:
    # `git pull --ff-only` refuses on its own to overwrite one, so they can
    # never be silently clobbered. (A git status failure reads as dirty.)
    wt_clean = not tracked_dirty

    # Classify the kind of update available:
    #   "new-release"        — upstream has a release tag newer than local's
    #   "unreleased-commits" — upstream has commits past the last release tag
    if release_change:
        update_kind = "new-release"
    else:
        update_kind = "unreleased-commits"

    return {
        "source": name,
        "status": "update-available" if behind > 0 else "diverged",
        "local_sha": local_sha,
        "upstream_sha": upstream_sha,
        "local_tag": local_tag,
        "latest_release_tag": latest_release_tag,
        "release_change": release_change,
        "update_kind": update_kind,
        "ahead": ahead,
        "behind": behind,
        "working_tree_clean": wt_clean,
        "tracked_dirty": tracked_dirty,
        "untracked": untracked,
        "update_available": behind > 0 and ahead == 0 and wt_clean,
        "blocked_reason": _self_block_reason(ahead, behind, wt_clean),
        "branch": branch,
    }


# Helpers for version-tag awareness

def _get_local_nearest_tag() -> Optional[str]:
    """Return the most recent semver tag reachable from local HEAD, or None.

    Uses ``git describe --tags --abbrev=0 --match 'v*.*.*'`` so we ignore
    non-semver tags. Returns just the tag name, not the describe suffix.
    """
    try:
        out = _git("describe", "--tags", "--abbrev=0", "--match", "v*.*.*").strip()
        return out or None
    except subprocess.CalledProcessError:
        return None


def _get_latest_remote_release_tag() -> Optional[str]:
    """Return the highest semver tag on origin (vX.Y.Z), or None on failure."""
    try:
        out = _git("ls-remote", "--tags", "--refs", "origin")
    except subprocess.CalledProcessError:
        return None
    tags: list = []
    for line in out.splitlines():
        # Format: "<sha>\trefs/tags/<tag>"
        parts = line.split("\t")
        if len(parts) != 2:
            continue
        tag = parts[1].replace("refs/tags/", "", 1)
        # Only consider strict semver tags: vX.Y.Z (no -preview, no -rc, etc.)
        if re.match(r"^v\d+\.\d+\.\d+$", tag):
            tags.append(tag)
    if not tags:
        return None
    return sorted(tags, key=_semver_sort_key)[-1]


def _semver_sort_key(tag: str) -> tuple:
    """Parse 'vX.Y.Z' into (X, Y, Z) for ordered comparison."""
    m = re.match(r"^v(\d+)\.(\d+)\.(\d+)$", tag)
    if not m:
        return (0, 0, 0)
    return tuple(int(m.group(i)) for i in (1, 2, 3))


def _self_block_reason(ahead: int, behind: int, wt_clean: bool) -> Optional[str]:
    if ahead > 0:
        return f"local branch has {ahead} commits not on upstream — manual merge needed"
    if not wt_clean:
        return ("tracked files have uncommitted changes — commit or stash them first "
                "(untracked files do not block)")
    if behind == 0:
        return None
    return None


def _run_scaffold_ensure() -> Optional[str]:
    """After a self-update, ensure the 00-09 base-folder skeleton exists so any
    newly-added base folders land without a manual first-run re-run — the
    one-touch property. Best-effort: never raises, never fails the update.
    Returns a short status line, or None if it couldn't run."""
    script = REPO_ROOT / "scripts" / "first-run.py"
    if not script.exists():
        return None
    try:
        result = subprocess.run(
            [sys.executable, str(script), "--scaffold-only"],
            capture_output=True, text=True, timeout=30,
        )
    except Exception as exc:
        return f"scaffold skipped: {exc}"
    lines = (result.stdout or result.stderr).strip().splitlines()
    return lines[-1] if lines else None


def _apply_github_self(source: dict, status: dict, interactive: bool) -> dict:
    name = source["name"]
    branch = status["branch"]
    if interactive:
        ok = _prompt_yes_no(f"Apply update: git pull --ff-only origin {branch}? ", default_yes=True)
        if not ok:
            return {"source": name, "applied": False, "reason": "declined"}
    untracked = status.get("untracked") or []
    try:
        out = _git("pull", "--ff-only", "origin", branch)
    except subprocess.CalledProcessError as exc:
        reason = f"git pull failed: {exc}"
        if untracked:
            reason += (" (an untracked file may be in the way of an incoming file; "
                       "git refuses to overwrite it, so nothing was lost: move it aside and re-run)")
        return {"source": name, "applied": False, "reason": reason}
    smoke = source.get("post_update_smoke")
    smoke_ok = _run_smoke(smoke) if smoke else None
    result = {"source": name, "applied": True, "git_output": out.strip().splitlines()[-3:], "smoke_ok": smoke_ok}
    scaffold_status = _run_scaffold_ensure()
    if scaffold_status:
        result["scaffold"] = scaffold_status
    result["whats_new"] = _whats_new_after_update()
    result["wiring"] = _run_post_update_wiring(interactive)
    return result


WIRING_SCRIPT = Path("scripts") / "post_install_wiring.py"


def _run_post_update_wiring(interactive: bool) -> dict:
    """After a good self-update, make sure Claude Code is wired to this install
    (the Agent Org pane and the status line), using the script that just
    arrived with the pull. Exit 0 = wired; exit 1 = not wired, and the script
    prints the fix. The result is printed loudly either way; it never fails
    the update itself, because the pull has already landed.

    Interactive runs inherit the terminal so the script can ask before it
    replaces anything; `--yes` runs pass --non-interactive, so it never asks.
    """
    script = REPO_ROOT / WIRING_SCRIPT
    if not script.is_file():
        _loud([
            "WIRING NOT CHECKED: scripts/post_install_wiring.py is missing from this install.",
            "The Agent Org pane and the status line may not be set up.",
            "Re-run the update, or restore the file with: git checkout -- scripts/post_install_wiring.py",
        ])
        return {"ok": False, "missing": True, "exit": None}
    cmd = [sys.executable, str(script), "--mode", "update"]
    if not interactive:
        cmd.append("--non-interactive")
    print()
    print("  Checking Claude Code wiring (Agent Org pane, status line)...")
    try:
        proc = subprocess.run(cmd, cwd=str(REPO_ROOT), check=False,
                              timeout=None if interactive else 300)
        code = proc.returncode
    except Exception as exc:  # noqa: BLE001 - must not fail the update, must be loud
        _loud([f"WIRING CHECK COULD NOT RUN: {type(exc).__name__}: {exc}",
               "Run it yourself from the Charon folder:",
               "    sh scripts/hook scripts/post_install_wiring.py --mode update"])
        return {"ok": False, "missing": False, "exit": None, "error": f"{type(exc).__name__}"}
    if code == 0:
        print("  ✅ wiring: everything is wired.")
        return {"ok": True, "missing": False, "exit": 0}
    _loud([f"WIRING NOT COMPLETE (post_install_wiring.py exited {code}).",
           "The lines above name what is not wired and the exact command that fixes it.",
           "Until it is fixed, the Agent Org pane or the status line will not appear."])
    return {"ok": False, "missing": False, "exit": code}


def _loud(lines: list) -> None:
    bar = "!" * 72
    print()
    print(bar)
    for line in lines:
        print(f"!! {line}")
    print(bar)
    print()


def _whats_new_after_update() -> Optional[dict]:
    """What did this pull actually give the user -- in plain language?

    The update used to say "impact: capability update (new commands / engine /
    rules)" and leave the rest to a 198KB CHANGELOG. And because the only wizard
    call here is `--scaffold-only` (folders, no questions), a question added to
    the wizard after someone installed never reached them: an install-wiring
    capability could land its config file and stay silently unconfigured.

    So after a successful pull we read the capability notes shipped with the new
    code and report (a) what is newly available, (b) which settings it still needs.
    Best-effort: release notes must never be able to fail an update.
    """
    sys.path.insert(0, str(REPO_ROOT / "scripts"))
    try:
        import whats_new  # noqa: PLC0415 - optional, must not break the update
        notes = whats_new.load_notes()
        seen = whats_new.load_seen()
        answered = whats_new.answered_question_ids()
        pending = whats_new.pending_notes(notes, seen)
        if not pending:
            return None
        owed = whats_new.pending_questions(pending, answered)
        print(whats_new.render(pending, answered))
        if owed:
            print("  Some of that needs a setting from you:")
            print("      python scripts/first-run.py --catch-up")
            print()
        whats_new.save_seen(seen | {n["id"] for n in pending if n.get("id")})
        return {"new": [n.get("id") for n in pending], "questions_owed": owed}
    except Exception as exc:  # noqa: BLE001
        return {"error": f"could not read capability notes: {exc!r}"}


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

    # Re-check every value that reaches git, a URL or a temp-folder name: the
    # status dict is built from the manifest and the network.
    try:
        _validate_source(dict(source, repo=repo, branch=branch))
        if not _is_sha(new_sha):
            raise ValueError(f"invalid upstream SHA {str(new_sha)[:80]!r}")
    except ValueError as exc:
        return {"source": name, "applied": False, "reason": f"{exc}; nothing changed"}

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
        try:
            _run("git", "clone", "--depth", "1", "--branch", branch, "--",
                 _clone_url(repo), str(clone_dir))
            cloned_sha = _git_in(clone_dir, "rev-parse", "HEAD").strip()
        except (subprocess.CalledProcessError, OSError) as exc:
            return {"source": name, "applied": False,
                    "reason": f"clone failed, nothing changed: {exc}"}
        if cloned_sha.lower() != new_sha.lower() and not _checkout_approved(clone_dir, new_sha):
            # Upstream moved after the user approved new_sha, and that commit
            # could not be checked out. Never swap in an unseen commit silently.
            moved = (f"upstream moved after the check: the approved commit is {new_sha[:10]}, "
                     f"upstream is now {cloned_sha[:10]}")
            if not interactive:
                return {"source": name, "applied": False,
                        "reason": f"{moved}, and the approved commit could not be checked out; "
                                  "nothing changed. Re-run to review the new commit."}
            if not _prompt_yes_no(f"{moved}. Apply {cloned_sha[:10]} instead? ", default_yes=False):
                return {"source": name, "applied": False,
                        "reason": f"declined: {moved}; nothing changed"}
            # A failed checkout attempt may have left the tree part-way: put it
            # back on exactly the commit the user was just shown, or stop.
            try:
                _git_in(clone_dir, "checkout", "-q", "--force", "--detach", cloned_sha)
                at = _git_in(clone_dir, "rev-parse", "HEAD").strip()
            except (subprocess.CalledProcessError, OSError) as exc:
                return {"source": name, "applied": False,
                        "reason": f"could not restore the clone to {cloned_sha[:10]}; "
                                  f"nothing changed: {exc}"}
            if at.lower() != cloned_sha.lower():
                return {"source": name, "applied": False,
                        "reason": f"clone is not at {cloned_sha[:10]}; nothing changed"}
            new_sha = cloned_sha

        try:
            copy_results, pin_results = apply_vendored_copy(source, clone_dir, old_sha, new_sha)
        except UpdateAborted as exc:
            return {"source": name, "applied": False,
                    "reason": f"{exc} — nothing was changed (every destination rolled back)"}

        # Run post-update smoke (only after the corpus and the pins both landed)
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
        _rmtree_force(sandbox)


def _checkout_approved(clone_dir: Path, sha: str) -> bool:
    """Fetch and check out exactly `sha` in the shallow clone. False if the
    commit cannot be fetched (for example it is no longer on the branch)."""
    if not _is_sha(sha):
        return False
    try:
        _git_in(clone_dir, "fetch", "-q", "--depth", "1", "origin", sha)
        _git_in(clone_dir, "checkout", "-q", "--detach", sha)
        return _git_in(clone_dir, "rev-parse", "HEAD").strip().lower() == sha.lower()
    except (subprocess.CalledProcessError, OSError):
        return False


def _rmtree_force(path: Path) -> None:
    """Remove a temp tree even when it holds read-only files or folders (git
    marks its object files read-only on Windows, which plain rmtree cannot
    delete). Clears the read-only bit only inside `path`, never on a link.
    Best effort: a leftover is reported, never fatal."""
    root = os.path.abspath(str(path))

    def _within(p: str) -> bool:
        try:
            return os.path.normcase(os.path.commonpath([p, root])) == os.path.normcase(root)
        except ValueError:
            return False

    def _retry(func, p, _err) -> None:
        try:
            parent = os.path.dirname(os.path.abspath(p))
            if _within(parent) and not os.path.islink(parent):
                os.chmod(parent, stat.S_IRWXU)
            if not os.path.islink(p):
                os.chmod(p, stat.S_IRWXU if os.path.isdir(p) else stat.S_IREAD | stat.S_IWRITE)
            func(p)
        except OSError:
            pass

    if not os.path.lexists(root):
        return
    try:
        if sys.version_info >= (3, 12):
            shutil.rmtree(root, onexc=_retry)
        else:
            shutil.rmtree(root, onerror=_retry)
    except OSError:
        pass
    if os.path.lexists(root):
        print(f"  note: could not delete temp folder {root}; it is safe to delete by hand")


def _clone_url(repo: str) -> str:
    return f"https://github.com/{repo}.git"


class UpdateAborted(Exception):
    """A vendored update stopped before or during the swap; the tree is as it was."""


def _inside(child: Path, root: Path) -> bool:
    try:
        child.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _safe_rel(rel: str, what: str) -> str:
    """Manifest paths must be plain relative paths: no absolute path, no '..',
    no '.' or empty steps, and no '.git' step in any letter case (Windows also
    drops trailing dots and spaces, so '.GIT.' counts too)."""
    if not isinstance(rel, str) or not rel.strip():
        raise UpdateAborted(f"pre-flight: empty {what} path in sources.yaml")
    norm = rel.replace("\\", "/")
    parts = norm.rstrip("/").split("/")
    if norm.startswith("/") or re.match(r"^[A-Za-z]:", norm) or ".." in parts:
        raise UpdateAborted(f"pre-flight: {what} path {rel!r} must be relative with no '..'")
    if any(p in ("", ".") for p in parts) or ":" in norm:
        raise UpdateAborted(f"pre-flight: {what} path {rel!r} has an empty, '.' or ':' step")
    if any(p.rstrip(" .").casefold() == ".git" for p in parts):
        raise UpdateAborted(f"pre-flight: {what} path {rel!r} names a .git folder")
    return norm


# Vendored content may only land under these repo-relative folders (exact case).
# A manifest entry pointing anywhere else (scripts, hooks, settings, docs, root
# files) is refused, even though it would be inside the repo.
VENDORED_DEST_PREFIXES = ("cerberus/rules/",)

_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_REPO_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9._][A-Za-z0-9._-]{0,99}$")
_BRANCH_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$")
_FULL_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def _is_sha(value) -> bool:
    return isinstance(value, str) and bool(_FULL_SHA_RE.match(value))


def _repo_branch_problems(name, repo, branch) -> list:
    """Values that reach a URL, a temp-folder name or a git argument. Anything
    that could read as a git option, a path step or a different host is out."""
    problems = []
    if not isinstance(name, str) or not _NAME_RE.match(name):
        problems.append(f"name {str(name)[:80]!r}")
    if not isinstance(repo, str) or not _REPO_RE.match(repo) \
            or repo.split("/")[1] in (".", ".."):
        problems.append(f"repo {str(repo)[:80]!r} (expected owner/name)")
    if not isinstance(branch, str) or not _BRANCH_RE.match(branch) or ".." in branch \
            or "//" in branch or "/." in branch or branch.endswith(("/", ".", ".lock")):
        problems.append(f"branch {str(branch)[:80]!r}")
    return problems


def _dest_key(to: str) -> str:
    return to.rstrip("/")


def _dest_problems(copy_paths: list) -> list:
    """Static checks on every copy_paths entry: safe relative paths, every
    destination under an allowed prefix, and no destination nested inside
    another (compared case-folded, as a case-insensitive disk would)."""
    problems, keys = [], []
    for cp in copy_paths:
        try:
            _safe_rel(cp.get("from"), "from")
            to = _safe_rel(cp.get("to"), "to")
        except (UpdateAborted, AttributeError) as exc:
            problems.append(str(exc))
            continue
        key = _dest_key(to)
        if not any(key.startswith(p) and len(key) > len(p) for p in VENDORED_DEST_PREFIXES):
            problems.append(f"{to}: not an allowed destination (vendored content may only "
                            f"land under {', '.join(VENDORED_DEST_PREFIXES)})")
            continue
        keys.append((key.casefold(), to))
    for i, (a, a_to) in enumerate(keys):
        for b, b_to in keys[i + 1:]:
            if a != b and (b.startswith(a + "/") or a.startswith(b + "/")):
                problems.append(f"{a_to} and {b_to}: nested destinations (one is inside the other)")
    return problems


def _validate_source(source: dict) -> None:
    """Raise ValueError naming every invalid manifest value in one source."""
    problems = _repo_branch_problems(source.get("name"), source.get("repo"),
                                     source.get("branch", "main"))
    if source.get("type") == "github-vendored":
        problems += _dest_problems(source.get("copy_paths") or [])
        for rel in source.get("sha_pin_files") or []:
            try:
                _safe_rel(rel, "sha_pin_files")
            except UpdateAborted as exc:
                problems.append(str(exc))
    if problems:
        raise ValueError("invalid sources.yaml value(s): " + "; ".join(problems))


def _preflight(source: dict, clone_dir: Path, repo_root: Path) -> list:
    """Check every copy_paths entry BEFORE anything is touched. Returns a list of
    (src, dst, kind, entry). Raises UpdateAborted naming every problem found."""
    plan, problems, seen = [], [], set()
    copy_paths = source.get("copy_paths") or []
    if not copy_paths:
        raise UpdateAborted("pre-flight: no copy_paths in sources.yaml")
    static = _dest_problems(copy_paths)
    if static:
        raise UpdateAborted("pre-flight failed: " + "; ".join(static))
    for cp in copy_paths:
        frm = _safe_rel(cp.get("from"), "from")
        to = _safe_rel(cp.get("to"), "to")
        kind = "dir" if frm.endswith("/") else "file"
        src = clone_dir / frm.rstrip("/")
        dst = repo_root / to.rstrip("/")
        links = _links_in(src, clone_dir) if (src.exists() or src.is_symlink()) else []
        if links:
            shown = ", ".join(p.relative_to(clone_dir).as_posix() for p in links[:5])
            problems.append(f"{frm}: upstream contains a link ({shown}); links are refused "
                            "so nothing outside the clone can be copied in")
            continue
        if not _inside(src, clone_dir):
            problems.append(f"{frm}: resolves outside the upstream clone")
            continue
        if not _inside(dst, repo_root) or dst.resolve() == repo_root.resolve():
            problems.append(f"{to}: not a safe destination inside the repo")
            continue
        if kind == "dir" and not src.is_dir():
            problems.append(f"upstream has no folder {frm} (upstream layout changed?)")
            continue
        if kind == "file" and not src.is_file():
            problems.append(f"upstream has no file {frm} (upstream layout changed?)")
            continue
        key = str(dst.resolve()).lower()
        if key in seen:
            problems.append(f"{to}: listed twice as a destination")
            continue
        seen.add(key)
        plan.append((src, dst, kind, cp))
    if problems:
        raise UpdateAborted("pre-flight failed: " + "; ".join(problems))
    return plan


def _sibling(path: Path, tag: str) -> Path:
    """A fresh hidden temp name beside `path` (same folder, so a rename is a swap)."""
    base = f".{path.name}.charon-update-{tag}-"
    n = 0
    while True:
        cand = path.with_name(f"{base}{os.getpid()}-{n}")
        if not cand.exists() and not cand.is_symlink():
            return cand
        n += 1


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    elif path.exists() or path.is_symlink():
        path.unlink()


def _is_link(path) -> bool:
    """True for a symlink, or on Windows any reparse point (junction, mount
    point). An entry that cannot be inspected counts as a link (fail closed)."""
    try:
        st = os.lstat(path)
    except OSError:
        return True
    if stat.S_ISLNK(st.st_mode):
        return True
    attrs = getattr(st, "st_file_attributes", 0) or 0
    return bool(attrs & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400))


def _links_in(src: Path, clone_dir: Path) -> list:
    """Every link on the way from the clone root down to `src`, and every link
    anywhere under `src`. Upstream content is untrusted: a nested link could
    point at a local file (an SSH key, say) and a copy would bring its bytes
    into the repo. Links are never followed while walking."""
    found = []
    p = clone_dir
    for part in src.relative_to(clone_dir).parts:
        p = p / part
        if _is_link(p):
            return [p]
    if src.is_dir():
        def _raise(err):
            raise err
        for dirpath, dirnames, filenames in os.walk(src, followlinks=False, onerror=_raise):
            for n in dirnames + filenames:
                if _is_link(Path(dirpath) / n):
                    found.append(Path(dirpath) / n)
            dirnames[:] = [n for n in dirnames if not _is_link(Path(dirpath) / n)]
    return found


def _copy_one(src: Path, staged: Path, kind: str) -> None:
    # symlinks=True / follow_symlinks=False: never read through a link, even if
    # one appeared after the pre-flight walk. The walk refuses links first.
    if kind == "dir":
        shutil.copytree(src, staged, symlinks=True)
    else:
        shutil.copy2(src, staged, follow_symlinks=False)


def _move(a: Path, b: Path) -> None:
    os.rename(a, b)


def apply_vendored_copy(source: dict, clone_dir: Path, old_sha: str, new_sha: str,
                        repo_root: Optional[Path] = None) -> tuple:
    """Atomic corpus update: pre-flight, stage, swap, re-pin, or roll back.

    1. Pre-flight every copy_paths source in the clone (nothing touched yet).
    2. Copy each source into a temp sibling of its destination.
    3. Swap: move each old destination aside, move the staged copy in.
    4. Re-pin the SHA in every sha_pin_files entry.
    5. Only then delete the old copies.
    A failure at any step before 5 restores every destination and pin file
    exactly as it was, and raises UpdateAborted.
    """
    root = repo_root if repo_root is not None else REPO_ROOT
    plan = _preflight(source, clone_dir, root)

    created_dirs: list = []   # parent folders this run created (removed on rollback)
    staged: list = []         # (staged_path, dst, kind, entry)
    swapped: list = []        # (dst, backup_or_None, staged_path), recorded BEFORE any rename
    pins_written: list = []   # (file, original_bytes)

    def _there(p: Path) -> bool:
        return p.exists() or p.is_symlink()

    def rollback() -> list:
        # Each swap is recorded before its first rename, so an interrupt (Ctrl-C)
        # can land at any point. What to undo is read from the disk, not assumed:
        # a backup that exists means the original was moved aside and goes back;
        # no backup yet means the original never moved and is left alone.
        errs = []
        for f, original in reversed(pins_written):
            try:
                f.write_bytes(original)
            except OSError as exc:
                errs.append(f"restore {f}: {exc}")
        for dst, backup, st in reversed(swapped):
            try:
                if backup is not None:
                    if _there(backup):
                        if _there(dst):
                            _remove(dst)
                        _move(backup, dst)
                elif not _there(st) and _there(dst):
                    _remove(dst)  # the new copy went in where nothing was before
            except OSError as exc:
                errs.append(f"restore {dst}: {exc}")
        for st, _dst, _k, _e in staged:
            try:
                _remove(st)
            except OSError as exc:
                errs.append(f"clean {st}: {exc}")
        for d in reversed(created_dirs):
            try:
                d.rmdir()
            except OSError:
                pass
        return errs

    try:
        # 2. stage
        for src, dst, kind, cp in plan:
            missing = []
            p = dst.parent
            while not p.exists():
                missing.append(p)
                p = p.parent
            for d in reversed(missing):
                created_dirs.append(d)  # recorded first; rmdir of a missing dir is ignored
                d.mkdir()
            st = _sibling(dst, "new")
            staged.append((st, dst, kind, cp))
            _copy_one(src, st, kind)
        # 3. swap (record first, then rename: see rollback)
        for st, dst, kind, cp in staged:
            backup = _sibling(dst, "old") if _there(dst) else None
            swapped.append((dst, backup, st))
            if backup is not None:
                _move(dst, backup)
            _move(st, dst)
        staged = [s for s in staged if s[0].exists()]
        # 4. re-pin
        pin_results = []
        for rel in source.get("sha_pin_files", []):
            f = root / _safe_rel(rel, "sha_pin_files")
            if not f.is_file():
                pin_results.append({"file": rel, "replaced": 0, "skipped": "not found"})
                continue
            original = f.read_bytes()
            text = original.decode("utf-8")
            new_text, n = re.subn(re.escape(old_sha), new_sha, text)
            # Also the short form (first 7 chars), common in tag/commit references
            new_text, n2 = re.subn(re.escape(old_sha[:7]), new_sha[:7], new_text)
            if new_text != text:
                pins_written.append((f, original))
                tmp = _sibling(f, "pin")
                try:
                    tmp.write_bytes(new_text.encode("utf-8"))
                    os.replace(tmp, f)
                except BaseException:
                    if tmp.exists():
                        tmp.unlink()
                    raise
            pin_results.append({"file": rel, "replaced": n + n2})
    except BaseException as exc:
        errs = rollback()
        if errs:
            raise UpdateAborted(
                f"update failed ({type(exc).__name__}: {exc}) and the rollback was INCOMPLETE: "
                + "; ".join(errs) + ". Restore with: git checkout -- "
                + " ".join(str(cp.get("to")) for _s, _d, _k, cp in plan)
                + " " + " ".join(str(r) for r in source.get("sha_pin_files", []))) from exc
        if isinstance(exc, UpdateAborted):
            raise
        if not isinstance(exc, Exception):
            raise  # KeyboardInterrupt etc.: rolled back, now let it propagate
        raise UpdateAborted(f"update failed ({type(exc).__name__}: {exc})") from exc

    # 5. success: drop the old copies (best effort; a leftover is harmless)
    for dst, backup, _st in swapped:
        if backup is not None:
            try:
                _remove(backup)
            except OSError as exc:
                print(f"  note: could not delete old copy {backup}: {exc}")
    copy_results = [{"from": cp["from"], "to": cp["to"], "kind": kind} for _s, _d, kind, cp in plan]
    return copy_results, pin_results


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


def _working_tree_state() -> tuple:
    """(tracked_dirty, untracked): lists of `git status --porcelain` paths.

    Only tracked changes block an update. Untracked entries ('??') are returned
    so the caller can warn. If git status itself fails, report it as a tracked
    problem so the update blocks (fail closed)."""
    try:
        out = _git("status", "--porcelain")
    except (subprocess.CalledProcessError, OSError) as exc:
        return [f"(git status failed: {exc})"], []
    tracked, untracked = [], []
    for line in out.splitlines():
        if not line.strip():
            continue
        if line.startswith("?? "):
            untracked.append(line[3:])
        elif line.startswith("!! "):
            continue  # ignored files never block
        else:
            tracked.append(line[3:] if len(line) > 3 else line)
    return tracked, untracked


def _is_working_tree_clean() -> bool:
    """True when no TRACKED file is modified (untracked files are allowed)."""
    tracked, _untracked = _working_tree_state()
    return not tracked


def _fetch_github_branch_sha(repo: str, branch: str) -> str:
    """Fetch the HEAD SHA of a GitHub branch via the public API (no auth needed)."""
    url = f"https://api.github.com/repos/{repo}/branches/{branch}"
    req = urllib.request.Request(url, headers={"Accept": "application/vnd.github+json", "User-Agent": "charon-update/1.0"})
    with urllib.request.urlopen(req, timeout=15) as resp:
        import json
        data = json.load(resp)
    sha = data["commit"]["sha"]
    if not _is_sha(sha):
        raise ValueError(f"upstream returned an invalid SHA {str(sha)[:80]!r}")
    return sha


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
    """Ask a person on the terminal. With no terminal, or at end of input, the
    answer is NO: an approval must be typed. Unattended runs use --yes, which
    never reaches this prompt. Enter on a real terminal takes the default."""
    suffix = " [Y/n]: " if default_yes else " [y/N]: "
    stdin = sys.stdin
    try:
        tty = bool(stdin is not None and stdin.isatty())
    except (AttributeError, ValueError, OSError):
        tty = False
    if not tty:
        print(prompt + suffix + "no (no terminal to ask on; after confirming, "
              "re-run with --yes to apply without asking)")
        return False
    try:
        ans = input(prompt + suffix).strip().lower()
    except EOFError:
        print()
        print("  no answer (end of input), treating it as no")
        return False
    if not ans:
        return default_yes
    return ans in ("y", "yes")


_PYTHON_NAMES = {"python", "python3", "python.exe", "python3.exe", "py"}


def _smoke_argv(cmd: str) -> Optional[list]:
    """If the smoke command starts with a python name, return it as an argv that
    runs on THIS interpreter (sys.executable), so a machine with only `python3`
    (or only `py`) still runs it. Otherwise None: run it as written."""
    try:
        parts = shlex.split(cmd, posix=True)
    except ValueError:
        return None
    if parts and parts[0].lower() in _PYTHON_NAMES:
        rest = parts[1:]
        if parts[0].lower() == "py" and rest[:1] and re.match(r"^-\d", rest[0]):
            rest = rest[1:]  # drop a `py -3` version selector
        return [sys.executable, *rest]
    return None


def _run_smoke(cmd: str) -> bool:
    """Run a post-update smoke check. Returns True on exit 0."""
    argv = _smoke_argv(cmd)
    print(f"  smoke: {cmd}" + (f"  (on {sys.executable})" if argv else ""))
    try:
        if argv is not None:
            result = subprocess.run(argv, cwd=str(REPO_ROOT), check=False)
        else:
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
        # github-vendored (rule corpus)
        if "pinned_sha" in s:
            print(f"  ✅ {name}: rules at latest (pinned {s['pinned_sha'][:10]})")
            return
        # github-self with version info
        local_tag = s.get("local_tag")
        if local_tag:
            print(f"  ✅ {name}: up to date — currently on {local_tag} ({s['local_sha'][:10]})")
        else:
            print(f"  ✅ {name}: up to date ({s['local_sha'][:10]})")
        return

    if s["status"] == "update-available":
        # github-vendored (rule corpus) — SHA-level diff
        if "pinned_sha" in s:
            print(f"  ⏫ {name}: rule updates available")
            print(f"     pinned  : {s['pinned_sha'][:10]}")
            print(f"     upstream: {s['upstream_sha'][:10]}")
            print(f"     impact  : detection-rule refresh (new / updated YARA, signatures, policies)")
            return
        # github-self — distinguish capability update from unreleased-commits
        update_kind = s.get("update_kind", "unreleased-commits")
        local_tag = s.get("local_tag") or "(no tag)"
        latest_tag = s.get("latest_release_tag") or "(no tag)"
        if update_kind == "new-release":
            print(f"  🆙 {name}: NEW RELEASE available — {local_tag} → {latest_tag}")
            print(f"     impact  : capability update (new commands / engine / rules)")
            print(f"     commits : {s['behind']} commits ahead on upstream/{s['branch']}")
        else:
            print(f"  ⏫ {name}: {s['behind']} unreleased commit(s) past {local_tag} on upstream/{s['branch']}")
            print(f"     impact  : in-flight fixes since {local_tag}, no new release yet")
        print(f"     local   : {s['local_sha'][:10]}")
        print(f"     upstream: {s['upstream_sha'][:10]}")
        if s.get("blocked_reason"):
            print(f"     blocked : {s['blocked_reason']}")
            for p in (s.get("tracked_dirty") or [])[:10]:
                print(f"               modified: {p}")
        _print_untracked_warning(s)
        return

    if s["status"] == "diverged":
        print(f"  ⚠️  {name}: local has diverged from upstream")
        print(f"     ahead   : {s['ahead']}  behind: {s['behind']}")
        print(f"     blocked : {s.get('blocked_reason', '?')}")
        return

    if s["status"] == "error":
        print(f"  ❌ {name}: error — {s['message']}")
        return

    print(f"  ? {name}: {s}")


def _print_untracked_warning(s: dict) -> None:
    untracked = s.get("untracked") or []
    if not untracked:
        return
    print(f"     ⚠️  warning: {len(untracked)} untracked item(s) in the Charon folder (these do NOT block):")
    for p in untracked[:10]:
        print(f"               {p}")
    if len(untracked) > 10:
        print(f"               ... and {len(untracked) - 10} more")
    print("               If an incoming file has the same name, git stops the pull and changes nothing.")


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
            if result.get("scaffold"):
                print(f"     folders: {result['scaffold']}")
            wiring = result.get("wiring")
            if isinstance(wiring, dict):
                if wiring.get("ok"):
                    print("     wiring: OK (Agent Org pane and status line)")
                elif wiring.get("missing"):
                    print("     ⚠️  wiring: NOT CHECKED — scripts/post_install_wiring.py is missing (see above)")
                else:
                    print("     ⚠️  wiring: NOT COMPLETE — see the fix printed above")
        else:
            print(f"  ❌ {source['name']}: not applied — {result.get('reason', 'unknown')}")
            any_failed = True

    print()
    print("Done. Review with `git diff` before committing.")
    return 1 if any_failed else 0


if __name__ == "__main__":
    sys.exit(main())
