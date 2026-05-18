"""graph.py — local knowledge-graph core.

Shared library for:
- `scripts/extract_entities.py` (CLI extractor)
- `scripts/mcp/vault-graph-server.py` (the vault-graph MCP server)

Local-first design:
- Backend: `kuzu` (embedded graph database, single binary, no server)
- Extraction: Anthropic SDK (Haiku) called by the extractor only — runs at
  index time, NOT at query time. The MCP query path is fully local.

Schema (v1, minimal):

  Entity {
    name STRING PRIMARY KEY,    # case-normalised — "acme-corp", "jane-doe"
    display_name STRING,         # original casing — "Acme Corp", "Jane Doe"
    entity_type STRING,          # person | project | org_unit | tool | concept | event | document
    created_at TIMESTAMP,
    last_seen_at TIMESTAMP
  }

  Mentions {
    FROM Entity TO Entity,
    relationship STRING,         # WORKS_ON | OWNS | AFFECTS | REFERENCES | DEPENDS_ON | ...
    source_file STRING,          # path the relationship was extracted from
    extracted_at TIMESTAMP,
    confidence DOUBLE            # 0.0 - 1.0
  }

Index file: <HARNESS_VAULT_ROOT>/.charon/knowledge-graph.kuzu
"""
from __future__ import annotations

from pathlib import Path

from .harness_paths import vault_root


GRAPH_REL_PATH = ".charon/knowledge-graph.kuzu"

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
    """Returns (available, reason)."""
    try:
        import kuzu  # noqa: F401
    except ImportError:
        return False, "kuzu not installed"
    return True, ""


def graph_path() -> Path:
    return vault_root() / GRAPH_REL_PATH


def open_graph(create_if_missing: bool = True):
    """Open the kuzu graph database, creating schema on first use.
    Returns (db, conn)."""
    import kuzu

    path = graph_path()
    if not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists() and not create_if_missing:
        raise FileNotFoundError(
            f"Knowledge graph not found at {path}. "
            f"Run scripts/extract_entities.py first."
        )

    db = kuzu.Database(str(path))
    conn = kuzu.Connection(db)

    # Create schema if missing. kuzu's IF NOT EXISTS is supported on newer
    # versions; we fall back to inspecting catalogs for older versions.
    try:
        conn.execute("""
            CREATE NODE TABLE IF NOT EXISTS Entity(
                name STRING PRIMARY KEY,
                display_name STRING,
                entity_type STRING,
                created_at TIMESTAMP,
                last_seen_at TIMESTAMP
            )
        """)
    except Exception:
        try:
            conn.execute("""
                CREATE NODE TABLE Entity(
                    name STRING PRIMARY KEY,
                    display_name STRING,
                    entity_type STRING,
                    created_at TIMESTAMP,
                    last_seen_at TIMESTAMP
                )
            """)
        except Exception:
            pass  # already exists

    try:
        conn.execute("""
            CREATE REL TABLE IF NOT EXISTS Mentions(
                FROM Entity TO Entity,
                relationship STRING,
                source_file STRING,
                extracted_at TIMESTAMP,
                confidence DOUBLE
            )
        """)
    except Exception:
        try:
            conn.execute("""
                CREATE REL TABLE Mentions(
                    FROM Entity TO Entity,
                    relationship STRING,
                    source_file STRING,
                    extracted_at TIMESTAMP,
                    confidence DOUBLE
                )
            """)
        except Exception:
            pass

    return db, conn


# ---------- Normalisation ----------

def normalise_name(name: str) -> str:
    """kebab-case lowercase, used as the entity primary key."""
    import re
    s = re.sub(r"\s+", "-", name.strip().lower())
    return re.sub(r"[^\w\-]", "", s)


# ---------- Upserts ----------

def upsert_entity(conn, name: str, display_name: str, entity_type: str) -> None:
    """Idempotent entity insert/update. Refuses unknown entity_type."""
    if entity_type not in ENTITY_TYPES:
        raise ValueError(f"unknown entity_type: {entity_type}. Allowed: {sorted(ENTITY_TYPES)}")
    norm = normalise_name(name)
    if not norm:
        return
    conn.execute("""
        MERGE (e:Entity {name: $name})
        ON CREATE SET
            e.display_name = $display_name,
            e.entity_type = $entity_type,
            e.created_at = CURRENT_TIMESTAMP(),
            e.last_seen_at = CURRENT_TIMESTAMP()
        ON MATCH SET
            e.last_seen_at = CURRENT_TIMESTAMP()
    """, {"name": norm, "display_name": display_name, "entity_type": entity_type})


def add_relationship(
    conn,
    from_name: str,
    to_name: str,
    relationship: str,
    source_file: str,
    confidence: float = 0.9,
) -> None:
    """Add a relationship between two entities. Refuses unknown relationship type."""
    if relationship not in RELATIONSHIP_TYPES:
        raise ValueError(
            f"unknown relationship: {relationship}. "
            f"Allowed: {sorted(RELATIONSHIP_TYPES)}"
        )
    from_norm = normalise_name(from_name)
    to_norm = normalise_name(to_name)
    if not from_norm or not to_norm:
        return
    conn.execute("""
        MATCH (a:Entity {name: $from_name}), (b:Entity {name: $to_name})
        CREATE (a)-[:Mentions {
            relationship: $rel,
            source_file: $src,
            extracted_at: CURRENT_TIMESTAMP(),
            confidence: $conf
        }]->(b)
    """, {
        "from_name": from_norm,
        "to_name": to_norm,
        "rel": relationship,
        "src": source_file,
        "conf": confidence,
    })


# ---------- Queries ----------

def get_entity(conn, name: str) -> dict | None:
    """Return entity properties + neighbouring relationships."""
    norm = normalise_name(name)
    result = conn.execute(
        "MATCH (e:Entity {name: $name}) RETURN e",
        {"name": norm},
    )
    if not result.has_next():
        return None
    row = result.get_next()
    entity = dict(row[0]) if row else None
    if not entity:
        return None

    # Outgoing edges
    out_rs = conn.execute("""
        MATCH (e:Entity {name: $name})-[r:Mentions]->(other:Entity)
        RETURN r.relationship AS rel, other.name AS to, other.display_name AS to_display,
               r.source_file AS src, r.extracted_at AS at, r.confidence AS conf
    """, {"name": norm})
    out = []
    while out_rs.has_next():
        r = out_rs.get_next()
        out.append({
            "relationship": r[0],
            "to": r[1],
            "to_display_name": r[2],
            "source_file": r[3],
            "extracted_at": str(r[4]),
            "confidence": r[5],
        })

    # Incoming edges
    in_rs = conn.execute("""
        MATCH (other:Entity)-[r:Mentions]->(e:Entity {name: $name})
        RETURN r.relationship AS rel, other.name AS from, other.display_name AS from_display,
               r.source_file AS src, r.extracted_at AS at, r.confidence AS conf
    """, {"name": norm})
    incoming = []
    while in_rs.has_next():
        r = in_rs.get_next()
        incoming.append({
            "relationship": r[0],
            "from": r[1],
            "from_display_name": r[2],
            "source_file": r[3],
            "extracted_at": str(r[4]),
            "confidence": r[5],
        })

    return {
        "name": entity.get("name"),
        "display_name": entity.get("display_name"),
        "entity_type": entity.get("entity_type"),
        "outgoing_relationships": out,
        "incoming_relationships": incoming,
    }


def stats(conn) -> dict:
    """Return node + edge counts."""
    try:
        node_count = conn.execute("MATCH (e:Entity) RETURN COUNT(e)").get_next()[0]
    except Exception:
        node_count = 0
    try:
        edge_count = conn.execute("MATCH ()-[r:Mentions]->() RETURN COUNT(r)").get_next()[0]
    except Exception:
        edge_count = 0
    return {"available": True, "nodes": node_count, "edges": edge_count}


def stats_unavailable(reason: str) -> dict:
    return {"available": False, "reason": reason}
