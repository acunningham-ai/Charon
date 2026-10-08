#!/usr/bin/env python3
"""check-commitments.py — surface overdue / due-soon harness commitments at session start.

Dated commitments agreed in a working session (a shadow-window review, a port
decision) appear in no captured message, so nothing that scans your inbox can
find them. `scripts/commitments.py` is their register; this hook is the
independent path that reads it at every session start — so a date cannot be
missed because a TODO regeneration failed or a morning job didn't run.

Silent when nothing is overdue or due within the window — a hook that speaks on
every start gets ignored, and an ignored hook protects nothing. Silent too when
there is no register yet (nothing has been recorded).

Exit 0 always. Surfacing is never worth breaking a session over.
"""
from __future__ import annotations

import io
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# Force UTF-8 stdout on Windows so emoji render cleanly (cp1252 raises on '⏰').
# WITHOUT THIS THE HOOK IS SILENT: the write below raises UnicodeEncodeError, the
# outer except swallows it, exit 0 — and a commitment never surfaces. That is
# the exact failure this hook exists to prevent; on the reference deployment it
# hid for three weeks before being found.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

DUE_SOON_DAYS = 7
VAULT = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
STORE = VAULT / "state" / "commitments.json"


def main() -> int:
    try:
        data = json.loads(io.open(STORE, encoding="utf-8").read())
    except Exception:
        return 0  # no register yet, or unreadable — never block a session

    today = date.today()
    horizon = today + timedelta(days=DUE_SOON_DAYS)
    overdue, soon = [], []
    for it in data.get("commitments", []):
        if it.get("done"):
            continue
        raw = (it.get("due") or "").strip()
        if not raw:
            continue
        try:
            due = datetime.strptime(raw, "%Y-%m-%d").date()
        except Exception:
            continue
        if due < today:
            overdue.append((due, it))
        elif due <= horizon:
            soon.append((due, it))

    if not overdue and not soon:
        return 0

    out = ["## ⏰ Harness commitments"]
    # Sort by date ONLY. A bare sorted() on (date, dict) tuples compares the dicts
    # when two commitments share a due date — TypeError, swallowed by the outer
    # except, and the hook goes silent on exactly the busiest days.
    for due, it in sorted(overdue, key=lambda t: t[0]):
        days = (today - due).days
        out.append("- ❌ **OVERDUE %d day%s** — %s (%s, due %s)"
                   % (days, "" if days == 1 else "s", it.get("what", ""), it.get("id", ""), due))
    for due, it in sorted(soon, key=lambda t: t[0]):
        days = (due - today).days
        when = "today" if days == 0 else ("tomorrow" if days == 1 else "in %d days" % days)
        out.append("- ⚠️ due %s — %s (%s, %s)" % (when, it.get("what", ""), it.get("id", ""), due))
    out.append("")
    out.append("_Close with_ `python scripts/commitments.py --done <id>`")
    sys.stdout.write("\n".join(out) + "\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        # Fail open -- a reminder must never block a session -- but never
        # SILENTLY: a bare `except: exit 0` here once hid two separate bugs on the
        # reference deployment for weeks while commitments went overdue. Log the
        # fall-open so the watch can count it, and say so on stdout.
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from _verdict import emit_fell_open
            emit_fell_open(hook="check-commitments", rule="render",
                           reason="commitment reminder crashed; nothing was shown",
                           error=repr(exc))
        except Exception:
            pass
        try:
            sys.stdout.write("## Harness commitments\n- The commitment reminder failed "
                             "(%s) - run `python scripts/commitments.py` to see what is due.\n"
                             % type(exc).__name__)
        except Exception:
            pass
        sys.exit(0)
