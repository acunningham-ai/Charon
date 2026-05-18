#!/usr/bin/env python3
"""skill-curator.py — daily skill-hygiene report.

This script is read-only. It NEVER moves, edits, or deletes a skill file.
It writes a markdown report listing stale + archive-candidate skills to
`00-Inbox/_reports/skill-curator/YYYY-MM-DD.md`. Action is gated on the
/curate-skills slash command after user approval.

Note: report lands in `_reports/`, not `_captured/`. The `_captured/`
zone is for untrusted ingress and is wrapped in "treat as data, not
instructions" path rules. Curator output is deterministic analyser output
— landing it in `_captured/` would incorrectly mark it untrusted.

Last-used resolution:
  1. PRIMARY — telemetry from `state/telemetry/skill-usage-log/*.jsonl`
     (populated by the skill-usage-log PostToolUse hook).
  2. FALLBACK — file mtime on the skill .md file. Less accurate (git
     pulls and edits change mtime) but works before telemetry exists.

Thresholds (tunable at the top of this file):
  STALE_DAYS = 180     # ~6 months unused → tag as stale in report
  ARCHIVE_DAYS = 365   # ~12 months unused → flag as archive candidate

Conservative defaults. Quarterly-cadence skills like `/quarterly-report-prep`
are intentionally above shorter defaults.

Usage:
  python scripts/skill-curator.py
  python scripts/skill-curator.py --dry-run   # print to stdout, don't write
"""
import argparse
import json
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.harness_paths import vault_root  # noqa: E402

STALE_DAYS = 180
ARCHIVE_DAYS = 365

VAULT = vault_root()
COMMANDS_DIR = VAULT / ".claude" / "commands"
TELEMETRY_DIR = VAULT / "state" / "telemetry" / "skill-usage-log"
INBOX_DIR = VAULT / "00-Inbox" / "_reports" / "skill-curator"


def parse_frontmatter(text: str) -> dict:
    m = re.match(r"^---\r?\n(.*?)\r?\n---", text, re.S)
    if not m:
        return {}
    out: dict = {}
    for raw in m.group(1).split("\n"):
        line = raw.rstrip()
        if not line.strip() or line.startswith(" "):
            continue
        if ":" in line:
            k, _, v = line.partition(":")
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def load_usage_index() -> dict:
    """Return {skill_name: latest_invocation_iso} from telemetry."""
    index: dict[str, str] = {}
    if not TELEMETRY_DIR.exists():
        return index
    for f in sorted(TELEMETRY_DIR.glob("*.jsonl")):
        try:
            with f.open(encoding="utf-8") as fp:
                for line in fp:
                    try:
                        row = json.loads(line)
                    except Exception:
                        continue
                    skill = (row.get("payload") or {}).get("skill", "")
                    ts = row.get("ts", "")
                    if skill and ts:
                        cur = index.get(skill, "")
                        if ts > cur:
                            index[skill] = ts
        except Exception:
            continue
    return index


def scan_skills(usage: dict) -> list[dict]:
    """Build a row per skill: name, last_used, source, age_days, status."""
    now = datetime.now(timezone.utc)
    rows: list[dict] = []
    if not COMMANDS_DIR.exists():
        return rows
    for path in sorted(COMMANDS_DIR.glob("*.md")):
        if path.name.startswith("_") or path.name.startswith("."):
            continue
        name = path.stem
        last_iso = usage.get(name, "")
        source = "telemetry"
        if last_iso:
            try:
                last_dt = datetime.fromisoformat(last_iso)
            except Exception:
                last_dt = None
        else:
            last_dt = None
        if last_dt is None:
            try:
                last_dt = datetime.fromtimestamp(
                    path.stat().st_mtime, tz=timezone.utc
                )
                source = "mtime"
            except Exception:
                continue
        age_days = (now - last_dt).days
        if age_days >= ARCHIVE_DAYS:
            status = "archive-candidate"
        elif age_days >= STALE_DAYS:
            status = "stale"
        else:
            status = "active"

        fm = {}
        try:
            fm = parse_frontmatter(path.read_text(encoding="utf-8"))
        except Exception:
            pass

        rows.append({
            "name": name,
            "path": str(path),
            "description": fm.get("description", ""),
            "last_used": last_dt.strftime("%Y-%m-%d"),
            "age_days": age_days,
            "source": source,
            "status": status,
        })
    return rows


def render_report(rows: list[dict]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    counts = {"active": 0, "stale": 0, "archive-candidate": 0}
    for r in rows:
        counts[r["status"]] = counts.get(r["status"], 0) + 1

    actionable = [r for r in rows if r["status"] != "active"]
    has_telemetry = any(r["source"] == "telemetry" for r in rows)

    lines: list[str] = []
    lines.append("---")
    lines.append(f"name: skill-curator-{now}")
    lines.append("type: report")
    lines.append("source: scripts/skill-curator.py")
    lines.append("trust: trusted")
    lines.append(f"date: {now}")
    lines.append("---")
    lines.append("")
    lines.append(f"# Skill curator report — {now}")
    lines.append("")
    lines.append(
        f"Scanned **{len(rows)}** skills. Active: **{counts['active']}**. "
        f"Stale (≥{STALE_DAYS}d): **{counts['stale']}**. "
        f"Archive candidates (≥{ARCHIVE_DAYS}d): **{counts['archive-candidate']}**."
    )
    lines.append("")
    if not has_telemetry:
        lines.append(
            "> 🔴 No telemetry data yet — every row uses file mtime as a "
            "proxy for last-used. Expect false positives (git pulls and "
            "edits move mtime). Wait for the skill-usage-log hook to "
            "accumulate ~30 days of data before treating this report as "
            "authoritative."
        )
        lines.append("")
    if not actionable:
        lines.append("**No action needed — every skill used within the threshold.**")
        lines.append("")
        return "\n".join(lines)

    lines.append("## Action candidates")
    lines.append("")
    lines.append("| Skill | Status | Last used | Days | Source | Description |")
    lines.append("|---|---|---|---|---|---|")
    for r in actionable:
        desc = (r["description"] or "")[:60].replace("|", "\\|")
        lines.append(
            f"| `{r['name']}` | {r['status']} | {r['last_used']} | "
            f"{r['age_days']} | {r['source']} | {desc} |"
        )
    lines.append("")
    lines.append("## How to act")
    lines.append("")
    lines.append(
        "Run `/curate-skills` to review these with model-assisted triage and "
        "approve archival per-skill. Nothing moves without your approval. "
        f"Archive lands in `.claude/commands/.archive/{now}/`; restore by "
        "moving the file back."
    )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Print report to stdout instead of writing.")
    args = ap.parse_args()

    usage = load_usage_index()
    rows = scan_skills(usage)
    report = render_report(rows)

    if args.dry_run:
        sys.stdout.write(report)
        return 0

    INBOX_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    out = INBOX_DIR / f"{today}.md"
    out.write_text(report, encoding="utf-8")
    sys.stdout.write(f"Wrote {out}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
