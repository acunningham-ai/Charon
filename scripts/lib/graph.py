"""graph.py — local knowledge-graph core (networkx-backed).

Shared library for:
- `scripts/extract_entities.py` (CLI extractor — writes)
- `scripts/mcp/vault-graph-server.py` (MCP server — reads)
- `scripts/vault_query.py` + `scripts/lib/communities.py` (load for traversal / clustering)
- `scripts/vault_graph_html.py` (interactive HTML viewer)
- `scripts/graph_link_backfill.py` (write graph edges back into notes)

Local-first design:
- Backend: **networkx** (pure-Python) persisted as JSON. No native deps, no DB
  server, no compiled wheel to source per platform/Python version. networkx
  already powered the traversal + clustering layers, so making it the store too
  removes the previous embedded-DB native dependency.
- Extraction: Anthropic SDK (Haiku) called by the extractor only — at index
  time, NOT query time. The query path is fully local.

Persisted JSON shape (`knowledge-graph.json`):
  {
    "nodes": [{"name","display_name","entity_type","created_at","last_seen_at"}, ...],
    "edges": [{"from","to","relationship","source_file","extracted_at","confidence"}, ...]
  }

Index file: <HARNESS_VAULT_ROOT>/.charon/knowledge-graph.json
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .harness_paths import vault_root


GRAPH_REL_PATH = ".charon/knowledge-graph.json"

ENTITY_TYPES = frozenset({
    "person", "project", "org_unit", "tool", "concept", "event", "document"
})

# Relationship vocabulary — closed set per C-3.1 (value-layer constraint).
RELATIONSHIP_TYPES = frozenset({
    "WORKS_ON",       # person → project
    "OWNS",           # person/org_unit → project/tool
    "AFFECTS",        # event/decision → project/org_unit
    "REFERENCES",     # document → entity
    "DEPENDS_ON",     # project → tool/project
    "REPORTS_TO",     # person → person
    "PART_OF",        # org_unit → org_unit
    "INVOLVES",       # event → person
    "RECOMMENDED_BY", # tool → person
    "MENTIONS",       # document → entity (generic catch-all)
})


def is_available() -> tuple[bool, str]:
    """Returns (available, reason). Graph needs networkx (pure-Python)."""
    try:
        import networkx  # noqa: F401
    except ImportError:
        return False, "networkx not installed — pip install -r requirements-graph.txt"
    return True, ""


def graph_path() -> Path:
    return vault_root() / GRAPH_REL_PATH


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def normalise_name(name: str) -> str:
    """kebab-case lowercase, used as the entity primary key."""
    import re
    s = re.sub(r"\s+", "-", name.strip().lower())
    return re.sub(r"[^\w\-]", "", s)


# ---------- Persistence ----------

class _GraphConn:
    """In-memory networkx graph + JSON persistence. Returned by open_graph().

    Mutations (upsert_entity / add_relationship) update the in-memory graph;
    call .save() to persist (the extractor saves once after its batch).
    """

    def __init__(self, g, path: Path):
        self.g = g
        self.path = path

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        nodes = [{"name": n, **dict(self.g.nodes[n])} for n in self.g.nodes]
        edges = [
            {"from": u, "to": v, **dict(d)}
            for u, v, d in self.g.edges(data=True)
        ]
        payload = {"nodes": nodes, "edges": edges}
        tmp = self.path.with_name(self.path.name + ".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path)  # atomic swap


def load_nx():
    """Load the persisted graph as a networkx MultiDiGraph (empty if none).

    Used by the query (vault_query), clustering (communities), viewer
    (vault_graph_html) and backfill (graph_link_backfill) layers so they don't
    each re-implement loading.
    """
    import networkx as nx

    g = nx.MultiDiGraph()
    p = graph_path()
    if not p.exists():
        return g
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return g
    for nd in data.get("nodes", []):
        name = nd.get("name")
        if not name:
            continue
        g.add_node(
            name,
            display_name=nd.get("display_name", name),
            entity_type=nd.get("entity_type", "concept"),
            created_at=nd.get("created_at", ""),
            last_seen_at=nd.get("last_seen_at", ""),
        )
    for ed in data.get("edges", []):
        u, v = ed.get("from"), ed.get("to")
        if not u or not v:
            continue
        g.add_edge(
            u, v,
            relationship=ed.get("relationship", "MENTIONS"),
            source_file=ed.get("source_file", ""),
            extracted_at=ed.get("extracted_at", ""),
            confidence=float(ed.get("confidence", 1.0) or 1.0),
        )
    return g


def open_graph(create_if_missing: bool = True):
    """Open the graph. Returns (conn, conn) — both are the same _GraphConn
    wrapper (keeps the historical `db, conn = open_graph()` unpacking working).

    This is the WRITABLE path — used by the extractor. Query consumers (the MCP
    server) should use open_graph_readonly() so mutation is impossible by
    construction, not merely unused."""
    path = graph_path()
    if not path.exists() and not create_if_missing:
        raise FileNotFoundError(
            f"Knowledge graph not found at {path}. "
            f"Run scripts/extract_entities.py first."
        )
    conn = _GraphConn(load_nx(), path)
    return conn, conn


class _ReadOnlyGraphConn:
    """Fail-closed read-only view of the graph for query consumers.

    Read-only BY CONSTRUCTION, two layers deep:
    - the wrapped networkx graph is `nx.freeze`-d → any add/remove node/edge raises
      `networkx.NetworkXError` (blocks in-memory mutation, e.g. a stray
      add_relationship(conn, ...) call or an injected query path);
    - `.save()` raises `PermissionError` (blocks persistence even if the in-memory
      graph were somehow altered).

    Reads (`get_entity`, `stats`) work unchanged — they only inspect `.g`.
    The on-disk graph can therefore only ever be written by the extractor's
    writable open_graph() path, never via a query/MCP surface.
    """

    read_only = True

    def __init__(self, g):
        self.g = g

    def save(self) -> None:  # noqa: D401 — fail-closed
        raise PermissionError(
            "vault-graph connection is read-only — persistence is not permitted "
            "on this path. Writes go through scripts/extract_entities.py only."
        )


def open_graph_readonly() -> "_ReadOnlyGraphConn":
    """Open the graph for READ-ONLY access (frozen graph; .save() raises).

    Raises FileNotFoundError if the graph file doesn't exist yet — callers surface
    the build hint. Use this from any query surface (MCP, future query tools); the
    writable open_graph() is for the extractor only."""
    import networkx as nx

    path = graph_path()
    if not path.exists():
        raise FileNotFoundError(
            f"Knowledge graph not found at {path}. "
            f"Run scripts/extract_entities.py first."
        )
    return _ReadOnlyGraphConn(nx.freeze(load_nx()))


# ---------- Upserts ----------

def upsert_entity(conn, name: str, display_name: str, entity_type: str) -> None:
    """Idempotent entity insert/update. Refuses unknown entity_type."""
    if getattr(conn, "read_only", False):
        raise PermissionError("cannot mutate the graph through a read-only connection")
    if entity_type not in ENTITY_TYPES:
        raise ValueError(f"unknown entity_type: {entity_type}. Allowed: {sorted(ENTITY_TYPES)}")
    norm = normalise_name(name)
    if not norm:
        return
    g = conn.g
    if g.has_node(norm):
        g.nodes[norm]["last_seen_at"] = _now()
        if not g.nodes[norm].get("display_name"):
            g.nodes[norm]["display_name"] = display_name
    else:
        g.add_node(
            norm,
            display_name=display_name,
            entity_type=entity_type,
            created_at=_now(),
            last_seen_at=_now(),
        )


def add_relationship(conn, from_name: str, to_name: str, relationship: str,
                     source_file: str, confidence: float = 0.9) -> None:
    """Add a relationship between two entities. Refuses unknown relationship type."""
    if getattr(conn, "read_only", False):
        raise PermissionError("cannot mutate the graph through a read-only connection")
    if relationship not in RELATIONSHIP_TYPES:
        raise ValueError(
            f"unknown relationship: {relationship}. Allowed: {sorted(RELATIONSHIP_TYPES)}"
        )
    f = normalise_name(from_name)
    t = normalise_name(to_name)
    if not f or not t:
        return
    g = conn.g
    # Endpoints should already exist (extractor upserts entities first); create
    # a minimal node if not, so a relationship is never silently dropped.
    for nm, disp in ((f, from_name), (t, to_name)):
        if not g.has_node(nm):
            g.add_node(nm, display_name=disp, entity_type="concept",
                       created_at=_now(), last_seen_at=_now())
    g.add_edge(f, t, relationship=relationship, source_file=source_file,
               extracted_at=_now(), confidence=float(confidence))


# ---------- Queries ----------

def get_entity(conn, name: str) -> dict | None:
    """Return entity properties + neighbouring relationships."""
    norm = normalise_name(name)
    g = conn.g
    if not g.has_node(norm):
        return None
    nd = g.nodes[norm]
    out = [
        {
            "relationship": d.get("relationship"),
            "to": other,
            "to_display_name": g.nodes[other].get("display_name", other),
            "source_file": d.get("source_file", ""),
            "extracted_at": str(d.get("extracted_at", "")),
            "confidence": d.get("confidence"),
        }
        for _, other, d in g.out_edges(norm, data=True)
    ]
    incoming = [
        {
            "relationship": d.get("relationship"),
            "from": other,
            "from_display_name": g.nodes[other].get("display_name", other),
            "source_file": d.get("source_file", ""),
            "extracted_at": str(d.get("extracted_at", "")),
            "confidence": d.get("confidence"),
        }
        for other, _, d in g.in_edges(norm, data=True)
    ]
    return {
        "name": norm,
        "display_name": nd.get("display_name"),
        "entity_type": nd.get("entity_type"),
        "outgoing_relationships": out,
        "incoming_relationships": incoming,
    }


def stats(conn) -> dict:
    """Return node + edge counts."""
    return {"available": True, "nodes": conn.g.number_of_nodes(), "edges": conn.g.number_of_edges()}


def stats_unavailable(reason: str) -> dict:
    return {"available": False, "reason": reason}
