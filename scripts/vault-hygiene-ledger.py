#!/usr/bin/env python
"""vault-hygiene-ledger.py — deterministic drift-ledger accumulator.

Phase 1 of the self-improving vault-hygiene prototype (roadmap §B). Runs the
deterministic `score-vault.py --json` audit and appends a timestamped snapshot
to an append-only ledger. This is the *history* substrate that the recurrence
detector (Phase 2) and post-check (Phase 4) read.

DETERMINISTIC. No LLM call, takes NO action on the vault, read-only with respect
to vault content. Its only write is appending one line to its own ledger. Per
the clean-signal gate: everything learned
downstream is *derived from* this deterministic history — nothing here is
model-generated, so there is no autophagy risk.

Ledger line schema (one JSON object per line):
  {
    "ts":             ISO-8601 UTC timestamp of this run,
    "date":           UTC date (YYYY-MM-DD) — used for the once-per-day guard,
    "score":          int 0-100 from score-vault,
    "finding_count":  int,
    "category_counts": {category: count, ...},   # derived, convenience
    "findings":       [ {severity, category, message, file}, ... ]  # lossless
  }

Usage:
  python vault-hygiene-ledger.py           # append today's snapshot (skips if one exists for today)
  python vault-hygiene-ledger.py --force   # append even if today already has a snapshot
  python vault-hygiene-ledger.py --status  # print ledger summary, append nothing

Exit codes:
  0  snapshot appended OR skipped (today already recorded) OR --status
  1  score-vault.py failed / produced non-JSON — ledger left untouched
"""
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.harness_paths import vault_root  # noqa: E402

SCRIPT_DIR = Path(__file__).resolve().parent
SCORE_VAULT = SCRIPT_DIR / "score-vault.py"
LEDGER_DIR = vault_root() / "state" / "vault-hygiene"
LEDGER_PATH = LEDGER_DIR / "ledger.jsonl"


def run_score_vault():
    """Invoke score-vault.py --json and return the parsed dict.

    Consumes the stable public --json contract via subprocess rather than
    importing internals — the ledger depends on the output shape, not the
    implementation. Returns None on any failure (fail-safe: caller leaves the
    ledger untouched)."""
    try:
        proc = subprocess.run(
            [sys.executable, str(SCORE_VAULT), "--json"],
            capture_output=True,
            text=True,
            timeout=120,
        )
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: failed to run score-vault.py: {exc}", file=sys.stderr)
        return None
    if proc.returncode != 0:
        print(
            f"ERROR: score-vault.py exited {proc.returncode}; stderr:\n{proc.stderr}",
            file=sys.stderr,
        )
        return None
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        print(f"ERROR: score-vault.py did not emit valid JSON: {exc}", file=sys.stderr)
        return None
    if not isinstance(data, dict) or "findings" not in data:
        print("ERROR: score-vault.py JSON missing expected keys", file=sys.stderr)
        return None
    return data


def read_ledger():
    """Return the list of snapshot dicts already in the ledger (possibly empty)."""
    if not LEDGER_PATH.exists():
        return []
    snapshots = []
    for line in LEDGER_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            snapshots.append(json.loads(line))
        except json.JSONDecodeError:
            # A corrupt line should not crash the accumulator; skip it.
            print(f"WARN: skipping unparseable ledger line", file=sys.stderr)
    return snapshots


def build_snapshot(data, now):
    findings = data.get("findings", [])
    category_counts = Counter(f.get("category", "?") for f in findings)
    return {
        "ts": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "score": data.get("score"),
        "finding_count": data.get("finding_count", len(findings)),
        "category_counts": dict(sorted(category_counts.items())),
        "findings": findings,
    }


def append_snapshot(snapshot):
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    with LEDGER_PATH.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(snapshot) + "\n")


def print_status(snapshots):
    if not snapshots:
        print("Ledger empty — no snapshots recorded yet.")
        print(f"Path: {LEDGER_PATH}")
        return
    first, last = snapshots[0], snapshots[-1]
    print(f"# Vault-hygiene ledger — {len(snapshots)} snapshot(s)")
    print(f"Path:  {LEDGER_PATH}")
    print(f"First: {first.get('date')}  score {first.get('score')}")
    print(f"Last:  {last.get('date')}  score {last.get('score')}  "
          f"({last.get('finding_count')} findings)")
    if last.get("category_counts"):
        print("Latest category counts:")
        for cat, n in last["category_counts"].items():
            print(f"  {cat}: {n}")


def main():
    # Force UTF-8 stdout — Windows console is cp1252 and would choke on any
    # non-ASCII in messages/paths. Guard in case stdout isn't reconfigurable.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    args = set(sys.argv[1:])
    snapshots = read_ledger()

    if "--status" in args:
        print_status(snapshots)
        return 0

    # Local time with offset preserved — the daily cadence is local (wire this as
    # the last step of your scheduled maintenance run), so "one snapshot per day"
    # must mean your local calendar day, not UTC's (which can lag many hours and
    # would mislabel the date). The offset in `ts` keeps ordering unambiguous
    # across hosts.
    now = datetime.now().astimezone()
    today = now.strftime("%Y-%m-%d")

    if "--force" not in args and any(s.get("date") == today for s in snapshots):
        print(f"Snapshot for {today} already recorded — skipping "
              f"(use --force to append anyway).")
        return 0

    data = run_score_vault()
    if data is None:
        # Fail-safe: ledger left untouched.
        return 1

    snapshot = build_snapshot(data, now)
    append_snapshot(snapshot)
    print(f"Appended snapshot for {today}: score {snapshot['score']}, "
          f"{snapshot['finding_count']} findings "
          f"({len(snapshots) + 1} total in ledger).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
