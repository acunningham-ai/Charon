#!/usr/bin/env python
"""vault-graph-server.py — knowledge-graph MCP server backed by kuzu.

Tools:
- get_entity(name)            : entity + its outgoing/incoming relationships
- query_graph(cypher, limit)  : run a Cypher-ish read query (advanced)
- stats()                     : graph node + edge counts

The graph is populated by `scripts/extract_entities.py` (called by hand or
on a schedule — extraction uses Haiku and incurs cost; not in the
synchronous hook path).

If the optional `kuzu` dep isn't installed or the graph file doesn't yet
exist, tools return a clear error pointing at the install + build steps.
The server itself launches fine without kuzu — only the tools fail
gracefully when called.

Security:
- READ-ONLY against the graph (no Cypher writes accepted via MCP).
- Defensive: query_graph strips/rejects MERGE / CREATE / DELETE / DROP
  / SET keywords before passing to kuzu.
"""
import argparse
import asyncio
import json
import re
import sys
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.harness_paths import vault_root  # noqa: E402


VAULT_ROOT: Path = vault_root()

WRITE_KEYWORDS = re.compile(
    r"\b(CREATE|MERGE|DELETE|DROP|SET|REMOVE|DETACH)\b",
    re.IGNORECASE,
)

server = Server("vault-graph")


def _graph_unavailable_response(reason: str, hint: str) -> list[types.TextContent]:
    return [types.TextContent(type="text", text=json.dumps({
        "error": reason,
        "hint": hint,
    }, indent=2))]


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="get_entity",
            description=(
                "READ-ONLY. Look up an entity by name (case-insensitive) and "
                "return its properties + outgoing and incoming relationships. "
                "Use this to ask 'what do we know about X?' for any entity in "
                "the knowledge graph. Returns null if the entity isn't present "
                "(yet to be extracted, or never mentioned)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "Entity name (case-insensitive).",
                    },
                },
                "required": ["name"],
            },
        ),
        types.Tool(
            name="query_graph",
            description=(
                "READ-ONLY. Run a Cypher read query against the graph. "
                "Useful for traversals like 'who works on what' or 'projects "
                "that depend on tool X'. Write keywords (CREATE/MERGE/DELETE/"
                "DROP/SET/REMOVE/DETACH) are rejected. Limit is enforced at 100."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "cypher": {
                        "type": "string",
                        "description": (
                            "Cypher query — read-only. Example: "
                            "'MATCH (p:Entity {entity_type: \"person\"})-[r:Mentions]->(pr:Entity) "
                            "RETURN p.display_name, r.relationship, pr.display_name LIMIT 20'"
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Cap on rows. Default 50, max 100.",
                        "default": 50,
                    },
                },
                "required": ["cypher"],
            },
        ),
        types.Tool(
            name="stats",
            description=(
                "READ-ONLY. Node + edge counts. Cheap. Useful to confirm "
                "the graph has been populated."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    try:
        from lib import graph
    except ImportError:
        return _graph_unavailable_response(
            "vault-graph module not importable",
            "Install: pip install -r requirements-graph.txt",
        )

    available, reason = graph.is_available()
    if not available:
        return _graph_unavailable_response(
            f"knowledge graph not enabled: {reason}",
            "Install: pip install -r requirements-graph.txt, then run: python scripts/extract_entities.py",
        )

    try:
        if name == "get_entity":
            return await tool_get_entity(arguments, graph)
        if name == "query_graph":
            return await tool_query_graph(arguments, graph)
        if name == "stats":
            return await tool_stats(arguments, graph)
        return [types.TextContent(type="text", text=f"unknown tool: {name}")]
    except Exception as e:
        return [types.TextContent(type="text", text=json.dumps({
            "error": f"{type(e).__name__}: {e}",
        }, indent=2))]


async def tool_get_entity(args: dict[str, Any], graph) -> list[types.TextContent]:
    name = (args.get("name") or "").strip()
    if not name:
        return [types.TextContent(type="text", text="ERROR: name is required")]
    try:
        _db, conn = graph.open_graph(create_if_missing=False)
    except FileNotFoundError:
        return _graph_unavailable_response(
            "graph file does not exist yet",
            "Build it: python scripts/extract_entities.py",
        )
    result = graph.get_entity(conn, name)
    if result is None:
        return [types.TextContent(type="text", text=json.dumps({
            "found": False,
            "name": name,
            "hint": "Entity not in graph. Either not yet extracted (run extract_entities.py) or not mentioned in any indexed file.",
        }, indent=2))]
    payload = {"found": True, **result}
    return [types.TextContent(type="text", text=json.dumps(payload, indent=2))]


async def tool_query_graph(args: dict[str, Any], graph) -> list[types.TextContent]:
    cypher = (args.get("cypher") or "").strip()
    if not cypher:
        return [types.TextContent(type="text", text="ERROR: cypher is required")]
    if WRITE_KEYWORDS.search(cypher):
        return [types.TextContent(type="text", text=json.dumps({
            "error": "write keywords detected — this MCP tool is READ-ONLY",
            "rejected_pattern": WRITE_KEYWORDS.search(cypher).group(0),
        }, indent=2))]
    limit = min(int(args.get("limit") or 50), 100)
    if "limit" not in cypher.lower():
        cypher = f"{cypher.rstrip(';')} LIMIT {limit}"

    try:
        _db, conn = graph.open_graph(create_if_missing=False)
    except FileNotFoundError:
        return _graph_unavailable_response(
            "graph file does not exist yet",
            "Build it: python scripts/extract_entities.py",
        )

    try:
        result = conn.execute(cypher)
    except Exception as e:
        return [types.TextContent(type="text", text=json.dumps({
            "error": f"query failed: {type(e).__name__}: {e}",
            "cypher": cypher,
        }, indent=2))]

    rows = []
    while result.has_next():
        row = result.get_next()
        rows.append([_jsonable(v) for v in row])
        if len(rows) >= limit:
            break

    return [types.TextContent(type="text", text=json.dumps({
        "cypher": cypher,
        "row_count": len(rows),
        "rows": rows,
    }, indent=2))]


async def tool_stats(args: dict[str, Any], graph) -> list[types.TextContent]:
    try:
        _db, conn = graph.open_graph(create_if_missing=False)
    except FileNotFoundError:
        return [types.TextContent(type="text", text=json.dumps({
            "available": True,
            "exists": False,
            "hint": "Run extract_entities.py to build the graph.",
        }, indent=2))]
    s = graph.stats(conn)
    return [types.TextContent(type="text", text=json.dumps({**s, "exists": True}, indent=2))]


def _jsonable(v):
    """Make kuzu values JSON-serialisable."""
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, dict):
        return {k: _jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_jsonable(x) for x in v]
    return str(v)


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def _parse_cli() -> Path:
    parser = argparse.ArgumentParser(
        prog="vault-graph-server",
        description="Knowledge-graph MCP server (read-only) backed by kuzu.",
    )
    parser.add_argument(
        "--vault-root",
        type=Path,
        default=vault_root(),
        help="Path to vault root (default: $HARNESS_VAULT_ROOT or cwd).",
    )
    args, _ = parser.parse_known_args()
    return args.vault_root.resolve()


if __name__ == "__main__":
    VAULT_ROOT = _parse_cli()
    print(f"[vault-graph] vault={VAULT_ROOT}", file=sys.stderr, flush=True)
    asyncio.run(main())
