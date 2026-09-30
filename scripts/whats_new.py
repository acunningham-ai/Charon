"""What did this update actually give you?

Charon's update path used to answer that question with one line:

    impact  : capability update (new commands / engine / rules)

...and leave the rest to a CHANGELOG that is now approaching 200KB. Worse, a
capability that needs a configuration answer from you shipped its config file and
nothing else: the update command scaffolds folders (`first-run.py --scaffold-only`)
but never asks a question, so a question added to the wizard *after* you installed
never reached you. Three such configs shipped that way in one release.

This module is the shared engine behind both halves of the fix:

  * `charon-update` calls it after a successful pull to print, in plain language,
    what you can now do that you could not before -- and to offer the questions
    any new capability needs answered.
  * `first-run.py --catch-up` asks exactly those questions and nothing else, so an
    existing install can catch up without re-running the whole wizard.

The data comes from `scripts/capability-notes.json`, generated upstream from the
capability manifest. If that file is missing, every function here degrades to
"nothing to report" rather than failing -- an update must never break because its
release notes are absent.

State lives in `~/.charon-capability-state.json`, deliberately separate from
`~/.charon-first-run-state.json` so that recording "you have seen this note" can
never corrupt your wizard answers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

NOTES_FILE = Path(__file__).resolve().parent / "capability-notes.json"
SEEN_FILE = Path.home() / ".charon-capability-state.json"
FIRST_RUN_STATE = Path.home() / ".charon-first-run-state.json"


# --- Loading (every path degrades quietly to "nothing to report") ------

def load_notes(path: Path | None = None) -> list[dict[str, Any]]:
    """Capability notes shipped with this release. [] if unavailable."""
    p = path or NOTES_FILE
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return []
    caps = data.get("capabilities")
    return caps if isinstance(caps, list) else []


def load_seen(path: Path | None = None) -> set[str]:
    """Capability ids already shown to this user."""
    p = path or SEEN_FILE
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        seen = data.get("seen")
        return set(seen) if isinstance(seen, list) else set()
    except Exception:
        return set()


def save_seen(ids: set[str], path: Path | None = None) -> None:
    p = path or SEEN_FILE
    try:
        p.write_text(json.dumps({"seen": sorted(ids)}, indent=2), encoding="utf-8")
    except OSError:
        pass  # a note re-shown once is harmless; a failed update is not


def answered_question_ids(path: Path | None = None) -> set[str]:
    """Question ids the user has already answered in the wizard."""
    p = path or FIRST_RUN_STATE
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return {k for k in data if not k.startswith("_")} if isinstance(data, dict) else set()
    except Exception:
        return set()


# --- Queries (pure; the CLI and first-run both use these) --------------

def pending_notes(notes: list[dict], seen: set[str]) -> list[dict]:
    """Capabilities this user has not yet been told about."""
    return [n for n in notes if n.get("id") and n["id"] not in seen]


def pending_questions(notes: list[dict], answered: set[str]) -> list[str]:
    """Question ids a shipped capability needs, that the user has not answered.

    Order-preserving and de-duplicated: two capabilities can legitimately need the
    same answer, and asking it twice in one session reads as a bug.
    """
    out: list[str] = []
    for n in notes:
        for q in n.get("questions") or []:
            if q not in answered and q not in out:
                out.append(q)
    return out


def questions_owed_by(notes: list[dict], qid: str) -> list[str]:
    """Which capabilities need this question -- so the wizard can say WHY it asks."""
    return [n.get("id", "?") for n in notes if qid in (n.get("questions") or [])]


# --- Rendering --------------------------------------------------------

def render(notes: list[dict], answered: set[str], width: int = 78) -> str:
    """The plain-language 'what you can now do' block. '' when there is nothing."""
    if not notes:
        return ""
    lines = ["", "  New in this update", "  " + "-" * (width - 4), ""]
    for n in notes:
        name = n.get("id", "?")
        ver = f"  ({n['shipped_in']})" if n.get("shipped_in") else ""
        lines.append(f"  * {name}{ver}")
        blurb = (n.get("blurb") or "").strip()
        if blurb:
            lines += ["    " + ln for ln in _wrap(blurb, width - 6)]
        owed = [q for q in (n.get("questions") or []) if q not in answered]
        if owed:
            lines.append(f"    needs a setting from you: {', '.join(owed)}")
        lines.append("")
    return "\n".join(lines)


def _wrap(text: str, width: int) -> list[str]:
    words, line, out = text.split(), "", []
    for w in words:
        if line and len(line) + 1 + len(w) > width:
            out.append(line)
            line = w
        else:
            line = f"{line} {w}".strip()
    if line:
        out.append(line)
    return out


# --- CLI --------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="Show what a Charon update gave you, and what it still needs from you")
    ap.add_argument("--check", action="store_true",
                    help="report without marking the notes as seen")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--all", action="store_true",
                    help="show every capability note, not just the unseen ones")
    args = ap.parse_args(argv)

    notes = load_notes()
    seen = set() if args.all else load_seen()
    answered = answered_question_ids()
    pending = pending_notes(notes, seen)
    owed = pending_questions(pending, answered)

    if args.json:
        print(json.dumps({"pending": pending, "questions": owed}, indent=2))
    else:
        block = render(pending, answered)
        if not block:
            print("  Nothing new to report.")
        else:
            print(block)
            if owed:
                print("  To answer the settings above:")
                print("      python scripts/first-run.py --catch-up")
                print()

    if not args.check and not args.all and pending:
        save_seen(seen | {n["id"] for n in pending if n.get("id")})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
