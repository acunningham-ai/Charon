"""commitments.py — the harness's own dated-commitment register.

WHY THIS EXISTS
---------------
Dated commitments — "review this shadow rule on the 17th", "decide the port by
Friday" — are agreed inside working sessions. They are not in any email or chat
message, so no inbox scan or TODO generator can ever find them. A commitment that
lives only in a project doc reaches you only if someone remembers it.

This is that missing source: deterministic, file-backed, one JSON register. The
`check-commitments.py` SessionStart hook reads it directly, so an overdue date
surfaces at the start of your next session even if every other surface (a stale
TODO, a failed morning job) missed it.

A commitment recorded only in a project doc is invisible, and invisible
commitments expire without anyone deciding to let them expire — which is how a
"two-week shadow window" quietly becomes permanent.

USAGE
  python scripts/commitments.py --list            # everything open
  python scripts/commitments.py --due             # overdue + due within 7 days
  python scripts/commitments.py --add "..." --date 2026-08-17 --kind review \
                                --ref "08-Projects/..." --owner me
  python scripts/commitments.py --done <id> [--note "..."]
  python scripts/commitments.py --json            # machine-readable

Store: <repo>/state/commitments.json (git-ignored; created on the first --add)
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

VAULT = Path(__file__).resolve().parent.parent
STORE = VAULT / "state" / "commitments.json"

KINDS = ("review", "gate", "port", "followup", "decision")
DUE_SOON_DAYS = 7
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _today() -> date:
    return date.today()


def load() -> dict:
    try:
        return json.loads(io.open(STORE, encoding="utf-8").read())
    except Exception:
        return {"version": 1, "commitments": []}


def save(data: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(STORE)


def _parse(d: str):
    try:
        return datetime.strptime(d, "%Y-%m-%d").date()
    except Exception:
        return None


def status_of(item, today=None):
    """overdue / due-soon / open / done. Overdue is a FIRST-CLASS state —
    something past its date is not 'still open'."""
    if item.get("done"):
        return "done"
    today = today or _today()
    d = _parse(item.get("due", ""))
    if not d:
        return "open"
    if d < today:
        return "overdue"
    if d <= today + timedelta(days=DUE_SOON_DAYS):
        return "due-soon"
    return "open"


def open_items(data, today=None):
    out = []
    for it in data.get("commitments", []):
        if it.get("done"):
            continue
        out.append((status_of(it, today), it))
    order = {"overdue": 0, "due-soon": 1, "open": 2}
    out.sort(key=lambda t: (order.get(t[0], 3), t[1].get("due") or "9999-99-99"))
    return out


def next_id(data) -> str:
    n = 0
    for it in data.get("commitments", []):
        m = re.match(r"C(\d+)$", str(it.get("id", "")))
        if m:
            n = max(n, int(m.group(1)))
    return "C%03d" % (n + 1)


def cmd_add(args) -> int:
    if args.date and not DATE_RE.match(args.date):
        print("--date must be YYYY-MM-DD (absolute; no relative dates)", file=sys.stderr)
        return 2
    data = load()
    item = {
        "id": next_id(data),
        "what": args.add.strip(),
        "due": args.date or "",
        "kind": args.kind,
        "owner": args.owner,
        "ref": args.ref or "",
        "created": _today().isoformat(),
        "done": False,
    }
    data.setdefault("commitments", []).append(item)
    save(data)
    print("added %s  %s  due %s" % (item["id"], item["what"][:60], item["due"] or "(no date)"))
    return 0


def cmd_done(args) -> int:
    data = load()
    for it in data.get("commitments", []):
        if str(it.get("id")) == args.done:
            it["done"] = True
            it["closed"] = _today().isoformat()
            if args.note:
                it["close_note"] = args.note
            save(data)
            print("closed %s — %s" % (it["id"], it["what"][:60]))
            return 0
    print("no commitment with id %s" % args.done, file=sys.stderr)
    return 1


def render(rows, header=True) -> str:
    if not rows:
        return "_(no open commitments)_"
    mark = {"overdue": "🔴 OVERDUE", "due-soon": "🟡 due", "open": "· open"}
    lines = []
    for st, it in rows:
        due = it.get("due") or "no date"
        ref = (" — `%s`" % it["ref"]) if it.get("ref") else ""
        lines.append("- [ ] **%s** %s (%s) — %s%s"
                     % (it["id"], it["what"], due, mark.get(st, st), ref))
    return "\n".join(lines)


def main(argv=None) -> int:
    # Force UTF-8 out regardless of the Windows console codepage. Without this,
    # --due/--list die with UnicodeEncodeError on the status emoji under cp1252,
    # and `--json > file` writes cp1252 bytes that later break json.load(utf-8).
    # errors="replace" so this can never itself crash.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--list", action="store_true", help="all open commitments")
    ap.add_argument("--due", action="store_true", help="overdue + due within %d days" % DUE_SOON_DAYS)
    ap.add_argument("--json", action="store_true", help="machine-readable")
    ap.add_argument("--add", metavar="TEXT")
    ap.add_argument("--date", metavar="YYYY-MM-DD")
    ap.add_argument("--kind", choices=KINDS, default="followup")
    ap.add_argument("--owner", default="me")
    ap.add_argument("--ref", metavar="PATH")
    ap.add_argument("--done", metavar="ID")
    ap.add_argument("--note", metavar="TEXT")
    args = ap.parse_args(argv)

    if args.add:
        return cmd_add(args)
    if args.done:
        return cmd_done(args)

    data = load()
    rows = open_items(data)
    if args.due:
        rows = [r for r in rows if r[0] in ("overdue", "due-soon")]

    if args.json:
        print(json.dumps({
            "generated": datetime.now().isoformat(timespec="seconds"),
            "openCount": len(rows),
            "commitments": [dict(status=st, **it) for st, it in rows],
        }, ensure_ascii=False, indent=2))
        return 0

    print(render(rows))
    return 0


if __name__ == "__main__":
    sys.exit(main())
