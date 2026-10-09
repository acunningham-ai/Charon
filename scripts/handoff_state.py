"""handoff_state.py — the live half of a handoff note, generated not remembered.

THE PROBLEM. A handoff used to be a snapshot the model wrote at the end of a
session, and a snapshot is stale the moment work continues. A note written in the
morning can still say "Phase 4 — THE NEXT ACTION" hours after phase 4 shipped, and
it is the first thing the next session reads.

THE SPLIT. Some of a handoff can be known from live state; some can only come
from the session that did the work.

  GENERATED (this script)  — open commitments and whether they are overdue,
                             prior handoffs for the project, and contradictions
                             between a note's stated next action and a
                             commitment already closed.
  AUTHORED (the session)   — what was actually done and why, the judgement calls,
                             what was tried and rejected.

Generating the first half means the note cannot silently disagree with reality
about dates, status, or what is still owed. The authored half stays honest by
being explicitly a record of a moment rather than a claim about now.

Reads: state/commitments.json (via scripts/commitments.py) and
08-Projects/<project>/handoffs/*.md. Writes nothing.

HONEST LIMIT — what the drift check cannot see. It compares handoffs against the
commitment register and against newer handoffs. Work finished that was never a
register entry is invisible to it. The gap closes only once handoffs are
regenerated and dated work is tracked as commitments — it is not retroactive.
Do not read "drift: none" as "every handoff is accurate".

Usage
  python scripts/handoff_state.py --project <Project>      # the state block
  python scripts/handoff_state.py --check                     # drift only
  python scripts/handoff_state.py --check --json
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

VAULT = Path(__file__).resolve().parent.parent
PROJECTS = VAULT / "08-Projects"
SUPERSEDE_STALE_DAYS = 14

sys.path.insert(0, str(VAULT / "scripts"))


def _commitments():
    try:
        import commitments as c
        data = c.load()
        return [(st, it) for st, it in c.open_items(data)], data
    except Exception:
        return [], {"commitments": []}


def _handoff_notes(project=None):
    """Every handoff note, newest first, with its frontmatter status."""
    out = []
    root = PROJECTS / project if project else PROJECTS
    if not root.exists():
        return out
    for p in sorted(root.rglob("handoffs/*.md")):
        try:
            head = io.open(p, encoding="utf-8", errors="replace").read(1200)
        except Exception:
            continue
        m = re.search(r"^date:\s*(\d{4}-\d{2}-\d{2})", head, re.M)
        st = re.search(r"^status:\s*(.+?)\s*$", head, re.M)
        proj = re.search(r"^project:\s*(.+?)\s*$", head, re.M)
        out.append({
            "path": p.relative_to(VAULT).as_posix(),
            "date": m.group(1) if m else "",
            "status": st.group(1) if st else "",
            "project": proj.group(1) if proj else p.parent.parent.name,
        })
    out.sort(key=lambda d: d["date"], reverse=True)
    return out


def _next_action_text(path):
    try:
        s = io.open(VAULT / path, encoding="utf-8", errors="replace").read()
    except Exception:
        return ""
    m = re.search(r"^##+\s*Next action\s*$(.+?)(?=^##|\Z)", s, re.M | re.S)
    return re.sub(r"\s+", " ", m.group(1)).strip()[:400] if m else ""


def drift():
    """Handoffs whose claims no longer hold. Three kinds, all computable."""
    findings = []
    notes = _handoff_notes()
    rows, data = _commitments()
    closed = [i for i in data.get("commitments", []) if i.get("done")]
    today = date.today()

    seen_project = {}
    for n in notes:
        key = n["project"]
        if key in seen_project:
            if "supersed" not in (n["status"] or "").lower():
                findings.append({
                    "kind": "superseded",
                    "path": n["path"],
                    "why": "a newer handoff exists for %s (%s) but this one is not "
                           "marked superseded" % (key, seen_project[key]),
                })
        else:
            seen_project[key] = n["date"]
            try:
                age = (today - datetime.strptime(n["date"], "%Y-%m-%d").date()).days
            except Exception:
                age = 0
            if age >= SUPERSEDE_STALE_DAYS:
                findings.append({
                    "kind": "stale",
                    "path": n["path"],
                    "why": "newest handoff for %s and %d days old — it is the first "
                           "thing the next session reads" % (key, age),
                })

    # A note telling the reader to do something already closed is the worst case:
    # it does not merely go quiet, it actively misdirects.
    for n in notes:
        if "supersed" in (n["status"] or "").lower():
            continue
        na = _next_action_text(n["path"]).lower()
        if not na:
            continue
        for it in closed:
            what = (it.get("what") or "").strip()
            if len(what) < 12:
                continue
            stem = re.sub(r"[^a-z0-9 ]", " ", what.lower()).split()
            probe = " ".join(stem[:4])
            if probe and probe in na:
                findings.append({
                    "kind": "contradicted",
                    "path": n["path"],
                    "why": "next action matches commitment %s which is CLOSED (%s)"
                           % (it.get("id", "?"), what[:60]),
                })
                break
    return findings


def state_block(project=None) -> str:
    rows, _ = _commitments()
    notes = _handoff_notes(project)
    d = drift()
    stamp = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")

    L = []
    L.append("<!-- GENERATED by scripts/handoff_state.py — do not hand-edit.")
    L.append("     Regenerate rather than correct: this block is a view of live")
    L.append("     state, so editing it makes the note disagree with reality. -->")
    L.append("")
    L.append("## Live state (generated %s)" % stamp)
    L.append("")
    L.append("### Open commitments")
    if rows:
        for st, it in rows:
            mark = {"overdue": "❌ OVERDUE", "due-soon": "⚠️ due", "open": "·"}.get(st, st)
            due = it.get("due") or "no date"
            ref = (" — `%s`" % it["ref"]) if it.get("ref") else ""
            L.append("- %s **%s** %s (%s)%s" % (mark, it.get("id", ""), it.get("what", ""), due, ref))
    else:
        L.append("_(none open)_")
    L.append("")

    L.append("### Prior handoffs for this project")
    if notes:
        for n in notes[:6]:
            flag = " — **superseded**" if "supersed" in (n["status"] or "").lower() else ""
            L.append("- `%s` (%s)%s" % (n["path"], n["date"] or "undated", flag))
    else:
        L.append("_(none)_")
    L.append("")

    if d:
        L.append("### ⚠️ Drift detected")
        for f in d:
            L.append("- **%s** — `%s`: %s" % (f["kind"], f["path"], f["why"]))
        L.append("")
    return "\n".join(L)


def main(argv=None) -> int:
    # Force UTF-8 out regardless of the Windows console codepage. Without this,
    # any output carrying the status emoji dies with UnicodeEncodeError under
    # cp1252. errors="replace" so this can never itself crash.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--project")
    ap.add_argument("--check", action="store_true", help="report drift only")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.check:
        d = drift()
        if args.json:
            print(json.dumps({"driftCount": len(d), "findings": d}, indent=2))
            return 0
        if not d:
            print("handoff drift: none — every handoff agrees with live state")
            return 0
        print("handoff drift: %d finding(s)" % len(d))
        for f in d:
            print("  [%s] %s" % (f["kind"], f["path"]))
            print("        %s" % f["why"])
        return 0

    print(state_block(args.project))
    return 0


if __name__ == "__main__":
    sys.exit(main())
