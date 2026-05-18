#!/usr/bin/env python3
"""PostToolUse hook for the Skill tool — logs each slash-command invocation.

Feeds the skill curator (`scripts/skill-curator.py`) by recording which
skills were actually used and when. Without this, the curator falls back
to file mtime as a proxy for last-used (less accurate — mtime moves on
git pulls and edits).

Reads the standard PostToolUse JSON payload from stdin. Extracts the
skill name from `tool_input` (Claude Code emits `{"skill": "<name>", ...}`
for the Skill tool). Logs one event per invocation via the existing
telemetry helper.

Fail-silent: any exception returns 0 with no output. Telemetry must never
break a hook.

Output: JSONL line at `state/telemetry/skill-usage-log/{YYYY-MM-DD}.jsonl`
with `payload.skill = "<name>"`.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from _telemetry import log_event
except Exception:
    def log_event(*_args, **_kwargs):
        pass


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0

    if data.get("tool_name") != "Skill":
        return 0

    tool_input = data.get("tool_input") or {}
    skill = (
        tool_input.get("skill")
        or tool_input.get("skill_name")
        or tool_input.get("name")
        or ""
    ).strip()
    if not skill:
        return 0

    session_id = data.get("session_id", "") or ""
    log_event(
        hook="skill-usage-log",
        event="invoked",
        payload={"skill": skill},
        session_id=session_id,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
