#!/usr/bin/env python3
"""
Is every memory file REACHABLE? — the orphan test that doesn't depend on MEMORY.md.

Why this exists
---------------
Today "is this memory indexed?" means "is it linked from MEMORY.md". That
definition is the reason the index grows: every new file mandates a new line, so
the one always-loaded surface expands forever until its tail is silently dropped.
It is also fragile in a way that bites — a regex that could not read `[[wikilinks]]`
reported 60 orphans when only 5 were real (`bugs_memory_index_blind_to_wikilinks`).

The question that actually matters is not "is it linked" but **"if I needed this,
would I find it?"** That is measurable, and it does not need a hand-maintained index.

So: for every memory file, use its own `description` frontmatter — the question it
exists to answer — as a query, and check whether the file comes back in the top-K of
the corpus. A file that cannot retrieve itself by its own description is genuinely
unreachable, whether or not anything links to it.

This is the measurement half of replacing MEMORY.md as the spine. Run it before and
after any change to the index, so "we removed the index and nothing got worse" is a
number rather than a hope.

Usage
-----
  python scripts/memory_reachability.py                 # summary + the unreachable
  python scripts/memory_reachability.py --k 10          # top-K cutoff (default 10)
  python scripts/memory_reachability.py --json          # machine-readable
  python scripts/memory_reachability.py --compare-index # vs the MEMORY.md definition

Exit codes: 0 always (this reports, it does not gate).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

VAULT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(VAULT / "scripts" / "lib"))
sys.path.insert(0, str(VAULT / "scripts" / "eval"))

# Resolved the same way every other Charon script finds it (HARNESS_MEMORY_ROOT
# override, else Claude Code's per-project memory dir for this vault).
sys.path.insert(0, str(VAULT / "scripts"))
from lib.harness_paths import memory_root  # noqa: E402

MEMORY_DIR = memory_root()

FM_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
STATUS_RE = re.compile(r"^\s*status:\s*(.+?)\s*$", re.MULTILINE)

# ONE definition of "reachable", shared with the Stop-hook enforcer. Same
# single-source discipline score-vault.indexed_memory_names() had — so the
# periodic report and the real-time gate can never drift on what an orphan is.
sys.path.insert(0, str(VAULT / "scripts" / "hooks"))
from memory_reachability_check import self_query  # noqa: E402


def frontmatter(text: str) -> str:
    m = FM_RE.match(text)
    return m.group(1) if m else ""


def is_deprecated(text: str) -> bool:
    m = STATUS_RE.search(frontmatter(text))
    return bool(m and "deprecated" in m.group(1).lower())


def main() -> int:
    ap = argparse.ArgumentParser(description="Reachability test for memory files")
    ap.add_argument("--k", type=int, default=10, help="top-K cutoff (default 10)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--compare-index", action="store_true",
                    help="also compute the MEMORY.md-linked definition, and diff")
    args = ap.parse_args()

    if not MEMORY_DIR.is_dir():
        print(f"memory dir not found: {MEMORY_DIR}", file=sys.stderr)
        return 0

    import fusion  # noqa: E402  (scripts/lib)

    docs = []
    meta = {}
    for p in sorted(MEMORY_DIR.glob("*.md")):
        if p.name == "MEMORY.md":
            continue  # the index is about memories, not one of them
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        docs.append((p.name, text))
        meta[p.name] = {
            "query": self_query(text, p.stem),
            "deprecated": is_deprecated(text),
        }

    bm = fusion.BM25(docs)

    unreachable, ranks, no_desc = [], {}, []
    for name, info in meta.items():
        if info["deprecated"]:
            continue
        if info["query"] is None:
            unreachable.append(name)
            no_desc.append(name)
            continue
        hits = [d for d, _ in bm.rank(info["query"])][: args.k]
        if name in hits:
            ranks[name] = hits.index(name) + 1
        else:
            unreachable.append(name)

    live = [n for n, i in meta.items() if not i["deprecated"]]
    reach = len(live) - len(unreachable)
    pct = (reach / len(live) * 100) if live else 0.0

    result = {
        "k": args.k,
        "memory_files": len(meta),
        "live": len(live),
        "reachable": reach,
        "unreachable": sorted(unreachable),
        "no_description": sorted(no_desc),
        "reachable_pct": round(pct, 1),
        "median_rank": sorted(ranks.values())[len(ranks) // 2] if ranks else None,
    }

    if args.compare_index:
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "sv", str(VAULT / "scripts" / "score-vault.py"))
            sv = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(sv)
            linked = sv.indexed_memory_names()
            unlinked = sorted(n for n in live if n not in linked)
            result["index_definition"] = {
                "linked_from_MEMORY_md": len([n for n in live if n in linked]),
                "not_linked": unlinked,
                # The interesting set: files the index calls orphans that are
                # perfectly findable — i.e. the index is measuring the wrong thing.
                "not_linked_but_reachable": sorted(
                    n for n in unlinked if n not in unreachable),
                "linked_but_unreachable": sorted(
                    n for n in unreachable if n in linked),
            }
        except Exception as exc:
            result["index_definition"] = {"error": repr(exc)}

    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0

    print(f"Memory reachability @ top-{args.k}")
    print(f"  files (non-deprecated): {result['live']}")
    print(f"  reachable by own description: {reach}/{len(live)}  ({pct:.1f}%)")
    print(f"  median self-rank: {result['median_rank']}")
    if unreachable:
        print(f"\n  UNREACHABLE ({len(unreachable)}) — these cannot retrieve themselves:")
        for n in unreachable:
            print(f"    - {n}")
            q = meta[n]["query"]
            print(f"        {'NO USABLE description: field' if q is None else 'query was: ' + q[:90]}")
    else:
        print("\n  Every live memory file retrieves itself. No real orphans.")

    idx = result.get("index_definition")
    if idx and "error" not in idx:
        print("\n  vs the MEMORY.md-linked definition:")
        print(f"    linked from MEMORY.md:        {idx['linked_from_MEMORY_md']}")
        print(f"    NOT linked but REACHABLE:     {len(idx['not_linked_but_reachable'])}"
              "   <- the index calls these orphans; retrieval finds them fine")
        print(f"    linked but UNREACHABLE:       {len(idx['linked_but_unreachable'])}"
              "   <- indexed and still unfindable; the index is not protecting these")
        for n in idx["linked_but_unreachable"]:
            print(f"      ! {n}")

    return 0


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass
    raise SystemExit(main())
