#!/usr/bin/env python3
"""Rebuild MEMORY.md as a small WORKING SET, and keep it under a hard ceiling.

Why this exists
---------------
MEMORY.md is the one memory surface loaded into every session, and Claude Code
reads only its first ~24.4 KB: anything past that is silently dropped. On the
reference deployment it reached 24,276 bytes, about 700 bytes from losing its tail.

An index that every new memory must join grows until it hits that limit. And it
is doing two jobs at once:
  * "where is X?" pointers, ~62%. Retrieval now does this on every prompt, and every
    memory file is checked at end of turn for whether it can be found by its own
    description, so these lines no longer need to be preloaded.
  * "what is urgent right now", ~38%: the Pickups section. Nothing else carries
    urgency, because urgency isn't in the words and isn't a graph edge.

So MEMORY.md keeps only the second job. This script:
  1. keeps the `## 📌 Pickups` section exactly as authored (edit it freely);
  2. regenerates a `## ⏰ Due now` block from state/commitments.json;
  3. moves every other section, pointers and all, into the catalog sub-index
     `reference_memory_catalog_index.md` (searchable, reachable, not preloaded);
  4. enforces CEILING_BYTES: if the working set would exceed it, the least urgent
     pickups (no 🔴, then no ⭐) move to the catalog. Moved, logged, never deleted;
  5. refuses to write if any link target in the old file would be lost.

The previous MEMORY.md is backed up to state/memory-index-backups/ on every write.

Usage:
    python scripts/memory_working_set.py --dry-run   # sizes and moves, writes nothing
    python scripts/memory_working_set.py             # rebuild (schedule it daily; see CONFIGURATION.md)

Exit codes: 0 ok · 1 refused (lossless check failed) · 3 still over ceiling (all 🔴)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

VAULT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(VAULT / "scripts"))
from lib.harness_paths import memory_root  # noqa: E402  (honours HARNESS_MEMORY_ROOT)

MEMDIR = memory_root()
MEMORY = MEMDIR / "MEMORY.md"
CATALOG_NAME = "reference_memory_catalog_index.md"
CATALOG = MEMDIR / CATALOG_NAME
COMMITMENTS = VAULT / "state" / "commitments.json"
BACKUPS = VAULT / "state" / "memory-index-backups"
OVERFLOW_FLAG = VAULT / "state" / "memory-index-overflow.flag"

# Claude Code drops MEMORY.md past ~24.4 KB. 16 KB leaves a third of the budget
# as headroom for lines added during the day, between daily rebuilds.
CEILING_BYTES = 16 * 1024
DUE_SOON_DAYS = 7
MAX_DUE_LINES = 12

PICKUPS = re.compile(r"^##\s*📌")
GENERATED = ("## ⏰ Due now", "## Everything else")
LINK_TARGET = re.compile(r"\]\(([^)\s]+)\)|\[\[([^\]|#]+)")

CATALOG_HEAD = """---
name: reference-memory-catalog-index
description: "Where is the full list of memories by topic? The catalog of every memory pointer that used to sit in MEMORY.md, grouped under the same section headings, plus any pointer added since."
metadata:
  type: reference
---

# Memory catalog

Every memory pointer by topic. Moved out of MEMORY.md by the working-set build so the one
always-loaded file holds only what's urgent. Nothing here is preloaded: relevant
memories reach a session through retrieval, and every memory file is checked at
end of turn for whether it can be found by its own description.

Maintained by `scripts/memory_working_set.py`, which moves new non-pickup lines
here from MEMORY.md each time it runs. Add pointers here directly if you want; it's
optional, because a memory doesn't need a line anywhere to be found.
"""


def split_sections(text: str) -> tuple[str, list[tuple[str, list[str]]]]:
    """(preamble, [(heading_line, body_lines)]) split on level-2 headings."""
    pre, sections, cur = [], [], None
    for line in text.splitlines():
        if line.startswith("## "):
            cur = (line, [])
            sections.append(cur)
        elif cur is None:
            pre.append(line)
        else:
            cur[1].append(line)
    return "\n".join(pre), sections


def link_targets(text: str) -> set[str]:
    out = set()
    for a, b in LINK_TARGET.findall(text):
        t = (a or b).strip()
        if t:
            out.add(t)
    return out


def due_now_block(today: date) -> list[str]:
    if not COMMITMENTS.exists():
        return ["- No commitments register yet. Start one: `python scripts/commitments.py --add`"]
    try:
        data = json.loads(COMMITMENTS.read_text(encoding="utf-8"))
    except Exception:
        return ["- ⚠️ commitments register unreadable: run `python scripts/commitments.py`"]
    rows = []
    for c in data.get("commitments", []):
        if c.get("done") or not c.get("due"):
            continue
        try:
            due = date.fromisoformat(c["due"])
        except ValueError:
            continue
        if due <= today + timedelta(days=DUE_SOON_DAYS):
            rows.append((due, c))
    rows.sort(key=lambda t: t[0])  # date only: two items due the same day must not compare dicts
    if not rows:
        return ["- Nothing due in the next %d days." % DUE_SOON_DAYS]
    out = []
    for due, c in rows[:MAX_DUE_LINES]:
        d = (today - due).days
        when = ("🔴 %dd overdue" % d) if d > 0 else ("🟡 due today" if d == 0 else "🟡 due %s" % due)
        # 80 chars keeps the whole bullet inside deny-destructive's 120-byte
        # per-bullet prose budget -- the generator obeys the same rule as a human.
        what = re.sub(r"\s+", " ", c.get("what", ""))
        what = what if len(what) <= 80 else what[:79].rstrip() + "…"
        out.append("- %s · %s — %s" % (when, c.get("id", "?"), what))
    if len(rows) > MAX_DUE_LINES:
        out.append("- +%d more: `python scripts/commitments.py`" % (len(rows) - MAX_DUE_LINES))
    return out


def pickup_items(body: list[str]) -> list[list[str]]:
    """Group a pickups body into items: a '- ' bullet plus its indented continuation."""
    items, cur = [], None
    for line in body:
        if line.startswith("- "):
            cur = [line]
            items.append(cur)
        elif cur is not None and (line.startswith("  ") or not line.strip()):
            cur.append(line)
        else:
            cur = [line]
            items.append(cur)
    return items


def build(today: date) -> dict:
    old = MEMORY.read_text(encoding="utf-8")
    pre, sections = split_sections(old)
    catalog = CATALOG.read_text(encoding="utf-8") if CATALOG.exists() else CATALOG_HEAD
    cat_pre, cat_sections = split_sections(catalog)
    cat_map = {h: body for h, body in cat_sections}
    cat_order = [h for h, _ in cat_sections]

    def to_catalog(heading: str, lines: list[str]) -> int:
        if heading not in cat_map:
            cat_map[heading] = []
            cat_order.append(heading)
        have = set(cat_map[heading])
        added = 0
        for ln in lines:
            if ln.strip() and ln not in have:
                cat_map[heading].append(ln)
                have.add(ln)
                added += 1
        return added

    moved = {}
    pickups_heading, pickups_body = None, []
    # Preamble lines that aren't the generated header move once, so nothing is lost.
    pre_keep = [ln for ln in pre.splitlines()
                if ln.strip() and not ln.startswith("# ") and "memory_working_set.py" not in ln
                and "How memory works" not in ln]
    if pre_keep:
        moved["(former header)"] = to_catalog("## Former MEMORY.md header", pre_keep)
    for heading, body in sections:
        if PICKUPS.match(heading):
            pickups_heading, pickups_body = heading, body
        elif heading.startswith(GENERATED):
            # Regenerated below -- but anything ADDED into these blocks is kept. Claude
            # Code's own auto-memory appends pointer lines at the end of MEMORY.md, which
            # is inside "Everything else": dropping them would trip the lossless guard and
            # wedge every rebuild. A linked line we didn't generate moves to the catalog.
            extra = [ln for ln in body if "](" in ln and CATALOG_NAME not in ln]
            if extra:
                moved["(added into a generated block)"] = to_catalog(
                    "## Added after the working set was built", extra)
        else:
            n = to_catalog(heading, body)
            if n:
                moved[heading] = n

    if pickups_heading is None:
        pickups_heading, pickups_body = "## 📌 Pickups (read first)", ["- (none)"]

    catalog_lines = sum(1 for b in cat_map.values() for ln in b if ln.lstrip().startswith("- "))

    def render(p_body: list[str]) -> str:
        head = [
            "# Memory index — working set",
            "",
            "<!-- Rebuilt daily by scripts/memory_working_set.py. Edit the 📌 Pickups section "
            "freely; the rest is regenerated. -->",
            "How memory works: relevant memories are injected into each prompt automatically; "
            "use `search_memory` or `/recall` to look further. Every memory file is checked at "
            "end of turn for whether it can be found by its own description, so a new memory "
            "needs no line here. Prior sessions: `sessions/*.md`.",
            "",
        ]
        body = [pickups_heading, *p_body]
        while body and not body[-1].strip():
            body.pop()
        due = ["", "## ⏰ Due now", "<!-- from state/commitments.json -->", *due_now_block(today)]
        rest = ["", "## Everything else",
                "- [Memory catalog](%s) — every memory pointer by topic (%d lines), "
                "including the domain sub-indexes" % (CATALOG_NAME, catalog_lines)]
        return "\n".join(head + body + due + rest) + "\n"

    items = pickup_items(pickups_body)
    overflow = []
    new = render([ln for it in items for ln in it])
    for tier in ("🔴", "⭐"):  # first move items lacking 🔴, then those lacking ⭐
        i = len(items) - 1
        while len(new.encode("utf-8")) > CEILING_BYTES and i >= 0:
            it = items[i]
            if it[0].startswith("- ") and tier not in it[0]:
                overflow.append(items.pop(i))
                new = render([ln for x in items for ln in x])
            i -= 1
    if overflow:
        moved["## Overflow from pickups"] = to_catalog(
            "## Overflow from pickups (moved %s to stay under the ceiling)" % today,
            [ln for it in reversed(overflow) for ln in it])

    cat_text = cat_pre.rstrip("\n") + "\n\n" + "\n\n".join(
        h + "\n" + "\n".join(cat_map[h]).strip("\n") for h in cat_order) + "\n"

    lost = link_targets(old) - link_targets(new) - link_targets(cat_text)
    return {"old": old, "new": new, "catalog": cat_text, "moved": moved, "overflow": len(overflow),
            "lost": sorted(lost), "old_bytes": len(old.encode("utf-8")),
            "new_bytes": len(new.encode("utf-8")), "catalog_bytes": len(cat_text.encode("utf-8"))}


def main() -> int:
    ap = argparse.ArgumentParser(description="Rebuild MEMORY.md as a small working set.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    r = build(date.today())
    print("MEMORY.md  %6d -> %6d bytes   (ceiling %d, Claude Code reads ~24,985)"
          % (r["old_bytes"], r["new_bytes"], CEILING_BYTES))
    print("catalog    %6d bytes  %s" % (r["catalog_bytes"], CATALOG_NAME))
    for h, n in r["moved"].items():
        print("  moved %3d line(s) to catalog: %s" % (n, h))
    if r["overflow"]:
        print("  OVERFLOW: %d pickup item(s) moved to stay under the ceiling" % r["overflow"])
    if r["lost"]:
        print("REFUSED: %d link target(s) would be lost: %s" % (len(r["lost"]), r["lost"][:10]))
        return 1
    over = r["new_bytes"] > CEILING_BYTES
    if args.dry_run:
        print("--dry-run: nothing written")
        return 3 if over else 0

    current_catalog = CATALOG.read_text(encoding="utf-8") if CATALOG.exists() else ""
    if r["new"] == r["old"] and r["catalog"] == current_catalog:
        print("unchanged; nothing written")
        return 3 if over else 0

    BACKUPS.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (BACKUPS / ("MEMORY-%s.md" % stamp)).write_bytes(r["old"].encode("utf-8"))
    for path, text in ((CATALOG, r["catalog"]), (MEMORY, r["new"])):
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_bytes(text.encode("utf-8"))
        os.replace(tmp, path)
    if over or r["overflow"]:
        OVERFLOW_FLAG.write_text(
            "%s MEMORY.md %d bytes, %d pickup(s) moved to the catalog%s\n"
            % (stamp, r["new_bytes"], r["overflow"],
               "; STILL OVER the ceiling: every remaining pickup is 🔴" if over else ""),
            encoding="utf-8")
    elif OVERFLOW_FLAG.exists():
        OVERFLOW_FLAG.unlink()
    print("written; backup state/memory-index-backups/MEMORY-%s.md" % stamp)
    return 3 if over else 0


if __name__ == "__main__":
    raise SystemExit(main())
