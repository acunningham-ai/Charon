"""communities.py — vault-graph community detection.

Reads the kuzu vault graph, builds an in-memory networkx undirected graph,
runs Louvain community detection, and writes the resulting node→community
labels to ``<vault>/.charon/graph-communities.json``.

Why this exists (v0.8.0):
- Adam's vault accumulates entities (people, projects, captures, decisions)
  faster than any individual can curate themes from manually.
- Louvain clustering surfaces **natural communities** in the graph — groups
  of nodes more densely connected to each other than to the rest of the
  graph. These often correspond to BU-level / project-level / domain-level
  themes that no manual tag captures.
- Community labels feed the interactive HTML viewer (colour by community)
  and the community-based wiki generator (one summary doc per cluster).

Optional dep stack:
- ``kuzu`` (requirements-graph.txt) — vault graph storage
- ``networkx`` (requirements-graph.txt) — Louvain algorithm + graph ops

Graceful degradation when either is missing: returns a clear error tuple
``(ok=False, reason=...)`` instead of raising. Callers surface the reason
to the user.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from .graph import graph_path, is_available as kuzu_is_available
from .harness_paths import vault_root


COMMUNITIES_REL_PATH = ".charon/graph-communities.json"


def communities_path() -> Path:
    return vault_root() / COMMUNITIES_REL_PATH


# ---------- Optional-dep gates ----------

def networkx_is_available() -> Tuple[bool, str]:
    """Return (True, '') if networkx is importable, else (False, reason)."""
    try:
        import networkx  # noqa: F401
        return True, ""
    except ImportError:
        return False, "networkx not installed — `pip install -r requirements-graph.txt`"


def communities_available() -> Tuple[bool, str]:
    """Full availability check: kuzu + networkx + a graph file on disk."""
    ok, reason = kuzu_is_available()
    if not ok:
        return False, reason
    ok, reason = networkx_is_available()
    if not ok:
        return False, reason
    if not graph_path().exists():
        return False, f"vault graph not found at {graph_path()} — run `python scripts/extract_entities.py` first"
    return True, ""


# ---------- Graph extraction (kuzu → networkx) ----------

def load_graph_to_networkx():
    """Read the kuzu vault graph into an undirected ``networkx.Graph``.

    Returns the graph. Raises RuntimeError if the optional deps are missing
    or the graph file isn't on disk — callers should check
    ``communities_available()`` first to fail cleanly.
    """
    ok, reason = communities_available()
    if not ok:
        raise RuntimeError(f"communities unavailable: {reason}")

    import kuzu
    import networkx as nx

    g = nx.Graph()
    db = kuzu.Database(str(graph_path()))
    conn = kuzu.Connection(db)

    # Pull every entity → node
    entity_result = conn.execute("MATCH (e:Entity) RETURN e.name, e.entity_type, e.display_name")
    while entity_result.has_next():
        row = entity_result.get_next()
        name, etype, display = row[0], row[1], row[2]
        g.add_node(name, entity_type=etype, display_name=display)

    # Pull every relationship → edge (undirected for clustering)
    rel_result = conn.execute(
        "MATCH (a:Entity)-[r:Mentions]->(b:Entity) "
        "RETURN a.name, b.name, r.relationship, r.confidence"
    )
    while rel_result.has_next():
        row = rel_result.get_next()
        a, b, rel, conf = row[0], row[1], row[2], row[3]
        # Aggregate parallel edges: bump weight rather than overwrite
        if g.has_edge(a, b):
            g[a][b]["weight"] += float(conf or 1.0)
        else:
            g.add_edge(a, b, weight=float(conf or 1.0), relationship=rel)

    return g


# ---------- Community detection ----------

def detect_communities(
    seed: int = 42,
    resolution: float = 1.0,
) -> Dict[str, int]:
    """Run Louvain community detection over the vault graph.

    Returns ``{node_name: community_id}``. Community IDs are integers
    starting from 0, assigned in order of detection.

    ``seed`` makes the run reproducible (Louvain depends on iteration
    order). ``resolution`` tunes community size: <1 favours larger
    communities, >1 favours smaller ones. Default 1.0 is balanced.
    """
    import networkx as nx
    from networkx.algorithms.community import louvain_communities

    g = load_graph_to_networkx()
    if g.number_of_nodes() == 0:
        return {}

    communities_list = louvain_communities(g, seed=seed, resolution=resolution)
    out: Dict[str, int] = {}
    for cid, community in enumerate(sorted(communities_list, key=len, reverse=True)):
        for node in community:
            out[node] = cid
    return out


def detect_communities_in_graph(g, seed: int = 42, resolution: float = 1.0) -> Dict[str, int]:
    """Variant that takes a prebuilt networkx graph (used by tests with synthetic data)."""
    from networkx.algorithms.community import louvain_communities

    if g.number_of_nodes() == 0:
        return {}
    communities_list = louvain_communities(g, seed=seed, resolution=resolution)
    out: Dict[str, int] = {}
    for cid, community in enumerate(sorted(communities_list, key=len, reverse=True)):
        for node in community:
            out[node] = cid
    return out


# ---------- Persistence ----------

def write_communities(communities: Dict[str, int], path: Optional[Path] = None) -> Path:
    """Write the community map to JSON. Returns the path written."""
    if path is None:
        path = communities_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    # Group by community for human readability
    by_community: Dict[int, List[str]] = {}
    for node, cid in communities.items():
        by_community.setdefault(cid, []).append(node)
    for cid in by_community:
        by_community[cid].sort()

    payload = {
        "generated_at": int(time.time()),
        "algorithm": "louvain",
        "node_count": len(communities),
        "community_count": len(by_community),
        "communities": {
            str(cid): {"size": len(nodes), "nodes": nodes}
            for cid, nodes in sorted(by_community.items())
        },
        # Also keep the flat node→community map for downstream consumers
        "node_to_community": communities,
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def read_communities(path: Optional[Path] = None) -> Optional[dict]:
    """Read the persisted communities file. Returns None if not present."""
    if path is None:
        path = communities_path()
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


# ---------- Stats helper ----------

def community_summary(communities: Dict[str, int]) -> Dict:
    """Lightweight stats. Returns counts + a histogram-ish breakdown."""
    if not communities:
        return {"node_count": 0, "community_count": 0, "sizes": []}
    by_community: Dict[int, int] = {}
    for cid in communities.values():
        by_community[cid] = by_community.get(cid, 0) + 1
    sizes = sorted(by_community.values(), reverse=True)
    return {
        "node_count": len(communities),
        "community_count": len(by_community),
        "sizes": sizes,
        "largest_size": sizes[0],
        "smallest_size": sizes[-1],
        "median_size": sizes[len(sizes) // 2],
    }
