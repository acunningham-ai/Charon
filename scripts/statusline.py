#!/usr/bin/env python3
"""Charon status line for Claude Code.

Claude Code runs this after each turn, sends its status JSON on stdin, and shows
what this prints under the prompt:

    line 1: the current folder, with your home folder shown as ~
    line 2: model | CTX % | Session % (5-hour limit) | Total % (7-day limit)

A line-2 segment is left out when its field is missing or is not a number. Bad,
empty or truncated input never raises: the script prints what it can and exits 0.
Standard library only (no jq, no Node).

JSON fields read (from Claude Code's status line input):
    workspace.current_dir, else cwd      folder for line 1
    model.display_name, else model.id    model name
    context_window.used_percentage       CTX %
    rate_limits.five_hour.used_percentage  Session %
    rate_limits.seven_day.used_percentage  Total %

Set NO_COLOR to any value to print without colours.

Wired into `statusLine` in your Claude Code settings by
`scripts/post_install_wiring.py`, through the `scripts/hook` launcher.
"""
from __future__ import annotations

import json
import math
import os
import sys
from pathlib import Path

MAX_INPUT = 1_000_000  # bytes; the real payload is a few KB
MAX_MODEL = 60
# C0 controls, DEL and C1 controls: stripped from every value we print, so a
# folder or model name cannot carry its own terminal escape sequence.
_CTRL = set(range(0x20)) | {0x7F} | set(range(0x80, 0xA0))


def _clean(text: str) -> str:
    return "".join(ch for ch in text if ord(ch) not in _CTRL)


def _get(data, *keys):
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def _pct(value) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    return f"{int(math.floor(value + 0.5))}%"


def _folder(data) -> str:
    cwd = _get(data, "workspace", "current_dir")
    if not isinstance(cwd, str) or not cwd.strip():
        cwd = _get(data, "cwd")
    if not isinstance(cwd, str) or not cwd.strip():
        try:
            cwd = os.getcwd()
        except OSError:
            cwd = ""
    cwd = cwd.replace("\\", "/")
    try:
        home = str(Path.home()).replace("\\", "/").rstrip("/")
    except Exception:  # no resolvable home: show the full path
        home = ""
    if home:
        fold = os.name == "nt"  # Windows paths are case-insensitive
        a, b = (cwd.lower(), home.lower()) if fold else (cwd, home)
        if a == b:
            cwd = "~"
        elif a.startswith(b + "/"):
            cwd = "~" + cwd[len(home):]
    return _clean(cwd)


def _model(data) -> str | None:
    for key in ("display_name", "id"):
        name = _get(data, "model", key)
        if isinstance(name, str):
            name = _clean(name).strip()
            if name:
                return name[:MAX_MODEL]
    return None


def render(raw: str, colour: bool = True) -> str:
    try:
        data = json.loads(raw) if raw.strip() else {}
    except Exception:  # garbage, truncated or too deeply nested
        data = {}
    if not isinstance(data, dict):
        data = {}

    def paint(code: str, text: str) -> str:
        return f"\x1b[{code}m{text}\x1b[0m" if colour else text

    parts = []
    model = _model(data)
    if model:
        parts.append(paint("35", model))
    ctx = _pct(_get(data, "context_window", "used_percentage"))
    if ctx:
        parts.append(paint("33", f"CTX {ctx}"))
    session = _pct(_get(data, "rate_limits", "five_hour", "used_percentage"))
    if session:
        parts.append(paint("32", f"Session {session}"))
    total = _pct(_get(data, "rate_limits", "seven_day", "used_percentage"))
    if total:
        parts.append(paint("34", f"Total {total}"))

    lines = [paint("36", _folder(data))]
    if parts:
        lines.append(" | ".join(parts))
    return "\n".join(lines)


def main() -> int:
    try:
        raw = sys.stdin.buffer.read(MAX_INPUT).decode("utf-8", errors="replace")
    except Exception:
        raw = ""
    try:
        out = render(raw, colour=not os.environ.get("NO_COLOR"))
    except Exception:  # never break the user's prompt line
        out = ""
    try:
        # Bytes, not text: text-mode stdout on Windows would turn "\n" into "\r\n".
        sys.stdout.buffer.write(out.encode("utf-8", errors="replace"))
        sys.stdout.flush()
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
