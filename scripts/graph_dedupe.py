"""graph_dedupe.py — remove redundant PARALLEL edges from the knowledge graph.

THE BUG THIS CLEANS UP. `add_relationship` is not idempotent: the store is a
networkx MultiDiGraph, so `g.add_edge` appends a *parallel* edge instead of
updating one. Every re-run of the extractor therefore re-adds every edge it
finds. On the reference deployment the graph went 6,247 -> 7,668 -> 9,089 edges
across two runs before anyone noticed.

`memory_graph.py::dedupe_memory_edges()` fixed the memory-sourced edges and
deliberately stopped there — vault edges are the extractor's data, and silently
rewriting another component's output as a side effect of an unrelated build
would have been the wrong call. That can leave duplicate vault edges standing
(824 on the reference deployment). This is the tool for those.

WHY IT IS SAFE. Parallel edges in the same (from, to, relationship) group are
byte-identical except for `extracted_at`. Keeping the earliest preserves the
first-observed timestamp and loses no relationship. The operation is therefore
LOSSLESS with respect to graph semantics — it removes repetition, not knowledge.

Duplicates are not harmless: they inflate every edge count the harness reports,
they skew neighbour ordering in retrieval, and they make "+0/+0 on re-run"
(the idempotence check the whole pipeline relies on) impossible to trust.

DRY-RUN BY DEFAULT. `--apply` is explicit — this mutates the shared graph.

Usage
  python scripts/graph_dedupe.py                 # report only
  python scripts/graph_dedupe.py --apply         # remove duplicates
  python scripts/graph_dedupe.py --apply --scope vault
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.graph import open_graph  # noqa: E402


def group_edges(g, scope="all"):
    """(from, to, relationship) -> [(key, extracted_at, source_file)]"""
    groups = {}
    for u, v, k, d in g.edges(keys=True, data=True):
        src = str(d.get("source_file", "") or "")
        is_memory = src.startswith("memory/")
        if scope == "memory" and not is_memory:
            continue
        if scope == "vault" and is_memory:
            continue
        groups.setdefault((u, v, d.get("relationship")), []).append(
            (k, d.get("extracted_at", ""), src))
    return groups


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="actually remove duplicates")
    ap.add_argument("--scope", choices=("all", "vault", "memory"), default="all")
    args = ap.parse_args(argv)

    _, conn = open_graph(create_if_missing=False)
    g = conn.g
    before = g.number_of_edges()
    groups = group_edges(g, args.scope)

    dup_groups = {k: v for k, v in groups.items() if len(v) > 1}
    redundant = sum(len(v) - 1 for v in dup_groups.values())

    by_rel = Counter()
    by_src = Counter()
    for (_u, _v, rel), items in dup_groups.items():
        by_rel[rel] += len(items) - 1
        for _k, _ts, src in items[1:]:
            top = src.split("/")[0] if "/" in src else (src or "(none)")
            by_src[top] += 1

    print("graph: %d edges · scope=%s" % (before, args.scope))
    print("duplicate groups: %d · redundant edges: %d" % (len(dup_groups), redundant))
    if by_rel:
        print("  by relationship:")
        for rel, n in by_rel.most_common(8):
            print("    %-18s %d" % (rel, n))
    if by_src:
        print("  by source zone:")
        for src, n in by_src.most_common(8):
            print("    %-22s %d" % (src, n))

    if not redundant:
        print("nothing to do")
        return 0

    if not args.apply:
        print("\nDRY RUN — nothing written. Re-run with --apply.")
        return 0

    removed = 0
    for (u, v, _rel), items in dup_groups.items():
        # Keep the EARLIEST observation so first-seen provenance survives.
        items.sort(key=lambda t: (t[1] or ""))
        for k, _ts, _src in items[1:]:
            g.remove_edge(u, v, key=k)
            removed += 1
    conn.save()
    after = g.number_of_edges()
    print("\nAPPLIED: removed %d redundant edge(s) · %d -> %d" % (removed, before, after))
    if before - after != removed:
        print("WARNING: edge-count delta (%d) != removals (%d)" % (before - after, removed),
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
