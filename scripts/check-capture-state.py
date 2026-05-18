#!/usr/bin/env python
"""Diagnostic for the capture pipeline state files.

Validates:
- state/captured.json — main captured-IDs registry (parses as JSON?)
- state/graph-cursor.json — high-water marks for the configured sources
- state/scheduled-run.log — last successful run timestamp

Reports anything corrupt or stale. Doesn't fix anything — the pipeline is
self-healing on next successful run because the cursor doesn't advance
until the run completes cleanly.

Usage: python check-capture-state.py

Called by the assistant when the capture pipeline appears stuck.
See `CLAUDE.md` "Recovery Recipes" section.
"""
import json
import os
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.harness_paths import capture_pipeline_root  # noqa: E402


PIPELINE_ROOT = str(capture_pipeline_root())
STATE_DIR = os.path.join(PIPELINE_ROOT, "state")


def check_captured_json() -> tuple[bool, str]:
    """captured.json holds the dedup IDs. JSON corruption here halts the pipeline."""
    path = os.path.join(STATE_DIR, "captured.json")
    if not os.path.exists(path):
        return False, f"MISSING: {path}"
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        size_mb = os.path.getsize(path) / 1024 / 1024
        item_count = len(data) if isinstance(data, dict) else 0
        return True, f"OK: {item_count} captured IDs, {size_mb:.1f} MB"
    except json.JSONDecodeError as e:
        return False, f"CORRUPT: {path} — {e}"
    except OSError as e:
        return False, f"READ ERROR: {path} — {e}"


def check_cursor() -> tuple[bool, str]:
    """graph-cursor.json holds source high-water marks."""
    path = os.path.join(STATE_DIR, "graph-cursor.json")
    if not os.path.exists(path):
        return False, f"MISSING: {path}"
    try:
        with open(path, "r", encoding="utf-8") as f:
            cursor = json.load(f)
    except json.JSONDecodeError as e:
        return False, f"CORRUPT: {path} — {e}"

    lines = []
    now = datetime.now(timezone.utc)
    if not cursor:
        lines.append("  (no high-water marks yet — fresh install or pipeline never run)")
    for source, entry in cursor.items():
        if not isinstance(entry, dict):
            continue
        hwm = entry.get("highWaterMark")
        if not hwm:
            lines.append(f"  {source}: no high-water mark (will use config window)")
            continue
        try:
            hwm_dt = datetime.fromisoformat(hwm.replace("Z", "+00:00"))
            age_hours = (now - hwm_dt).total_seconds() / 3600
            stale = age_hours > 36  # one daily run + buffer
            tag = "STALE" if stale else "OK"
            lines.append(f"  {source}: {hwm} ({age_hours:.1f}h ago) [{tag}]")
        except ValueError:
            lines.append(f"  {source}: UNPARSEABLE {hwm}")
    return True, "\n".join(lines)


def check_last_run() -> tuple[bool, str]:
    """scheduled-run.log shows last successful run."""
    path = os.path.join(STATE_DIR, "scheduled-run.log")
    if not os.path.exists(path):
        return False, f"MISSING: {path}"
    try:
        with open(path, "rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - 4000))
            tail = f.read().decode("utf-8", errors="replace")
    except OSError as e:
        return False, f"READ ERROR: {path} — {e}"

    finished_lines = [
        ln for ln in tail.splitlines() if "Run finished" in ln or "Run started" in ln
    ]
    if not finished_lines:
        return False, "No Run started/finished markers in last 4KB of log"

    last = finished_lines[-1]
    return True, f"Last marker: {last.strip()}"


def main() -> int:
    print(f"Capture pipeline state diagnostics — {STATE_DIR}\n")

    ok_total = True
    for name, fn in [
        ("captured.json", check_captured_json),
        ("graph-cursor.json", check_cursor),
        ("scheduled-run.log", check_last_run),
    ]:
        ok, msg = fn()
        marker = "[OK]" if ok else "[FAIL]"
        print(f"{marker} {name}")
        for line in msg.split("\n"):
            print(f"  {line}")
        ok_total = ok_total and ok

    print()
    if ok_total:
        print("All state files readable. If pipeline is stuck, retry with:")
        if platform.system() == "Windows":
            print(
                f'  cmd //c "{os.path.join(PIPELINE_ROOT, "scheduled-capture.bat")}"'
            )
        else:
            print(f'  {os.path.join(PIPELINE_ROOT, "scheduled-capture.sh")}')
        return 0
    else:
        print("One or more state files are unreadable.")
        print("Reminder: pipeline is self-healing — cursor doesn't advance on failure,")
        print("so the next successful run will catch up.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
