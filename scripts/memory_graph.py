#!/usr/bin/env python3
"""
Materialise the MEMORY layer into the knowledge graph — deterministically.

WHY. `extract_entities.py::gather_files()` covers vault content only
(02-BUs, 03-Domains, 04-People, 06-Decisions, 07-References, 08-Projects,
CLAUDE.md). The memory directory is in NO include pattern, so without this the
graph is structurally blind to your memories. On the reference deployment that left
330 memory files with no relationship structure at all, which is why their only
navigational surface was a hand-maintained flat index that kept growing: it was
compensating for retrieval that did not exist.

THE POINT: the relationships are ALREADY AUTHORED. The memory convention says to
link related memories with a double-bracket wikilink, and on the reference
deployment 70% of files did (1,445 link instances). This script transcribes them.
It infers NOTHING.

  * No LLM, no API cost, no extraction error, no poisoning surface.
  * confidence=1.0, honestly: every other edge in the graph is a Haiku inference
    at 0.7-0.9; these are copied from text the author wrote. A deterministic edge
    should not be scored like a guess.
  * Additive and idempotent (upsert_entity/add_relationship both are), so the
    existing vault graph is never disturbed and re-running is safe.

RESOLUTION IS THREE-TIER, and the order matters:

  1. canonical filename  — '-' and '_' folded, case-insensitive
  2. frontmatter `name:` slug
  3. an existing vault graph node (memory -> vault bridge)

Tier 1's fold is load-bearing: on the reference deployment 58 targets looked unresolved purely
because they used the kebab-case frontmatter slug (`project-charon`) where the
file is snake_case (`project_charon`). Both conventions are legitimately in use.
Without the fold, ~13% of real edges would be silently dropped — and a silent
drop in a retrieval layer is indistinguishable from the memory not existing.

Unresolved targets are LEFT ALONE, not invented. Dangling wikilinks are an
allowed forward-ref in the memory convention, so creating a node for one would
manufacture an entity the author never wrote.

Usage:
    python scripts/memory_graph.py --dry-run     # report, change nothing
    python scripts/memory_graph.py               # apply
    python scripts/memory_graph.py --selftest    # resolver unit tests
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    sys.stdout.reconfigure(encoding="utf-8")  # Windows console is cp1252
except Exception:
    pass

from lib.graph import (  # noqa: E402
    add_relationship,
    load_nx,
    normalise_name,
    open_graph,
    upsert_entity,
)

# The memory directory sits OUTSIDE the vault, under the Claude project dir.
# Resolved like every other Charon script (HARNESS_MEMORY_ROOT override honoured).
from lib.harness_paths import memory_root  # noqa: E402

MEMORY_DIR = memory_root()

WIKILINK_RE = re.compile(r"\[\[([^\]|]+)")
NAME_FM_RE = re.compile(r"^name:\s*(.+)$", re.M)

# Node/edge vocabulary — both already in the CLOSED enums in lib/graph.py, so
# this adds no new terms and needs no C-3.1 vocabulary change.
NODE_TYPE = "document"
EDGE_TYPE = "REFERENCES"

# Index itself is not a memory; it is the pointer list ABOUT memories.
SKIP_FILES = {"MEMORY.md"}


def canon(s: str) -> str:
    """Fold the two naming conventions onto one key."""
    return s.strip().removesuffix(".md").replace("-", "_").lower()


def memory_files(mem_dir: Path) -> list[Path]:
    if not mem_dir.is_dir():
        return []
    return sorted(f for f in mem_dir.glob("*.md") if f.name not in SKIP_FILES)


def build_resolver(files: list[Path]) -> tuple[dict, dict]:
    """(by_canonical_stem, by_canonical_frontmatter_name) -> file stem."""
    by_stem, by_name = {}, {}
    for f in files:
        by_stem[canon(f.stem)] = f.stem
        try:
            m = NAME_FM_RE.search(f.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if m:
            by_name[canon(m.group(1).strip().strip("\"'"))] = f.stem
    return by_stem, by_name


def resolve(target: str, by_stem: dict, by_name: dict, graph_names: set):
    """(resolved_name, tier) or (None, 'unresolved'). Never invents a node."""
    c = canon(target)
    if c in by_stem:
        return by_stem[c], "filename"
    if c in by_name:
        return by_name[c], "frontmatter-name"
    gn = normalise_name(target)
    if gn in graph_names:
        return gn, "vault-node"
    return None, "unresolved"


def collect(mem_dir: Path, graph_names: set) -> dict:
    """Pure-ish: read files, resolve links, return a plan. Writes nothing."""
    files = memory_files(mem_dir)
    by_stem, by_name = build_resolver(files)
    nodes, edges = [], []
    tiers = {"filename": 0, "frontmatter-name": 0, "vault-node": 0, "unresolved": 0}
    unresolved_samples, isolated = [], []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        nodes.append((f.stem, f.name))
        found = 0
        for raw in WIKILINK_RE.findall(text):
            tgt, tier = resolve(raw, by_stem, by_name, graph_names)
            tiers[tier] += 1
            if tgt is None:
                if len(unresolved_samples) < 25:
                    unresolved_samples.append(raw.strip())
                continue
            if tgt == f.stem:
                continue  # self-link adds nothing
            edges.append((f.stem, tgt, f.name))
            found += 1
        if found == 0:
            isolated.append(f.stem)
    return {
        "files": len(files), "nodes": nodes, "edges": edges, "tiers": tiers,
        "unresolved_samples": unresolved_samples, "isolated": isolated,
    }


def _memory_edge_index(g) -> set:
    """Existing (src, dst, relationship) triples that came from the memory layer.

    NEEDED because `add_relationship` is NOT idempotent: the store is a
    MultiDiGraph, so `g.add_edge` appends a PARALLEL edge every call rather than
    updating. Re-running without this check silently doubles the memory layer —
    it did exactly that on the first run here (6,247 -> 7,668 -> 9,089).

    Dedupe lives in this caller, not in lib/graph.py: changing the semantics of a
    primitive the extractor also uses is a wider change than this build, and it
    should be made deliberately rather than as a side effect.
    """
    seen = set()
    for u, v, d in g.edges(data=True):
        if str(d.get("source_file", "")).startswith("memory/"):
            seen.add((u, v, d.get("relationship")))
    return seen


def apply_plan(plan: dict) -> tuple[int, int, int]:
    # open_graph returns (conn, conn) — the historical `db, conn = ...` shape.
    _, conn = open_graph(create_if_missing=True)
    existing = _memory_edge_index(conn.g)
    n = e = skipped = 0
    for stem, fname in plan["nodes"]:
        upsert_entity(conn, name=stem, display_name=stem, entity_type=NODE_TYPE)
        n += 1
    for src, dst, fname in plan["edges"]:
        key = (normalise_name(src), normalise_name(dst), EDGE_TYPE)
        if key in existing:
            skipped += 1
            continue
        add_relationship(conn, from_name=src, to_name=dst, relationship=EDGE_TYPE,
                         source_file=f"memory/{fname}", confidence=1.0)
        existing.add(key)
        e += 1
    conn.save()
    return n, e, skipped


def dedupe_memory_edges() -> tuple[int, int]:
    """Remove redundant PARALLEL memory edges, keeping one per triple.

    Lossless: the duplicates are byte-identical except for `extracted_at`.
    Scoped to memory-sourced edges only — vault edges belong to the extractor.
    """
    _, conn = open_graph(create_if_missing=False)
    g = conn.g
    groups: dict = {}
    for u, v, k, d in g.edges(keys=True, data=True):
        if str(d.get("source_file", "")).startswith("memory/"):
            groups.setdefault((u, v, d.get("relationship")), []).append((k, d.get("extracted_at", "")))
    removed = 0
    for (u, v, _rel), items in groups.items():
        if len(items) < 2:
            continue
        items.sort(key=lambda kv: kv[1])          # keep the earliest
        for k, _ts in items[1:]:
            g.remove_edge(u, v, key=k)
            removed += 1
    conn.save()
    return removed, len(groups)


def _selftest() -> int:
    by_stem = {"project_charon": "project_charon", "feedback_x": "feedback_x"}
    by_name = {"charon_release": "project_charon"}
    gnames = {"prometheus"}
    checks = [
        (resolve("project_charon", by_stem, by_name, gnames) == ("project_charon", "filename"),
         "exact filename"),
        (resolve("project-charon", by_stem, by_name, gnames) == ("project_charon", "filename"),
         "kebab-case folds to snake_case (the 13%-of-edges case)"),
        (resolve("Project_Charon", by_stem, by_name, gnames) == ("project_charon", "filename"),
         "case-insensitive"),
        (resolve("project_charon.md", by_stem, by_name, gnames) == ("project_charon", "filename"),
         ".md suffix tolerated"),
        (resolve("charon-release", by_stem, by_name, gnames) == ("project_charon", "frontmatter-name"),
         "frontmatter slug tier"),
        (resolve("prometheus", by_stem, by_name, gnames) == ("prometheus", "vault-node"),
         "vault-node bridge tier"),
        (resolve("wikilinks", by_stem, by_name, gnames) == (None, "unresolved"),
         "unresolved stays unresolved (never invented)"),
        (canon("A-B_c.md") == "a_b_c", "canon folds all three"),
    ]
    for ok, name in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    failed = [n for ok, n in checks if not ok]
    print(f"\n{len(checks)-len(failed)}/{len(checks)} passed")
    return 1 if failed else 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true", help="report only, change nothing")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--dedupe", action="store_true",
                    help="remove redundant parallel memory edges, keep one per triple")
    ap.add_argument("--memory-dir", default=str(MEMORY_DIR))
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()

    if args.dedupe:
        removed, groups = dedupe_memory_edges()
        g = load_nx()
        print(f"deduped {removed} redundant memory edge(s) across {groups} triple(s)")
        print(f"graph now: {g.number_of_nodes()} nodes / {g.number_of_edges()} edges")
        return 0

    mem = Path(args.memory_dir)
    if not mem.is_dir():
        print(f"ERROR: memory dir not found: {mem}")
        return 2

    g = load_nx()
    before_n, before_e = g.number_of_nodes(), g.number_of_edges()
    plan = collect(mem, set(g.nodes()))
    t = plan["tiers"]
    resolved = t["filename"] + t["frontmatter-name"] + t["vault-node"]
    total = resolved + t["unresolved"]

    print(f"memory dir      : {mem}")
    print(f"memory files    : {plan['files']}")
    print(f"graph before    : {before_n} nodes / {before_e} edges")
    print()
    print(f"link instances  : {total}")
    print(f"  filename tier      : {t['filename']}")
    print(f"  frontmatter-name   : {t['frontmatter-name']}")
    print(f"  vault-node bridge  : {t['vault-node']}")
    print(f"  unresolved         : {t['unresolved']}"
          f"  ({t['unresolved']*100//max(total,1)}%)")
    print(f"  => resolvable      : {resolved} ({resolved*100//max(total,1)}%)")
    print()
    print(f"planned nodes   : {len(plan['nodes'])}")
    print(f"planned edges   : {len(plan['edges'])}")
    print(f"isolated files  : {len(plan['isolated'])} "
          f"({len(plan['isolated'])*100//max(plan['files'],1)}% reachable only by search_memory)")
    if plan["unresolved_samples"]:
        print(f"unresolved e.g. : {plan['unresolved_samples'][:10]}")

    if args.dry_run:
        print("\nDRY RUN — nothing written.")
        return 0

    n, e, skipped = apply_plan(plan)
    g2 = load_nx()
    print(f"\napplied         : {n} node upserts / {e} NEW edges "
          f"/ {skipped} already present (idempotent skip)")
    print(f"graph after     : {g2.number_of_nodes()} nodes / {g2.number_of_edges()} edges "
          f"(+{g2.number_of_nodes()-before_n} / +{g2.number_of_edges()-before_e})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
