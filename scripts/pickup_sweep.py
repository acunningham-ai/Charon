"""pickup_sweep.py — lifecycle for the MEMORY.md 📌 Pickups section.

THE PROBLEM. Pickups are the "read first" surface, so anything that lands there
stays there. Nothing ever declared one finished, so the section only grew: on the
reference deployment it reached 23 of the index's 64 bullets and 5,410 of its bytes. A
read-first list that is mostly finished work is not read first — it is skimmed,
which defeats the point of having one.

THE LIFECYCLE:
  done-marker  — a pickup carrying ✅ / DONE / ⛔ has declared itself finished
  stale sweep  — a pickup whose backing file has not been touched in 30 days has
                 gone quiet, whether or not anyone said so
  archive      — both classes are PROPOSED for removal from Pickups; the memory
                 or note itself is never deleted, only its claim on the
                 read-first surface

PROPOSE-ONLY by default. `--apply` is explicit and never the default, because a
sweep that silently edits the index would be the harness deciding what you still
care about.

Removing a pickup bullet does NOT lose the pointer: every memory file is found by
its own description, and the end-of-turn reachability check keeps it that way, so
a demoted pickup is still reachable by asking for it. Works with the MEMORY.md
working set (scripts/memory_working_set.py): Pickups stays the one authored
section of MEMORY.md, and this is what keeps it short.

Usage
  python scripts/pickup_sweep.py              # report only
  python scripts/pickup_sweep.py --report     # also write 00-Inbox/_harness/
  python scripts/pickup_sweep.py --apply      # edit MEMORY.md (explicit)
"""
from __future__ import annotations

import argparse
import io
import os
import re
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts"))
from lib.harness_paths import memory_root, vault_root  # noqa: E402

VAULT = vault_root()
MEMDIR = memory_root()
MEMORY = MEMDIR / "MEMORY.md"
REPORT_DIR = VAULT / "00-Inbox" / "_harness"

PICKUP_HEADING = re.compile(r"^##\s*📌", re.M)
NEXT_HEADING = re.compile(r"^##\s", re.M)
LINK = re.compile(r"\[([^\]]*)\]\(([^)]*)\)")

STALE_DAYS = 30
# Markers a human puts on a bullet to say "this is finished".
DONE_MARKERS = ("✅", "⛔", "DONE", "SHIPPED", "CLOSED", "COMPLETE")


def _resolve(target: str):
    t = urllib.parse.unquote(target)
    p = Path(os.path.normpath(str(MEMDIR / t)))
    if p.exists():
        return p
    alt = Path(os.path.normpath(str(MEMDIR / ".." / t)))
    return alt if alt.exists() else None


def pickups_block(text: str):
    m = PICKUP_HEADING.search(text)
    if not m:
        return None, None
    start = m.start()
    nxt = NEXT_HEADING.search(text, m.end())
    end = nxt.start() if nxt else len(text)
    return start, end


def classify(line: str, now):
    """(verdict, detail). Verdict: done / stale / live / unresolved."""
    if any(mk in line for mk in DONE_MARKERS):
        hit = next(mk for mk in DONE_MARKERS if mk in line)
        return "done", "carries %s" % hit
    m = LINK.search(line)
    if not m:
        return "live", "no link to age"
    p = _resolve(m.group(2))
    if p is None:
        return "unresolved", "target missing: %s" % m.group(2)[:60]
    try:
        age = (now - datetime.fromtimestamp(p.stat().st_mtime, timezone.utc)).days
    except Exception:
        return "live", "unreadable mtime"
    if age >= STALE_DAYS:
        return "stale", "%s untouched %d days" % (p.name, age)
    return "live", "%s touched %d days ago" % (p.name, age)


def sweep():
    text = io.open(MEMORY, encoding="utf-8").read()
    start, end = pickups_block(text)
    if start is None:
        return text, []
    now = datetime.now(timezone.utc)
    rows = []
    for line in text[start:end].split("\n"):
        if not line.startswith("- "):
            continue
        verdict, detail = classify(line, now)
        rows.append((verdict, detail, line))
    return text, rows


def main(argv=None) -> int:
    # Windows consoles default to cp1252, which cannot encode the 📌 in the help
    # text or the 'no 📌 Pickups' line: --help crashed (2026-10-08). UTF-8 out.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except Exception:
            pass
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="edit MEMORY.md (explicit)")
    ap.add_argument("--report", action="store_true", help="write a report artefact")
    args = ap.parse_args(argv)

    if not MEMORY.is_file():
        print("MEMORY.md not found: %s" % MEMORY, file=sys.stderr)
        return 1

    text, rows = sweep()
    if not rows:
        print("pickup-sweep: no 📌 Pickups section found")
        return 0

    buckets = {}
    for v, d, line in rows:
        buckets.setdefault(v, []).append((d, line))
    proposed = buckets.get("done", []) + buckets.get("stale", [])

    print("pickup-sweep: %d pickups — %d done · %d stale (>=%dd) · %d live · %d unresolved"
          % (len(rows), len(buckets.get("done", [])), len(buckets.get("stale", [])),
             STALE_DAYS, len(buckets.get("live", [])), len(buckets.get("unresolved", []))))
    for label in ("done", "stale", "unresolved"):
        for d, line in buckets.get(label, []):
            m = LINK.search(line)
            name = m.group(1) if m else line[2:40]
            print("  [%s] %-46s %s" % (label.upper()[:6], name[:46], d))

    if args.report and proposed:
        REPORT_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y-%m-%d")
        out = REPORT_DIR / ("pickup-sweep-%s.md" % stamp)
        body = ["---", "type: harness-report", "date: %s" % stamp,
                "trust: harness-generated", "---", "",
                "# Pickup sweep — %s" % stamp, "",
                "%d of %d pickups proposed for archive. Nothing has been changed."
                % (len(proposed), len(rows)), "",
                "Removing a bullet does not lose the note — every memory file is",
                "found by its own description, so a demoted pickup stays reachable.", ""]
        for label in ("done", "stale"):
            if not buckets.get(label):
                continue
            body.append("## %s" % label.title())
            for d, line in buckets[label]:
                body.append("- %s" % d)
                body.append("  `%s`" % line.strip()[:160])
            body.append("")
        body.append("Apply with `python scripts/pickup_sweep.py --apply`.")
        out.write_text("\n".join(body), encoding="utf-8")
        print("  report: %s" % out)

    if args.apply:
        if not proposed:
            print("  nothing to apply")
            return 0

        # STALE IS NOT FINISHED. A pickup that has gone quiet may simply have
        # been deprioritised, so removing it from the read-first surface without
        # recording it anywhere would quietly lose an open thread — the exact
        # second-brain failure this vault exists to prevent. Stale items are
        # PROMOTED to the commitments register (undated) rather than dropped.
        # Items carrying a done-marker are genuinely finished and just go.
        promoted = 0
        try:
            import commitments as _c  # scripts/ is already on sys.path
            data = _c.load()
            existing = {(i.get("ref") or "") for i in data.get("commitments", [])}
            for detail, line in buckets.get("stale", []):
                m = LINK.search(line)
                ref = urllib.parse.unquote(m.group(2)) if m else ""
                title = m.group(1) if m else line[2:60]
                if ref and ref in existing:
                    continue          # already tracked — don't duplicate
                data.setdefault("commitments", []).append({
                    "id": _c.next_id(data),
                    "what": "%s — archived from Pickups (%s); decide: resume or close"
                            % (title, detail),
                    "due": "", "kind": "followup", "owner": "me", "ref": ref,
                    "created": datetime.now().date().isoformat(), "done": False,
                })
                promoted += 1
            if promoted:
                _c.save(data)
        except Exception as exc:
            print("  WARNING: could not promote stale pickups to the register (%s)" % exc,
                  file=sys.stderr)
            print("  ABORTING apply — refusing to drop pickups that are not tracked",
                  file=sys.stderr)
            return 1

        drop = {line for _, line in proposed}
        start, end = pickups_block(text)
        block = text[start:end]
        kept = [ln for ln in block.split("\n") if ln not in drop]
        io.open(MEMORY, "w", encoding="utf-8", newline="\n").write(
            text[:start] + "\n".join(kept) + text[end:])
        print("  APPLIED: removed %d pickup bullet(s) from MEMORY.md" % len(drop))
        print("           %d stale item(s) promoted to the commitments register"
              % promoted)
    elif proposed:
        print("\n  %d proposed for archive — propose-only; rerun with --apply" % len(proposed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
