#!/usr/bin/env python3
"""
Telemetry helper for harness hooks.

Append one JSON line per hook invocation to:
    state/telemetry/{hook}/{YYYY-MM-DD}.jsonl

Per-day rotation keeps files grep-friendly and bounds growth without a
janitor. Daily files are immutable once the day rolls — `/telemetry-summary`
rolls them up over a window.

This module is intentionally tiny and dependency-free so any hook can
`from _telemetry import log_event` without slowing cold start.

`log_event` is fail-silent: any IO error is swallowed. Telemetry must
never break a hook.
"""
import json
import os
from datetime import datetime, timezone
from pathlib import Path

VAULT_ENV = "CLAUDE_PROJECT_DIR"


def _vault_root() -> Path:
    env = os.environ.get(VAULT_ENV)
    if env:
        return Path(env)
    here = Path(__file__).resolve().parent
    for cand in [here, *here.parents]:
        if (cand / ".claude").is_dir():
            return cand
    return here


def log_event(hook: str, event: str, payload: dict, session_id: str = "") -> None:
    """Append one JSONL line for `hook`. Never raises."""
    try:
        now = datetime.now(timezone.utc)
        line = {
            "ts": now.isoformat(timespec="seconds"),
            "hook": hook,
            "event": event,
            "session_id": session_id or "",
            "payload": payload or {},
        }
        day = now.strftime("%Y-%m-%d")
        directory = _vault_root() / "state" / "telemetry" / hook
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"{day}.jsonl"
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(line, ensure_ascii=False) + "\n")
    except Exception:
        return
