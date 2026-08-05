#!/usr/bin/env python3
"""Shared state for "which slash command is currently running, and where may it write".

Two hooks need to agree on this, so the format lives in one place:

  * ``skill-usage-log.py`` (PostToolUse on ``Skill``) RECORDS the invocation.
  * ``validate-interactive-write.py`` (PreToolUse on writes) READS it and
    confines the write to the command's declared scope.

**Why the Skill tool is the signal.** A PreToolUse payload contains no field
naming the active slash command, so the obvious approach is to grep the user's
prompt for ``/name`` on UserPromptSubmit. That is a guess: the word may appear
conversationally ("should I use /meeting-prep?"), and a guess that *blocks a
write* is a false positive with teeth. Claude Code invokes a typed
``/name`` through the ``Skill`` tool, whose ``tool_input`` carries the name, so
recording at that moment is an observation rather than an inference.

**Scope comes from the command's own frontmatter** (``write-scope:``), so the
authority on where a command may write is the command definition — not a table
in a hook that drifts away from it.

Honest limits, because this is a confinement control and its edges matter:

  * A command with no ``write-scope:`` is **not** scope-enforced. Absence of a
    declaration is not a licence, it is an unenforced gap — and the deterministic
    check reports which commands are in it rather than letting the count look
    complete.
  * The record is per session and TTL-bounded. Writes the model makes long after
    a command has finished are outside the window, deliberately: a stale scope
    that blocks unrelated later work would be worse than no scope.
  * Nested invocation (a seat routing to another verb) records the inner
    command, which is the one actually writing.
"""
import json
import os
import re
import time
from pathlib import Path
from typing import List, Optional

PROJECT_ENV = "CLAUDE_PROJECT_DIR"

# How long a recorded invocation stays authoritative. Long enough for a command
# to finish its writes, short enough that an abandoned command does not keep
# constraining the rest of the session.
TTL_SECONDS = 900


def project_root() -> Path:
    env = os.environ.get(PROJECT_ENV)
    if env:
        return Path(env)
    return Path(__file__).resolve().parent.parent.parent


def state_path() -> Path:
    return project_root() / "state" / "active-command.json"


def command_write_scope(name: str) -> Optional[List[str]]:
    """Read ``write-scope:`` from a command's frontmatter.

    Accepts a YAML list or a single string. Returns None when the command has no
    declaration — distinct from an empty list, which would mean "may write
    nowhere" and is treated as a real (if unusual) declaration.
    """
    # Guard the filename: `name` originates in tool input, and this builds a path.
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", name or ""):
        return None
    cmd = project_root() / ".claude" / "commands" / f"{name}.md"
    if not cmd.is_file():
        return None
    try:
        text = cmd.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.S)
    if not m:
        return None
    fm = m.group(1)

    inline = re.search(r"^write-scope:\s*(\[.*\]|\S.*)$", fm, re.M)
    block = re.search(r"^write-scope:\s*\n((?:\s*-\s*.+\n?)+)", fm, re.M)
    if block:
        return [ln.strip().lstrip("-").strip().strip("'\"")
                for ln in block.group(1).splitlines() if ln.strip()]
    if inline:
        raw = inline.group(1).strip()
        if raw.startswith("["):
            inner = raw[1:-1] if raw.endswith("]") else raw[1:]
            return [p.strip().strip("'\"") for p in inner.split(",") if p.strip()]
        return [raw.strip("'\"")]
    return None


def record(name: str, session_id: str) -> bool:
    """Note that ``name`` is now running. Returns True if a scope was recorded."""
    scope = command_write_scope(name)
    payload = {
        "command": name,
        "session_id": session_id or "",
        "recorded_at": time.time(),
        "write_scope": scope,          # None => command declares no scope
    }
    try:
        p = state_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, p)             # atomic: a reader never sees a half-written file
    except OSError:
        return False
    return scope is not None


def active(session_id: str = "") -> Optional[dict]:
    """The current command record, or None if absent, stale, or another session."""
    try:
        data = json.loads(state_path().read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    if time.time() - float(data.get("recorded_at") or 0) > TTL_SECONDS:
        return None
    # Cross-session leakage would apply one session's scope to another's writes.
    if session_id and data.get("session_id") and data["session_id"] != session_id:
        return None
    return data
