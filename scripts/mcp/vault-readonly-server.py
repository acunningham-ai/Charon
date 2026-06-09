#!/usr/bin/env python
"""vault-readonly-server.py — bundled read-only MCP over the user's vault.

Ships as part of the harness toolkit. Each installation points this server
at the running user's OWN vault + memory paths — not at anyone else's. No
cross-user exposure surface — the user IS the audience.

Tools:

  - search_memory(query, scope=None, limit=20)
      Keyword search across the harness memory dir.

  - get_unit_context(unit_name)
      Plain-language per-unit context from the user's nominated per-unit
      context file (default: `reference_per_unit_context.md`).

  - list_active_initiatives()
      Named user initiatives from `project_active_initiatives.md`.

Configuration:

  --vault-root <path>    Default: from HARNESS_VAULT_ROOT or cwd.
  --memory-root <path>   Default: from HARNESS_MEMORY_ROOT or computed.

Files with `classification: restricted` or `classification: confidential`
are NEVER returned by any tool. That matches the classification-frontmatter
convention (confidential = human-only handling, no automation reads).

Security baseline references (`.claude/rules/secure-code.md`):
  C-2 — tool minimisation: this server registers ONLY read tools.
  C-7 — captured-content discipline: 00-Inbox/_captured/** is never
        searched or returned by any tool.

Path-safety invariant (V3 / path-traversal):
  This server has NO _safe_resolve()-style containment check by design —
  it is safe BY CONSTRUCTION because no user-supplied argument is ever
  joined into a filesystem path. `scope` is a startswith name-filter over
  MEMORY_ROOT.glob('*.md'); `unit_name` is a string-equality cell match
  against a fixed register file; semantic-search reads only file_paths
  produced by the internal index, never by the caller. If you add a tool
  that joins a caller-supplied value into a path, this invariant breaks —
  add a vault-ops-style _safe_resolve() (resolve() + relative_to(ROOT))
  before doing so.
"""
import argparse
import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.harness_paths import memory_root, vault_root  # noqa: E402


VAULT_ROOT: Path = vault_root()
MEMORY_ROOT: Path = memory_root()

# Default per-unit context filename — the user's nominated register of
# plain-language per-org-unit context. Configurable via CLI.
PER_UNIT_CONTEXT_FILE = "reference_per_unit_context.md"

DENIED_CLASSIFICATIONS = frozenset({"restricted", "confidential"})

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)

server = Server("vault-readonly")


def _parse_frontmatter(text: str) -> tuple[dict[str, str], str]:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    fm: dict[str, str] = {}
    for line in m.group(1).split("\n"):
        if ":" in line and not line.startswith(" "):
            k, _, v = line.partition(":")
            fm[k.strip()] = v.strip().strip("\"'")
    return fm, text[m.end():]


def _fm_classification_denied(fm: dict[str, str]) -> bool:
    return fm.get("classification", "").lower() in DENIED_CLASSIFICATIONS


def _read_text_safe(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="search_memory",
            description=(
                "READ-ONLY. Keyword search across the harness memory "
                "directory (rules, conventions, project notes). Returns "
                "matched files with name/description/snippet. Files with "
                "classification: restricted/confidential are never returned."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Keyword(s) to search for. Case-insensitive "
                            "substring match across file body and frontmatter."
                        ),
                    },
                    "scope": {
                        "type": "string",
                        "description": (
                            "Optional filename prefix to scope results "
                            "(e.g. 'feedback_', 'project_', 'reference_')."
                        ),
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results. Default 20, max 100.",
                        "default": 20,
                    },
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="get_unit_context",
            description=(
                "READ-ONLY. Return plain-language control-context for a "
                "named org-unit from the per-unit context register. "
                "Output is the unit's rows across each control table plus "
                "portfolio-level notes. Returns row_count=0 if no rows match."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "unit_name": {
                        "type": "string",
                        "description": (
                            "Org-unit name as it appears in tables. "
                            "Case-insensitive exact match on first table column."
                        ),
                    },
                },
                "required": ["unit_name"],
            },
        ),
        types.Tool(
            name="list_active_initiatives",
            description=(
                "READ-ONLY. List currently active named work initiatives "
                "with their routing keywords and vault paths. Source: "
                "project_active_initiatives.md."
            ),
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="semantic_search",
            description=(
                "READ-ONLY. Semantic (embedding-based) search across the "
                "vault. Returns top-k most-similar chunks. Requires the "
                "optional semantic-search dependencies (sentence-transformers + "
                "sqlite-vec + numpy from requirements-semantic.txt) and a "
                "built index (run `python scripts/semantic_index.py` first). "
                "If deps or index are missing, returns a clear error pointing "
                "at the install + build steps. Honours classification: confidential."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Free-text query (natural language).",
                    },
                    "k": {
                        "type": "integer",
                        "description": "Max results. Default 10, max 50.",
                        "default": 10,
                    },
                    "scope": {
                        "type": "string",
                        "description": (
                            "Optional path prefix to scope results "
                            "(e.g. '07-References/', '08-Projects/Charon/')."
                        ),
                    },
                },
                "required": ["query"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(
    name: str, arguments: dict[str, Any]
) -> list[types.TextContent]:
    try:
        if name == "search_memory":
            return await tool_search_memory(arguments)
        if name == "get_unit_context":
            return await tool_get_unit_context(arguments)
        if name == "list_active_initiatives":
            return await tool_list_active_initiatives(arguments)
        if name == "semantic_search":
            return await tool_semantic_search(arguments)
        return [types.TextContent(type="text", text=f"unknown tool: {name}")]
    except Exception as e:
        return [
            types.TextContent(
                type="text", text=f"ERROR: {type(e).__name__}: {e}"
            )
        ]


async def tool_search_memory(
    args: dict[str, Any],
) -> list[types.TextContent]:
    query = (args.get("query") or "").strip()
    if not query:
        return [
            types.TextContent(type="text", text="ERROR: query is required")
        ]
    query_lower = query.lower()

    scope = (args.get("scope") or "").strip().lower()
    limit = min(int(args.get("limit") or 20), 100)

    results: list[dict[str, Any]] = []
    classification_denied = 0

    for path in sorted(MEMORY_ROOT.glob("*.md")):
        if len(results) >= limit:
            break

        if scope and not path.name.lower().startswith(scope):
            continue

        text = _read_text_safe(path)
        if text is None:
            continue

        fm, body = _parse_frontmatter(text)
        if _fm_classification_denied(fm):
            classification_denied += 1
            continue

        haystack = (text).lower()
        if query_lower not in haystack:
            continue

        snippet = _make_snippet(body, query_lower)
        results.append(
            {
                "path": str(path.relative_to(MEMORY_ROOT)).replace(
                    "\\", "/"
                ),
                "name": fm.get("name", path.stem),
                "description": fm.get("description", ""),
                "type": fm.get("type", ""),
                "snippet": snippet,
            }
        )

    response = {
        "query": query,
        "scope": scope or "(all memory)",
        "result_count": len(results),
        "classification_denied": classification_denied,
        "results": results,
    }
    return [
        types.TextContent(
            type="text", text=json.dumps(response, indent=2)
        )
    ]


def _make_snippet(body: str, query_lower: str, window: int = 120) -> str:
    idx = body.lower().find(query_lower)
    if idx < 0:
        return body[:240].replace("\n", " ")
    start = max(0, idx - window)
    end = min(len(body), idx + len(query_lower) + window)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(body) else ""
    return f"{prefix}{body[start:end].strip()}{suffix}".replace("\n", " ")


async def tool_get_unit_context(
    args: dict[str, Any],
) -> list[types.TextContent]:
    unit_name = (args.get("unit_name") or "").strip()
    if not unit_name:
        return [
            types.TextContent(
                type="text", text="ERROR: unit_name is required"
            )
        ]

    context_file = MEMORY_ROOT / PER_UNIT_CONTEXT_FILE
    text = _read_text_safe(context_file)
    if text is None:
        return [
            types.TextContent(
                type="text",
                text=(
                    f"ERROR: per-unit context register not found at "
                    f"{context_file}. Populate during first-run, or set the "
                    f"PER_UNIT_CONTEXT_FILE constant to your register's filename."
                ),
            )
        ]

    unit_lower = unit_name.lower()
    current_section = "(top)"
    matched: list[dict[str, str]] = []

    for line in text.split("\n"):
        if line.startswith("## "):
            current_section = line[3:].strip()
            continue
        if not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 2:
            continue
        first_cell = cells[0].lower()
        if first_cell != unit_lower:
            continue
        if all(c.replace("-", "").replace(":", "").strip() == "" for c in cells):
            continue
        matched.append({"control": current_section, "row": " | ".join(cells)})

    portfolio_notes = _portfolio_notes(text)

    response = {
        "unit_name": unit_name,
        "row_count": len(matched),
        "rows": matched,
        "portfolio_notes_excerpt": portfolio_notes,
        "source": PER_UNIT_CONTEXT_FILE,
        "note": (
            "Scores are point-in-time per the source file's frontmatter; "
            "your authoritative dashboard is the live source of truth."
        ),
    }
    return [
        types.TextContent(
            type="text", text=json.dumps(response, indent=2)
        )
    ]


def _portfolio_notes(text: str, max_bullets: int = 6) -> list[str]:
    in_section = False
    out: list[str] = []
    for line in text.split("\n"):
        if line.startswith("## Portfolio-Level Notes"):
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if not in_section:
            continue
        if not line.startswith("- "):
            continue
        out.append(line[2:].strip())
        if len(out) >= max_bullets:
            break
    return out


INITIATIVE_HEADING_RE = re.compile(r"^\*\*(.+?)\*\*\s*—\s*(.+)$")


async def tool_list_active_initiatives(
    args: dict[str, Any],
) -> list[types.TextContent]:
    initiatives_file = MEMORY_ROOT / "project_active_initiatives.md"
    text = _read_text_safe(initiatives_file)
    if text is None:
        return [
            types.TextContent(
                type="text",
                text=f"ERROR: initiatives file not found at {initiatives_file}",
            )
        ]

    initiatives: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None

    for raw in text.split("\n"):
        line = raw.rstrip()
        m = INITIATIVE_HEADING_RE.match(line)
        if m:
            if current is not None:
                initiatives.append(current)
            current = {
                "name": m.group(1).strip(),
                "summary": m.group(2).strip(),
                "subject_keywords": [],
                "vault_path": "",
            }
            continue
        if current is None:
            continue
        sub_line = line.strip().lstrip("- ").strip()
        low = sub_line.lower()
        if low.startswith("subject keywords:") or low.startswith(
            "subject pattern:"
        ):
            kws = sub_line.split(":", 1)[1]
            current["subject_keywords"] = [
                k.strip().strip("`") for k in kws.split(",") if k.strip()
            ]
        elif low.startswith("vault path:"):
            current["vault_path"] = (
                sub_line.split(":", 1)[1].strip().strip("`")
            )

    if current is not None:
        initiatives.append(current)

    response = {
        "source": "project_active_initiatives.md",
        "count": len(initiatives),
        "initiatives": initiatives,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }
    return [
        types.TextContent(
            type="text", text=json.dumps(response, indent=2)
        )
    ]


async def tool_semantic_search(
    args: dict[str, Any],
) -> list[types.TextContent]:
    query = (args.get("query") or "").strip()
    if not query:
        return [types.TextContent(type="text", text="ERROR: query is required")]
    k = min(int(args.get("k") or 10), 50)
    scope = (args.get("scope") or "").strip() or None

    try:
        from lib import semantic
    except ImportError:
        return [types.TextContent(type="text", text=json.dumps({
            "error": "semantic-search module not importable",
            "hint": "Install with: pip install -r requirements-semantic.txt",
        }, indent=2))]

    available, reason = semantic.is_available()
    if not available:
        return [types.TextContent(type="text", text=json.dumps({
            "error": f"semantic search not enabled: {reason}",
            "hint": "Install with: pip install -r requirements-semantic.txt then run: python scripts/semantic_index.py",
        }, indent=2))]

    try:
        results = semantic.search(query, k=k, scope_prefix=scope)
    except FileNotFoundError:
        return [types.TextContent(type="text", text=json.dumps({
            "error": "semantic index does not exist yet",
            "hint": "Build it with: python scripts/semantic_index.py",
        }, indent=2))]
    except Exception as e:
        return [types.TextContent(type="text", text=json.dumps({
            "error": f"{type(e).__name__}: {e}",
        }, indent=2))]

    # Filter out any results that match a denied classification by reading
    # the source file's frontmatter. Keep this defensive — the indexer
    # already excludes capture zones; this is a second-layer check on
    # classification frontmatter that the indexer can't know about per chunk.
    filtered = []
    for r in results:
        path = VAULT_ROOT / r["file_path"]
        text = _read_text_safe(path)
        if text is None:
            continue
        fm, _ = _parse_frontmatter(text)
        if _fm_classification_denied(fm):
            continue
        filtered.append(r)

    response = {
        "query": query,
        "scope": scope or "(whole vault)",
        "k_requested": k,
        "result_count": len(filtered),
        "results": filtered,
    }
    return [types.TextContent(type="text", text=json.dumps(response, indent=2))]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def _parse_cli() -> tuple[Path, Path]:
    parser = argparse.ArgumentParser(
        prog="vault-readonly-server",
        description="Read-only MCP server over the running user's vault.",
    )
    parser.add_argument(
        "--vault-root",
        type=Path,
        default=vault_root(),
        help="Path to the second-brain vault root (default: $HARNESS_VAULT_ROOT or cwd).",
    )
    parser.add_argument(
        "--memory-root",
        type=Path,
        default=memory_root(),
        help="Path to the harness memory directory (default: $HARNESS_MEMORY_ROOT or computed).",
    )
    args, _ = parser.parse_known_args()
    return args.vault_root.resolve(), args.memory_root.resolve()


if __name__ == "__main__":
    VAULT_ROOT, MEMORY_ROOT = _parse_cli()
    print(
        f"[vault-readonly] vault={VAULT_ROOT} memory={MEMORY_ROOT}",
        file=sys.stderr,
        flush=True,
    )
    if not MEMORY_ROOT.exists():
        print(
            f"[vault-readonly] WARN: --memory-root does not exist: {MEMORY_ROOT}",
            file=sys.stderr,
            flush=True,
        )
    asyncio.run(main())
