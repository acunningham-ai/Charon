#!/usr/bin/env python3
"""Decision channel for harness auto-review proposals — the missing nerve.

THE GAP THIS CLOSES. A failure happens, the review engine explains how and why, and
you get the fix options with their trade-offs — then you need somewhere to give the
go-ahead. `on-error.py` banks every automation failure and `harness_autoreview.py` turns
one into a {root cause + ranked options + recommendation} note. Without this module
there is nowhere to record your answer, and the notes pile up unread. (On the reference
deployment, 43 failures were banked over 61 days before this existed and none reached
the user.)

WHY "GO-AHEAD" IS NOT AUTO-APPLY. Pre-approved remediations are canned RECOVERY actions
on a closed allowlist. A novel code fix ("change line 281 to process.exitCode") can never
sit on that list, because the list has to exist before the failure does. So accepting an
option QUEUES WORK; it never executes anything. This module deliberately does not import
the auto-heal apply module — the same observe != act rule that governs the review engine.

WHAT IT DOES
  --list                          open proposals (artefact exists, no decision recorded)
  --accept <event_id> --option N  record the pick; it becomes a queued dev item
  --decline <event_id> --note ".." record a no; stops it re-surfacing forever
  --defer <event_id>              leave open, but mute until --list --all
  --queue                         the dev queue, highest priority first
  --todo-block                    render the pinned markdown block for TODO.md
  --done <event_id>               mark a queued item implemented

Exit codes: 0 ok · 1 bad args / not found. Never raises into a caller.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

VAULT = Path(__file__).resolve().parents[1]
HARNESS_NOTES = VAULT / "00-Inbox" / "_harness"
LEDGER = VAULT / "state" / "harness-fixes" / "decisions.jsonl"

#: Artefacts the review engine writes. `review-YYYY-MM-DD.md` (shadow-promotion
#: reviews) are a DIFFERENT type and must not be picked up — conflating the two is
#: how the artefact count was misreported earlier today.
ARTEFACT_RE = re.compile(r"^\d{4}-\d{2}-\d{2}-review-(?P<event_id>.+)\.md$")

DECISIONS = ("accept", "decline", "defer")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- Artefact parsing -------------------------------------------------

def _frontmatter(text: str) -> dict:
    if not text.startswith("---"):
        return {}
    end = text.find("\n---", 3)
    if end == -1:
        return {}
    out = {}
    for line in text[3:end].splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            out[k.strip()] = v.strip()
    return out


def parse_options(text: str) -> list[dict]:
    """Extract the ranked options. Best-effort: a malformed artefact still lists.

    Options look like:  `1. **Title**  [effort: low · risk: low]`
    """
    opts = []
    body = text.split("## Ranked fix options", 1)
    if len(body) < 2:
        return opts
    for m in re.finditer(r"^(\d+)\.\s+\*\*(.+?)\*\*(.*)$", body[1], re.MULTILINE):
        opts.append({
            "n": int(m.group(1)),
            "title": m.group(2).strip(),
            "tags": m.group(3).strip().strip("[]"),
        })
    return opts


def load_artefacts() -> dict[str, dict]:
    """event_id -> {path, automation, date, options, recommendation}."""
    out: dict[str, dict] = {}
    if not HARNESS_NOTES.is_dir():
        return out
    for p in sorted(HARNESS_NOTES.glob("*-review-*.md")):
        m = ARTEFACT_RE.match(p.name)
        if not m:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        fm = _frontmatter(text)
        if fm.get("type") != "harness-auto-review":
            continue  # a shadow-promotion review, not a failure proposal
        eid = fm.get("event_id") or m.group("event_id")
        rec = ""
        if "## Recommendation" in text:
            rec = text.split("## Recommendation", 1)[1].strip().split("\n\n")[0].strip()
        out[eid] = {
            "event_id": eid,
            "path": str(p.relative_to(VAULT)).replace("\\", "/"),
            "automation": fm.get("automation", "?"),
            "date": fm.get("date", ""),
            "exit_code": fm.get("exit_code", ""),
            "options": parse_options(text),
            "recommendation": rec[:400],
        }
    return out


# --- Ledger -----------------------------------------------------------

def load_decisions() -> dict[str, dict]:
    """event_id -> latest decision record. Last write wins, so a mind can change."""
    out: dict[str, dict] = {}
    if not LEDGER.exists():
        return out
    try:
        for line in LEDGER.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except Exception:
                continue
            if rec.get("event_id"):
                out[rec["event_id"]] = rec
    except OSError:
        pass  # unreadable ledger -> everything reads as open, which is the safe way to fail
    return out


def append_decision(rec: dict) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


# --- Queries ----------------------------------------------------------

def open_proposals(include_deferred: bool = False) -> list[dict]:
    arts, decs = load_artefacts(), load_decisions()
    out = []
    for eid, a in arts.items():
        d = decs.get(eid)
        if d is None:
            out.append(a)
        elif d.get("decision") == "defer" and include_deferred:
            out.append({**a, "deferred": True})
    return sorted(out, key=lambda a: a.get("date", ""), reverse=True)


def dev_queue() -> list[dict]:
    """Accepted-but-not-done items. This IS the top of the dev pipeline."""
    arts, decs = load_artefacts(), load_decisions()
    out = []
    for eid, d in decs.items():
        if d.get("decision") != "accept" or d.get("status") == "done":
            continue
        a = arts.get(eid, {})
        out.append({**d, "automation": a.get("automation", d.get("automation", "?")),
                    "path": a.get("path", d.get("path", ""))})
    return sorted(out, key=lambda r: r.get("ts", ""))


# --- Rendering --------------------------------------------------------

def render_todo_block() -> str:
    """The pinned block for the top of TODO.md. '' when there is nothing to say."""
    q, o = dev_queue(), open_proposals()
    if not q and not o:
        return ""
    lines = ["## 🔧 Harness self-healing — needs you", ""]
    if q:
        lines.append(f"**{len(q)} approved fix(es) queued — top of the dev pipeline**")
        lines.append("")
        for r in q:
            lines.append(f"- **{r.get('automation')}** — option {r.get('option')}: "
                         f"{r.get('option_title', '?')}")
            if r.get("note"):
                lines.append(f"  - your note: {r['note']}")
            lines.append(f"  - `{r.get('path', '')}` · mark done with "
                         f"`python scripts/harness_fix.py --done {r.get('event_id')}`")
        lines.append("")
    if o:
        lines.append(f"**{len(o)} proposal(s) awaiting your call**")
        lines.append("")
        for a in o:
            lines.append(f"- **{a['automation']}** (exit {a.get('exit_code','?')}, "
                         f"{a.get('date','')}) — {len(a['options'])} options")
            if a.get("recommendation"):
                lines.append(f"  - recommended: {a['recommendation'][:160]}")
            lines.append(f"  - read `{a['path']}` · decide with "
                         f"`python scripts/harness_fix.py --accept {a['event_id']} --option N`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# --- CLI --------------------------------------------------------------

def _decide(kind: str, event_id: str, option: int | None, note: str | None) -> int:
    arts = load_artefacts()
    a = arts.get(event_id)
    if a is None:
        print(f"No auto-review artefact for event_id '{event_id}'.", file=sys.stderr)
        print(f"Open proposals: {', '.join(x['event_id'] for x in open_proposals()) or '(none)'}",
              file=sys.stderr)
        return 1
    title = None
    if kind == "accept":
        if option is None:
            print("--accept needs --option N (which fix you're approving).", file=sys.stderr)
            return 1
        match = [o for o in a["options"] if o["n"] == option]
        if not match:
            print(f"Option {option} not found. Available: "
                  f"{', '.join(str(o['n']) for o in a['options']) or '(none parsed)'}",
                  file=sys.stderr)
            return 1
        title = match[0]["title"]
    rec = {
        "event_id": event_id, "ts": _now(), "decision": kind,
        "option": option, "option_title": title, "note": note,
        "automation": a["automation"], "path": a["path"],
        "status": "queued" if kind == "accept" else kind,
    }
    append_decision(rec)
    if kind == "accept":
        print(f"✅ Queued: {a['automation']} — option {option}: {title}")
        print("   Top of the dev pipeline. Nothing was executed; this is work to implement.")
    elif kind == "decline":
        print(f"Recorded as declined: {a['automation']}. It won't surface again.")
    else:
        print(f"Deferred: {a['automation']}. Shows again under --list --all.")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Decide on harness auto-review proposals")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true", help="open proposals")
    g.add_argument("--queue", action="store_true", help="approved fixes awaiting implementation")
    g.add_argument("--todo-block", action="store_true", help="render the TODO.md block")
    g.add_argument("--accept", metavar="EVENT_ID")
    g.add_argument("--decline", metavar="EVENT_ID")
    g.add_argument("--defer", metavar="EVENT_ID")
    g.add_argument("--done", metavar="EVENT_ID")
    ap.add_argument("--option", type=int, help="which ranked option you are approving")
    ap.add_argument("--note", help="your reasoning — recorded with the decision")
    ap.add_argument("--all", action="store_true", help="--list also shows deferred")
    args = ap.parse_args(argv)

    if args.todo_block:
        sys.stdout.write(render_todo_block())
        return 0

    if args.list:
        props = open_proposals(include_deferred=args.all)
        if not props:
            print("No open harness proposals.")
            return 0
        print(f"{len(props)} open proposal(s):\n")
        for a in props:
            flag = " [deferred]" if a.get("deferred") else ""
            print(f"  {a['event_id']}{flag}")
            print(f"    {a['automation']} · exit {a.get('exit_code','?')} · {a.get('date','')}")
            for o in a["options"]:
                print(f"      {o['n']}. {o['title']}  {('[' + o['tags'] + ']') if o['tags'] else ''}")
            if a.get("recommendation"):
                print(f"    recommended: {a['recommendation'][:200]}")
            print(f"    {a['path']}\n")
        return 0

    if args.queue:
        q = dev_queue()
        if not q:
            print("Dev queue empty — no approved harness fixes awaiting implementation.")
            return 0
        print(f"{len(q)} approved fix(es), oldest first:\n")
        for r in q:
            print(f"  {r['event_id']}  {r.get('automation')}")
            print(f"    option {r.get('option')}: {r.get('option_title')}")
            if r.get("note"):
                print(f"    note: {r['note']}")
        return 0

    if args.done:
        decs = load_decisions()
        d = decs.get(args.done)
        if not d or d.get("decision") != "accept":
            print(f"'{args.done}' is not an accepted item.", file=sys.stderr)
            return 1
        append_decision({**d, "ts": _now(), "status": "done"})
        print(f"Marked done: {d.get('automation')} — option {d.get('option')}")
        return 0

    for kind in DECISIONS:
        eid = getattr(args, kind)
        if eid:
            return _decide(kind, eid, args.option, args.note)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
