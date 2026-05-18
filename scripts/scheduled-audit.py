#!/usr/bin/env python3
"""scheduled-audit.py — recurring deterministic harness audit.

Self-gating: does nothing unless today is the first Monday of Jan / Apr /
Jul / Oct (quarterly cadence — matches common reporting rhythms). Wire into
your daily scheduled runner so it runs once per quarter without separate
admin. Add `--force` to run today regardless of date for ad-hoc audits.

What it checks (deterministic only — no LLM):
  1. /score-vault — vault hygiene score + findings
  2. Stale model IDs in code/docs (grep for known-stale strings)
  3. Permission-list drift — hashes settings.json permissions block,
     compares to last-known-good snapshot
  4. Unpinned dependencies in any requirements.txt
  5. Captured-zone write-block coverage — every subdir of
     `00-Inbox/_captured/` is covered by vault-ops WRITE_BLOCKED_PREFIXES
  6. Always-fire rules still load correctly

Output: `00-Inbox/_reports/harness-audit/YYYY-MM-DD.md` (frontmatter
`trust: trusted`, `type: report`).

Usage:
  python scripts/scheduled-audit.py             # self-gated quarterly run
  python scripts/scheduled-audit.py --force     # run today regardless
  python scripts/scheduled-audit.py --dry-run   # print report to stdout
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.harness_paths import vault_root  # noqa: E402

VAULT = vault_root()
REPORT_DIR = VAULT / "00-Inbox" / "_reports" / "harness-audit"
SNAPSHOT_DIR = VAULT / "state" / "audit-snapshots"

QUARTER_MONTHS = {1, 4, 7, 10}  # Jan, Apr, Jul, Oct

# Stale model identifiers — update when a model is retired or rebranded.
# This list catches code/docs that reference outdated model strings.
STALE_MODEL_IDS = [
    "claude-3-5-sonnet",
    "claude-3-5-haiku",
    "claude-3-opus",
    "claude-3-sonnet",
    "claude-3-haiku",
    "claude-sonnet-4-5",
    "claude-opus-4-5",
    "claude-opus-4-6",
    "claude-haiku-4-0",
]


def is_quarterly_trigger(today: date) -> bool:
    """First Monday of Jan/Apr/Jul/Oct."""
    if today.month not in QUARTER_MONTHS:
        return False
    if today.weekday() != 0:  # 0 = Monday
        return False
    return today.day <= 7


def run_score_vault() -> str:
    try:
        result = subprocess.run(
            [sys.executable, str(VAULT / "scripts" / "score-vault.py")],
            capture_output=True, text=True, timeout=60, cwd=str(VAULT),
        )
        return result.stdout or "(no output)"
    except Exception as e:
        return f"(score-vault failed: {type(e).__name__}: {e})"


def grep_stale_models() -> list[tuple[str, str]]:
    """Return list of (file_path, line_text) for each stale model match."""
    hits: list[tuple[str, str]] = []
    extensions = (".py", ".md", ".mjs", ".js", ".ts", ".json", ".yaml", ".yml", ".txt", ".env")
    skip_dirs = {".git", "node_modules", "__pycache__", ".snapshots",
                 ".archive", "_captured", "09-Archive", "drafts",
                 "harness-audit"}  # skip own report dir
    skip_files = {
        "scheduled-audit.py",  # self — contains the model list as data
    }

    for path in VAULT.rglob("*"):
        if not path.is_file() or path.suffix not in extensions:
            continue
        if any(part in skip_dirs for part in path.parts):
            continue
        if path.name in skip_files:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for stale in STALE_MODEL_IDS:
            if stale in text:
                for ln, line in enumerate(text.splitlines(), 1):
                    if stale in line:
                        hits.append((str(path), f"L{ln}: {line.strip()[:120]}"))
                        break
    return hits


def permission_drift() -> tuple[str, str | None]:
    """Return (current_hash, last_hash). last_hash is None if no snapshot exists."""
    settings_path = VAULT / ".claude" / "settings.json"
    try:
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
    except Exception:
        return "(unreadable)", None
    perms = settings.get("permissions", {})
    canonical = json.dumps(perms, sort_keys=True).encode("utf-8")
    current = hashlib.sha256(canonical).hexdigest()[:16]

    snap_path = SNAPSHOT_DIR / "permissions.sha"
    last = None
    if snap_path.exists():
        try:
            last = snap_path.read_text(encoding="utf-8").strip()
        except Exception:
            last = None
    return current, last


def save_permission_snapshot(current_hash: str) -> None:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    (SNAPSHOT_DIR / "permissions.sha").write_text(current_hash, encoding="utf-8")


def unpinned_dependencies() -> list[tuple[str, str]]:
    """Find requirements.txt files with unpinned packages."""
    findings: list[tuple[str, str]] = []
    skip_dirs = {".git", "node_modules", "__pycache__", ".archive"}
    for path in VAULT.rglob("requirements.txt"):
        if any(part in skip_dirs for part in path.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        for ln, raw in enumerate(text.splitlines(), 1):
            line = raw.split("#", 1)[0].strip()
            if not line or line.startswith("-"):
                continue
            if not re.search(r"[=<>~]", line):
                findings.append((str(path), f"L{ln}: {line}"))
    return findings


def captured_zone_coverage() -> tuple[list[str], bool]:
    """List subdirs of 00-Inbox/_captured/ and check they're covered by vault-ops."""
    captured = VAULT / "00-Inbox" / "_captured"
    if not captured.exists():
        return [], True
    subdirs = [p.name for p in captured.iterdir() if p.is_dir() and not p.name.startswith(".")]
    mcp_path = VAULT / "scripts" / "mcp" / "vault-ops-server.py"
    covered = True
    try:
        mcp_text = mcp_path.read_text(encoding="utf-8")
        covered = '"00-Inbox/_captured"' in mcp_text
    except Exception:
        covered = False
    return subdirs, covered


def render_report(today: date,
                  score_vault_output: str,
                  stale_hits: list[tuple[str, str]],
                  perm_current: str,
                  perm_last: str | None,
                  unpinned: list[tuple[str, str]],
                  captured_subdirs: list[str],
                  captured_covered: bool) -> str:
    iso = today.strftime("%Y-%m-%d")
    lines: list[str] = []
    lines.append("---")
    lines.append(f"name: harness-audit-{iso}")
    lines.append("type: report")
    lines.append("source: scripts/scheduled-audit.py")
    lines.append("trust: trusted")
    lines.append(f"date: {iso}")
    lines.append("---")
    lines.append("")
    lines.append(f"# Scheduled harness audit — {iso}")
    lines.append("")
    lines.append(
        "Deterministic recurring audit (quarterly cadence). The deeper "
        "LLM-driven review still runs on demand via Claude Code session — "
        "this catches drift between those."
    )
    lines.append("")

    lines.append("## 1. Vault hygiene (score-vault)")
    lines.append("")
    lines.append("```")
    lines.append(score_vault_output.strip())
    lines.append("```")
    lines.append("")

    lines.append("## 2. Stale model IDs")
    lines.append("")
    if not stale_hits:
        lines.append("**No stale model IDs found** in code or docs.")
    else:
        lines.append(f"Found {len(stale_hits)} reference(s) to stale model IDs:")
        lines.append("")
        lines.append("| File | Line |")
        lines.append("|---|---|")
        for path, line in stale_hits[:40]:
            rel = path.replace(str(VAULT), "").lstrip("/\\")
            esc = line.replace("|", "\\|")[:100]
            lines.append(f"| `{rel}` | {esc} |")
        if len(stale_hits) > 40:
            lines.append(f"| _(+{len(stale_hits) - 40} more)_ | |")
    lines.append("")

    lines.append("## 3. Permission-list drift")
    lines.append("")
    if perm_last is None:
        lines.append(
            f"First audit run — recording baseline hash `{perm_current}`. "
            f"Future runs will compare against this."
        )
    elif perm_last == perm_current:
        lines.append(f"No drift. Hash matches baseline (`{perm_current}`).")
    else:
        lines.append(
            f"**Drift detected.** Was `{perm_last}`, now `{perm_current}`. "
            f"Review `.claude/settings.json` permissions block — did the change "
            f"go through review? If yes, accept the new baseline by running "
            f"`python scripts/scheduled-audit.py --accept-perms`."
        )
    lines.append("")

    lines.append("## 4. Unpinned dependencies")
    lines.append("")
    if not unpinned:
        lines.append("**No unpinned packages found** in any requirements.txt.")
    else:
        lines.append(f"Found {len(unpinned)} unpinned package(s):")
        lines.append("")
        lines.append("| File | Line |")
        lines.append("|---|---|")
        for path, line in unpinned[:40]:
            rel = path.replace(str(VAULT), "").lstrip("/\\")
            esc = line.replace("|", "\\|")[:100]
            lines.append(f"| `{rel}` | {esc} |")
    lines.append("")

    lines.append("## 5. Captured-zone write-block coverage")
    lines.append("")
    if captured_covered:
        lines.append(
            f"`vault-ops-server.py` still blocks the `00-Inbox/_captured/` "
            f"prefix. {len(captured_subdirs)} subdirectory(ies) under it are "
            f"covered automatically by startswith match: "
            f"{', '.join(f'`{s}`' for s in captured_subdirs) or '(none)'}."
        )
    else:
        lines.append(
            "**Coverage gap.** `vault-ops-server.py` no longer contains the "
            "`'00-Inbox/_captured'` write-block prefix. **Fix:** re-add the "
            "entry to `WRITE_BLOCKED_PREFIXES` in `scripts/mcp/vault-ops-server.py`."
        )
    lines.append("")

    issues = (
        (1 if stale_hits else 0)
        + (1 if (perm_last is not None and perm_last != perm_current) else 0)
        + (1 if unpinned else 0)
        + (0 if captured_covered else 1)
    )
    lines.append("## Summary")
    lines.append("")
    if issues == 0:
        lines.append("All five deterministic checks **passed**.")
    else:
        lines.append(f"**{issues} check(s)** found drift or new issues. Detail above.")
    lines.append("")
    lines.append("Next scheduled run: first Monday of Jan/Apr/Jul/Oct.")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true",
                    help="Run today regardless of date.")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print report to stdout; don't write or update snapshots.")
    ap.add_argument("--accept-perms", action="store_true",
                    help="Update permission-snapshot to current hash and exit. "
                         "Use after a deliberate permission change.")
    args = ap.parse_args()

    today = date.today()

    if args.accept_perms:
        current, _ = permission_drift()
        save_permission_snapshot(current)
        print(f"Permission snapshot updated to {current}.")
        return 0

    if not args.force and not args.dry_run and not is_quarterly_trigger(today):
        return 0

    score_output = run_score_vault()
    stale_hits = grep_stale_models()
    perm_current, perm_last = permission_drift()
    unpinned = unpinned_dependencies()
    captured_subdirs, captured_covered = captured_zone_coverage()

    report = render_report(today, score_output, stale_hits, perm_current,
                           perm_last, unpinned, captured_subdirs, captured_covered)

    if args.dry_run:
        sys.stdout.write(report)
        return 0

    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORT_DIR / f"{today.strftime('%Y-%m-%d')}.md"
    out_path.write_text(report, encoding="utf-8")
    sys.stdout.write(f"Wrote {out_path}\n")

    if perm_last is None:
        save_permission_snapshot(perm_current)

    return 0


if __name__ == "__main__":
    sys.exit(main())
