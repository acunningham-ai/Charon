#!/usr/bin/env python
"""vault-graph-server.py — knowledge-graph MCP server (read-only, networkx-backed).

Tools:
- get_entity(name)            : entity + its outgoing/incoming relationships
- stats()                     : graph node + edge counts

The graph is populated by `scripts/extract_entities.py` (called by hand or
on a schedule — extraction uses Haiku and incurs cost; not in the
synchronous hook path).

If the optional graph deps aren't installed or the graph file doesn't yet
exist, tools return a clear error pointing at the install + build steps.
The server itself launches fine without the deps — only the tools fail
gracefully when called.

Security:
- READ-ONLY against the graph **by construction**: queries go through
  `open_graph_readonly()`, which returns a frozen networkx graph whose
  `.save()` raises. No mutation surface is exposed via MCP — there is no
  free-form query passthrough.
"""
import argparse
import asyncio
import json
import sys
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.harness_paths import vault_root  # noqa: E402


VAULT_ROOT: Path = vault_root()

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
        conn = graph.open_graph_readonly()
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


async def tool_stats(args: dict[str, Any], graph) -> list[types.TextContent]:
    try:
        conn = graph.open_graph_readonly()
    except FileNotFoundError:
        return [types.TextContent(type="text", text=json.dumps({
            "available": True,
            "exists": False,
            "hint": "Run extract_entities.py to build the graph.",
        }, indent=2))]
    s = graph.stats(conn)
    return [types.TextContent(type="text", text=json.dumps({**s, "exists": True}, indent=2))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def _parse_cli() -> Path:
    parser = argparse.ArgumentParser(
        prog="vault-graph-server",
        description="Knowledge-graph MCP server (read-only, networkx-backed).",
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
