#!/usr/bin/env python3
"""
SessionStart hook: surface capture-pipeline re-auth requests at session start.

When the scheduled capture pipeline silent-auth fails, fetch-mail.mjs writes a
JSON flag file at capture-pipeline/state/REAUTH-NEEDED.flag. This hook reads
it on every Claude Code session start and emits additionalContext so the first
response surfaces the need clearly with a copy-paste recovery command.

Output: prints additionalContext markdown to stdout (consumed by Claude Code).
Silent if no flag file exists. Never raises (failure here must not block
session start).
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Force UTF-8 stdout on Windows so emoji + symbols render cleanly. Without this,
# the default cp1252 encoder raises on emoji characters.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# Resolve flag path relative to this script. Charon installs vary by user
# location; the capture-pipeline sits as a sibling of scripts/ inside the
# Charon project. Fall back to the documented default if env says otherwise.
SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_CHARON_ROOT = SCRIPT_DIR.parent.parent
CHARON_ROOT = Path(os.environ.get("CHARON_ROOT", str(DEFAULT_CHARON_ROOT)))
FLAG_PATH = CHARON_ROOT / "capture-pipeline" / "state" / "REAUTH-NEEDED.flag"


def main() -> int:
    if not FLAG_PATH.exists():
        return 0

    try:
        payload = json.loads(FLAG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        print(
            "## Capture pipeline: re-auth flag present but unreadable\n\n"
            f"Flag file at `{FLAG_PATH}` exists but couldn't be parsed. "
            "Run `node fetch-mail.mjs auth` interactively to re-authenticate, "
            "or delete the flag file if it's stale."
        )
        return 0

    detected_at = payload.get("detected_at", "unknown")
    reason = payload.get("reason", "(no reason recorded)")
    recovery = payload.get("recovery_command", "node fetch-mail.mjs auth")
    working_dir = payload.get(
        "working_dir", str(CHARON_ROOT / "capture-pipeline")
    )

    elapsed = ""
    try:
        detected_dt = datetime.fromisoformat(detected_at.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = now - detected_dt
        hours = delta.total_seconds() / 3600
        if hours < 1:
            elapsed = f" ({int(delta.total_seconds() / 60)} minutes ago)"
        elif hours < 24:
            elapsed = f" ({hours:.1f} hours ago)"
        else:
            elapsed = f" ({delta.days} days ago)"
    except (ValueError, TypeError):
        pass

    print(
        f"## ⚠️ Capture pipeline: re-auth required\n\n"
        f"**Detected:** {detected_at}{elapsed}\n"
        f"**Reason:** {reason}\n\n"
        f"**Recovery (≈60 seconds):**\n\n"
        f"```\n"
        f"cd \"{working_dir}\"\n"
        f"{recovery}\n"
        f"```\n\n"
        f"The pipeline will pick up where it left off on the next scheduled "
        f"run. Flag clears automatically on next successful run.\n"
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        sys.stderr.write(f"check-reauth-flag.py: {exc}\n")
        sys.exit(0)
