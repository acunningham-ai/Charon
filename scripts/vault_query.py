"""vault_query.py — natural-language graph queries over the Charon vault graph.

Three operations, all over the kuzu vault graph (loaded into networkx
for traversal):

- ``neighbours``  — BFS/DFS around a starting entity to a given depth
- ``path``        — shortest path between two entities
- ``explain``     — entity + its 1-hop neighbourhood with relationship labels
- ``search``      — fuzzy-find an entity by name

The slash command ``/vault-query`` invokes this helper through the
``vault-query`` skill. Claude parses the user's natural-language question
into one of the four subcommands + the entity name(s), runs the helper,
and folds the results into a human-readable answer.

Why "borrow from graphify": graphify ships natural-language BFS/DFS over
its graph and it materially changes how you interact with a knowledge
base — instead of constructing queries, you ask questions. Charon's
existing MCP server exposes raw entity lookups; this layer adds the
traversal primitive on top.

Optional deps (same as community detection): kuzu + networkx via
``requirements-graph.txt``. Graceful degradation when missing.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.communities import (  # noqa: E402
    networkx_is_available,
)
from lib.graph import graph_path, is_available as kuzu_is_available, normalise_name  # noqa: E402


# ---------- Data shapes ----------

@dataclass(frozen=True)
class EntityHit:
    name: str               # normalised key
    display_name: str
    entity_type: str
    distance: int           # 0 = self, 1 = direct neighbour, etc.
    path: tuple             # tuple of (name, name, name, ...) describing the path used

    def to_dict(self) -> dict:
        return asdict(self)


# ---------- Availability ----------

def query_available() -> Tuple[bool, str]:
    ok, reason = kuzu_is_available()
    if not ok:
        return False, reason
    ok, reason = networkx_is_available()
    if not ok:
        return False, reason
    if not graph_path().exists():
        return False, f"vault graph not found at {graph_path()} — run `python scripts/extract_entities.py` first"
    return True, ""


# ---------- Kuzu → networkx (directed, for path semantics) ----------

def load_graph():
    """Load the vault graph as a directed networkx graph (preserves edge direction)."""
    ok, reason = query_available()
    if not ok:
        raise RuntimeError(f"vault-query unavailable: {reason}")

    import kuzu
    import networkx as nx

    g = nx.DiGraph()
    db = kuzu.Database(str(graph_path()))
    conn = kuzu.Connection(db)

    res = conn.execute("MATCH (e:Entity) RETURN e.name, e.entity_type, e.display_name")
    while res.has_next():
        row = res.get_next()
        g.add_node(row[0], entity_type=row[1], display_name=row[2] or row[0])

    res = conn.execute(
        "MATCH (a:Entity)-[r:Mentions]->(b:Entity) "
        "RETURN a.name, b.name, r.relationship, r.confidence, r.source_file"
    )
    while res.has_next():
        row = res.get_next()
        g.add_edge(
            row[0], row[1],
            relationship=row[2],
            confidence=float(row[3] or 1.0),
            source_file=row[4] or "",
        )
    return g


# ---------- Fuzzy entity lookup ----------

def search_entities(g, query: str, limit: int = 10) -> List[dict]:
    """Find entities whose name or display-name contains the query (case-insensitive).

    Returns up to ``limit`` matches, ranked by:
    1. exact match
    2. prefix match
    3. substring match
    """
    q_lower = query.lower().strip()
    q_normalised = normalise_name(query)

    exact: List[dict] = []
    prefix: List[dict] = []
    substring: List[dict] = []

    for node, data in g.nodes(data=True):
        name = node
        display = data.get("display_name", node).lower()
        name_lower = name.lower()
        entry = {
            "name": name,
            "display_name": data.get("display_name", node),
            "entity_type": data.get("entity_type", "unknown"),
        }
        if name == q_normalised or display == q_lower:
            exact.append(entry)
        elif name_lower.startswith(q_lower) or display.startswith(q_lower):
            prefix.append(entry)
        elif q_lower in name_lower or q_lower in display:
            substring.append(entry)

    combined = exact + prefix + substring
    return combined[:limit]


# ---------- Traversal ----------

def neighbours(g, start: str, depth: int = 2, traversal: str = "bfs", limit: int = 50) -> List[EntityHit]:
    """Return entities within ``depth`` hops of ``start``.

    ``traversal`` is ``"bfs"`` (breadth-first — broad context) or
    ``"dfs"`` (depth-first — narrow chains). ``limit`` caps the result.
    """
    import networkx as nx

    if start not in g:
        return []

    # Treat graph as undirected for "what's near X" intent
    undirected = g.to_undirected()
    hits: List[EntityHit] = []

    if traversal == "bfs":
        layers = nx.bfs_layers(undirected, [start])
    elif traversal == "dfs":
        # DFS preorder gives a depth-first walk; cap by depth manually
        layers = _dfs_layers(undirected, start, max_depth=depth)
    else:
        raise ValueError(f"unknown traversal: {traversal!r}")

    seen = {start}
    for d, layer in enumerate(layers):
        if d > depth:
            break
        for node in layer:
            if node in seen and node != start:
                continue
            seen.add(node)
            data = g.nodes[node]
            try:
                path = tuple(nx.shortest_path(undirected, source=start, target=node))
            except nx.NetworkXNoPath:
                path = (start, node)
            hits.append(EntityHit(
                name=node,
                display_name=data.get("display_name", node),
                entity_type=data.get("entity_type", "unknown"),
                distance=d,
                path=path,
            ))
            if len(hits) >= limit:
                return hits
    return hits


def _dfs_layers(g, start, max_depth):
    """Depth-first walk yielding (depth, [nodes_at_depth, ...]) in DFS order."""
    layers: List[List] = [[start]]
    visited = {start}
    stack = [(start, 0)]
    while stack:
        node, d = stack.pop()
        if d >= max_depth:
            continue
        for nbr in g.neighbors(node):
            if nbr in visited:
                continue
            visited.add(nbr)
            while len(layers) <= d + 1:
                layers.append([])
            layers[d + 1].append(nbr)
            stack.append((nbr, d + 1))
    return layers


def shortest_path_between(g, source: str, target: str) -> Optional[List[dict]]:
    """Shortest path from source to target. Returns [node_info, ...] or None."""
    import networkx as nx

    if source not in g or target not in g:
        return None
    undirected = g.to_undirected()
    try:
        path = nx.shortest_path(undirected, source=source, target=target)
    except nx.NetworkXNoPath:
        return None
    result: List[dict] = []
    for i, node in enumerate(path):
        data = g.nodes[node]
        entry = {
            "name": node,
            "display_name": data.get("display_name", node),
            "entity_type": data.get("entity_type", "unknown"),
        }
        # Annotate the edge to the next node, if present
        if i + 1 < len(path):
            nxt = path[i + 1]
            edge_data = g.get_edge_data(node, nxt) or g.get_edge_data(nxt, node) or {}
            entry["edge_to_next"] = {
                "relationship": edge_data.get("relationship", "RELATED_TO"),
                "source_file": edge_data.get("source_file", ""),
            }
        result.append(entry)
    return result


def explain_node(g, name: str) -> Optional[dict]:
    """Return node info + its 1-hop neighbours with relationship labels."""
    if name not in g:
        return None
    data = g.nodes[name]
    incoming = [
        {
            "neighbour": src,
            "display_name": g.nodes[src].get("display_name", src),
            "entity_type": g.nodes[src].get("entity_type", "unknown"),
            "relationship": g.edges[src, name].get("relationship", "RELATED_TO"),
            "source_file": g.edges[src, name].get("source_file", ""),
            "direction": "incoming",
        }
        for src in g.predecessors(name)
    ]
    outgoing = [
        {
            "neighbour": dst,
            "display_name": g.nodes[dst].get("display_name", dst),
            "entity_type": g.nodes[dst].get("entity_type", "unknown"),
            "relationship": g.edges[name, dst].get("relationship", "RELATED_TO"),
            "source_file": g.edges[name, dst].get("source_file", ""),
            "direction": "outgoing",
        }
        for dst in g.successors(name)
    ]
    return {
        "name": name,
        "display_name": data.get("display_name", name),
        "entity_type": data.get("entity_type", "unknown"),
        "neighbours": sorted(incoming + outgoing, key=lambda x: x["neighbour"]),
    }


# ---------- CLI ----------

def _configure_stdio_for_unicode() -> None:
    if sys.platform.startswith("win"):
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass


def _print_hits(hits: List[EntityHit], traversal: str) -> None:
    print(f"  {len(hits)} entit{'y' if len(hits) == 1 else 'ies'} via {traversal.upper()}")
    print()
    by_distance: dict = {}
    for h in hits:
        by_distance.setdefault(h.distance, []).append(h)
    for d in sorted(by_distance):
        layer = by_distance[d]
        print(f"  depth {d} ({len(layer)}):")
        for h in layer[:10]:
            print(f"    • {h.display_name}  [{h.entity_type}]")
        if len(layer) > 10:
            print(f"    ... +{len(layer) - 10} more")


def _print_path(path: Optional[List[dict]], src: str, dst: str) -> None:
    if path is None:
        print(f"  no path from {src!r} to {dst!r}")
        return
    print(f"  path ({len(path)} nodes):")
    for i, node in enumerate(path):
        print(f"    {i}. {node['display_name']}  [{node['entity_type']}]")
        if "edge_to_next" in node:
            print(f"       └─ {node['edge_to_next']['relationship']}")


def _print_explain(node: Optional[dict], name: str) -> None:
    if node is None:
        print(f"  no entity named {name!r}")
        return
    print(f"  {node['display_name']}  [{node['entity_type']}]")
    print(f"  {len(node['neighbours'])} neighbour(s):")
    for n in node["neighbours"]:
        arrow = "→" if n["direction"] == "outgoing" else "←"
        print(f"    {arrow} {n['display_name']}  [{n['entity_type']}]  ({n['relationship']})")


def main() -> int:
    _configure_stdio_for_unicode()
    parser = argparse.ArgumentParser(description="Natural-language graph queries over the Charon vault graph")
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of text")
    sub = parser.add_subparsers(dest="command", required=True)

    p_search = sub.add_parser("search", help="Fuzzy-find entities by name")
    p_search.add_argument("query")
    p_search.add_argument("--limit", type=int, default=10)

    p_explain = sub.add_parser("explain", help="Show an entity + its 1-hop neighbours")
    p_explain.add_argument("name")

    p_n = sub.add_parser("neighbours", help="BFS/DFS around a starting entity")
    p_n.add_argument("name")
    p_n.add_argument("--depth", type=int, default=2)
    p_n.add_argument("--dfs", action="store_true", help="Use depth-first traversal (default: BFS)")
    p_n.add_argument("--limit", type=int, default=50)

    p_path = sub.add_parser("path", help="Shortest path between two entities")
    p_path.add_argument("source")
    p_path.add_argument("target")

    args = parser.parse_args()

    ok, reason = query_available()
    if not ok:
        sys.stderr.write(f"vault-query unavailable: {reason}\n")
        return 1

    g = load_graph()

    if args.command == "search":
        results = search_entities(g, args.query, limit=args.limit)
        if args.json:
            print(json.dumps(results, indent=2, ensure_ascii=False))
        else:
            print(f"  {len(results)} match(es) for {args.query!r}")
            for r in results:
                print(f"    • {r['display_name']}  [{r['entity_type']}]  (key: {r['name']})")
        return 0 if results else 1

    if args.command == "explain":
        key = normalise_name(args.name)
        node = explain_node(g, key)
        if args.json:
            print(json.dumps(node, indent=2, ensure_ascii=False))
        else:
            _print_explain(node, args.name)
        return 0 if node else 1

    if args.command == "neighbours":
        key = normalise_name(args.name)
        traversal = "dfs" if args.dfs else "bfs"
        hits = neighbours(g, key, depth=args.depth, traversal=traversal, limit=args.limit)
        if args.json:
            print(json.dumps([h.to_dict() for h in hits], indent=2, ensure_ascii=False))
        else:
            _print_hits(hits, traversal)
        return 0 if hits else 1

    if args.command == "path":
        src = normalise_name(args.source)
        dst = normalise_name(args.target)
        path = shortest_path_between(g, src, dst)
        if args.json:
            print(json.dumps(path, indent=2, ensure_ascii=False))
        else:
            _print_path(path, args.source, args.target)
        return 0 if path else 1

    return 2


if __name__ == "__main__":
    sys.exit(main())
