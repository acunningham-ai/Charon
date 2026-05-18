#!/usr/bin/env python
"""vault-ops-server.py — local stdio MCP server for surgical vault operations.

Exposes three tools to Claude Code:

  - patch_note(path, frontmatter_patch=None, body_append=None,
               body_replace=None, body_search=None)
      Surgical edit of a markdown file. Frontmatter is merged (not replaced);
      body operations are either append, replace-section, or search-replace.

  - frontmatter_query(filters, scope=None, limit=50)
      Walk vault markdown files; return paths whose frontmatter matches the
      given filters. Filters are key/value matches with operators:
        {"trust": "untrusted"}                     # equality
        {"captured_at": {"before": "2026-05-04"}}  # ISO-date before
        {"classification": {"in": ["restricted", "confidential"]}}
        {"posted": {"present": False}}             # field is absent or null
      `scope` narrows to a subtree (e.g. "00-Inbox/_captured").

  - manage_tags(path, add=None, remove=None)
      Add or remove tags from a note's `tags:` frontmatter list. Idempotent.

Security baseline (07-References/security-baselines.md):
  C-2 — Tool minimisation: this server only operates on .md files within
        VAULT_ROOT. Refuses targets outside that scope.
  C-7 — Captured-content discipline: writes are blocked for paths under
        00-Inbox/_captured/** (captured content is untrusted and must
        not be modified by automation).
  C-3.1 — Value-layer constraint: structured fields (tags) use the
        save-on-mention TAG_ALLOWLIST.
"""
import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.server.stdio import stdio_server
import mcp.types as types

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.harness_paths import vault_root  # noqa: E402


VAULT_ROOT: Path = vault_root()

# Paths under these prefixes are READ-ONLY for the patch tool.
WRITE_BLOCKED_PREFIXES = (
    "00-Inbox/_captured",
    "09-Archive",
)

# Protected files — extra-strict, even patch with a tiny diff is refused.
PROTECTED_PATHS = {
    "CLAUDE.md",
    "MEMORY.md",
    "TODO.md",
}

# Reuse the tag allowlist from save-on-mention. Duplicated here intentionally
# so this server doesn't depend on importing the hook module.
TAG_ALLOWLIST = frozenset(
    {"correction", "gotcha", "fix", "pattern", "env", "convention"}
)

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


server = Server("vault-ops")


def _safe_resolve(path_str: str) -> Path:
    """Resolve a path string to an absolute path, ensuring it stays inside
    VAULT_ROOT. Raises ValueError if it would escape.
    """
    p = Path(path_str)
    if not p.is_absolute():
        p = VAULT_ROOT / p
    p = p.resolve()
    try:
        p.relative_to(VAULT_ROOT)
    except ValueError as e:
        raise ValueError(
            f"path '{path_str}' resolves outside vault root {VAULT_ROOT}"
        ) from e
    return p


def _rel_for_check(path: Path) -> str:
    return str(path.relative_to(VAULT_ROOT)).replace("\\", "/")


def _is_write_blocked(path: Path) -> tuple[bool, str]:
    rel = _rel_for_check(path)
    if rel in PROTECTED_PATHS or path.name in PROTECTED_PATHS:
        return True, f"'{rel}' is a protected file (read-only via this MCP)"
    for prefix in WRITE_BLOCKED_PREFIXES:
        if rel.startswith(prefix + "/") or rel == prefix:
            return True, f"'{rel}' is under '{prefix}/' — write-blocked"
    return False, ""


def _parse_yaml_simple(fm_text: str) -> dict[str, Any]:
    out: dict[str, Any] = {}
    lines = fm_text.split("\n")
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line or line.lstrip().startswith("#"):
            i += 1
            continue
        if not line[0].isspace() and ":" in line:
            key, _, val = line.partition(":")
            key = key.strip()
            val = val.strip()
            if val == "":
                items: list[str] = []
                j = i + 1
                while j < len(lines):
                    sub = lines[j]
                    if sub.startswith("  - ") or sub.startswith("- "):
                        item = sub.split("-", 1)[1].strip().strip("\"'")
                        items.append(item)
                        j += 1
                    elif not sub.strip():
                        j += 1
                    else:
                        break
                out[key] = items
                i = j
                continue
            elif val.startswith("[") and val.endswith("]"):
                inner = val[1:-1].strip()
                if not inner:
                    out[key] = []
                else:
                    out[key] = [
                        x.strip().strip("\"'") for x in inner.split(",")
                    ]
            else:
                out[key] = val.strip("\"'")
        i += 1
    return out


def _serialize_yaml_simple(d: dict[str, Any]) -> str:
    lines = []
    for k, v in d.items():
        if isinstance(v, list):
            if not v:
                lines.append(f"{k}: []")
            else:
                lines.append(f"{k}:")
                for item in v:
                    lines.append(f"  - {item}")
        else:
            s = str(v)
            if any(c in s for c in [":", "#", "[", "]", "{", "}", ","]):
                s = f"\"{s}\""
            lines.append(f"{k}: {s}")
    return "\n".join(lines)


def _split_frontmatter_and_body(text: str) -> tuple[dict[str, Any], str, bool]:
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text, False
    fm = _parse_yaml_simple(m.group(1))
    body = text[m.end():]
    return fm, body, True


def _compose(fm: dict[str, Any], body: str, had_fm: bool) -> str:
    if not fm and not had_fm:
        return body
    return f"---\n{_serialize_yaml_simple(fm)}\n---\n{body}"


def _matches_filter(value: Any, predicate: Any) -> bool:
    if isinstance(predicate, (str, int, float, bool)):
        return str(value) == str(predicate)
    if not isinstance(predicate, dict):
        return False

    if "in" in predicate:
        allowed = predicate["in"]
        return isinstance(allowed, list) and str(value) in [str(x) for x in allowed]
    if "not_in" in predicate:
        denied = predicate["not_in"]
        return isinstance(denied, list) and str(value) not in [str(x) for x in denied]
    if "present" in predicate:
        wanted = bool(predicate["present"])
        is_present = value is not None and value != "" and value != []
        return is_present == wanted
    if "before" in predicate or "after" in predicate:
        try:
            v = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return False
        if "before" in predicate:
            b = datetime.fromisoformat(str(predicate["before"]).replace("Z", "+00:00"))
            if v.tzinfo is None:
                v = v.replace(tzinfo=timezone.utc)
            if b.tzinfo is None:
                b = b.replace(tzinfo=timezone.utc)
            if not v < b:
                return False
        if "after" in predicate:
            a = datetime.fromisoformat(str(predicate["after"]).replace("Z", "+00:00"))
            if v.tzinfo is None:
                v = v.replace(tzinfo=timezone.utc)
            if a.tzinfo is None:
                a = a.replace(tzinfo=timezone.utc)
            if not v > a:
                return False
        return True
    if "contains" in predicate:
        if isinstance(value, list):
            return predicate["contains"] in value
        return predicate["contains"] in str(value)
    return False


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="patch_note",
            description=(
                "Surgical edit of a markdown file in the vault. Merges "
                "frontmatter patch (without replacing the whole block) and "
                "applies body operations (append, replace-by-search, or "
                "section-replace). Refuses writes to protected files "
                "(CLAUDE.md, MEMORY.md, TODO.md) and write-blocked prefixes "
                "(00-Inbox/_captured/, 09-Archive/)."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Vault-relative or absolute path to a .md file."
                    },
                    "frontmatter_patch": {
                        "type": "object",
                        "description": "Keys to set/update in frontmatter. Use null to delete a key."
                    },
                    "body_append": {
                        "type": "string",
                        "description": "Text to append to the body."
                    },
                    "body_search": {
                        "type": "string",
                        "description": "Literal string to find in body (paired with body_replace)."
                    },
                    "body_replace": {
                        "type": "string",
                        "description": "Replacement for body_search (single replacement)."
                    },
                },
                "required": ["path"],
            },
        ),
        types.Tool(
            name="frontmatter_query",
            description=(
                "Find .md files whose frontmatter matches the given filters. "
                "Filter operators: equality (key: value), {in: [...]}, "
                "{not_in: [...]}, {present: bool}, {before: iso-date}, "
                "{after: iso-date}, {contains: x}. Returns up to `limit` paths."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "filters": {
                        "type": "object",
                        "description": "Map of frontmatter key → predicate."
                    },
                    "scope": {
                        "type": "string",
                        "description": "Vault-relative subdirectory to scope search to. Optional."
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results. Default 50.",
                        "default": 50,
                    },
                },
                "required": ["filters"],
            },
        ),
        types.Tool(
            name="manage_tags",
            description=(
                "Add or remove tags from a note's `tags:` frontmatter list. "
                "Idempotent. Tags must be on the save-on-mention allowlist: "
                "correction, gotcha, fix, pattern, env, convention. "
                "Subject to the same protected-file rules as patch_note."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "add": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tags to add (allowlist enforced)."
                    },
                    "remove": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Tags to remove."
                    },
                },
                "required": ["path"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    try:
        if name == "patch_note":
            return await tool_patch_note(arguments)
        if name == "frontmatter_query":
            return await tool_frontmatter_query(arguments)
        if name == "manage_tags":
            return await tool_manage_tags(arguments)
        return [types.TextContent(type="text", text=f"unknown tool: {name}")]
    except Exception as e:
        return [types.TextContent(type="text", text=f"ERROR: {type(e).__name__}: {e}")]


async def tool_patch_note(args: dict[str, Any]) -> list[types.TextContent]:
    path_str = args.get("path", "")
    if not path_str:
        return [types.TextContent(type="text", text="ERROR: path is required")]

    path = _safe_resolve(path_str)
    if path.suffix.lower() != ".md":
        return [types.TextContent(
            type="text",
            text=f"ERROR: only .md files supported (got {path.suffix})"
        )]
    blocked, reason = _is_write_blocked(path)
    if blocked:
        return [types.TextContent(type="text", text=f"BLOCKED: {reason}")]
    if not path.exists():
        return [types.TextContent(type="text", text=f"ERROR: file does not exist: {path}")]

    text = path.read_text(encoding="utf-8")
    fm, body, had_fm = _split_frontmatter_and_body(text)

    fm_patch = args.get("frontmatter_patch") or {}
    for k, v in fm_patch.items():
        if v is None:
            fm.pop(k, None)
        else:
            fm[k] = v

    body_append = args.get("body_append")
    body_search = args.get("body_search")
    body_replace = args.get("body_replace")

    if body_search is not None and body_replace is not None:
        if body_search not in body:
            return [types.TextContent(
                type="text",
                text=f"ERROR: body_search string not found in body"
            )]
        body = body.replace(body_search, body_replace, 1)

    if body_append:
        if not body.endswith("\n"):
            body += "\n"
        body += body_append
        if not body.endswith("\n"):
            body += "\n"

    new_text = _compose(fm, body, had_fm or bool(fm))
    path.write_text(new_text, encoding="utf-8")
    return [types.TextContent(
        type="text",
        text=f"patched: {_rel_for_check(path)} ({len(text)} -> {len(new_text)} bytes)"
    )]


async def tool_frontmatter_query(args: dict[str, Any]) -> list[types.TextContent]:
    filters = args.get("filters") or {}
    scope_str = args.get("scope") or ""
    limit = int(args.get("limit") or 50)

    if scope_str:
        scope_path = _safe_resolve(scope_str)
    else:
        scope_path = VAULT_ROOT

    if not scope_path.exists():
        return [types.TextContent(type="text", text=f"ERROR: scope path does not exist")]

    matches: list[dict[str, Any]] = []
    for p in scope_path.rglob("*.md"):
        if len(matches) >= limit:
            break
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except (OSError, UnicodeDecodeError):
            continue
        fm, _, _ = _split_frontmatter_and_body(text)
        ok = True
        for key, pred in filters.items():
            value = fm.get(key)
            if not _matches_filter(value, pred):
                ok = False
                break
        if ok:
            matches.append({
                "path": _rel_for_check(p),
                "frontmatter": {k: fm.get(k) for k in filters},
            })

    return [types.TextContent(
        type="text",
        text=json.dumps({"count": len(matches), "matches": matches}, indent=2)
    )]


async def tool_manage_tags(args: dict[str, Any]) -> list[types.TextContent]:
    path_str = args.get("path", "")
    if not path_str:
        return [types.TextContent(type="text", text="ERROR: path is required")]

    path = _safe_resolve(path_str)
    blocked, reason = _is_write_blocked(path)
    if blocked:
        return [types.TextContent(type="text", text=f"BLOCKED: {reason}")]
    if not path.exists():
        return [types.TextContent(type="text", text=f"ERROR: file does not exist")]

    text = path.read_text(encoding="utf-8")
    fm, body, had_fm = _split_frontmatter_and_body(text)

    add = [t.strip().lower() for t in (args.get("add") or [])]
    remove = [t.strip().lower() for t in (args.get("remove") or [])]

    rejected = [t for t in add if t not in TAG_ALLOWLIST]
    add = [t for t in add if t in TAG_ALLOWLIST]

    tags = fm.get("tags")
    if not isinstance(tags, list):
        tags = []
    tags = [t for t in tags if t not in remove]
    for t in add:
        if t not in tags:
            tags.append(t)
    fm["tags"] = tags

    new_text = _compose(fm, body, had_fm or bool(fm))
    path.write_text(new_text, encoding="utf-8")

    msg = f"updated tags on {_rel_for_check(path)}: now {tags}"
    if rejected:
        msg += f". REJECTED (not on allowlist): {rejected}"
    return [types.TextContent(type="text", text=msg)]


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(),
        )


def _parse_cli() -> Path:
    parser = argparse.ArgumentParser(
        prog="vault-ops-server",
        description="Write-capable MCP server for the running user's vault.",
    )
    parser.add_argument(
        "--vault-root",
        type=Path,
        default=vault_root(),
        help="Path to the second-brain vault root (default: $HARNESS_VAULT_ROOT or cwd).",
    )
    args, _ = parser.parse_known_args()
    return args.vault_root.resolve()


if __name__ == "__main__":
    VAULT_ROOT = _parse_cli()
    print(f"[vault-ops] vault={VAULT_ROOT}", file=sys.stderr, flush=True)
    if not VAULT_ROOT.exists():
        print(
            f"[vault-ops] WARN: --vault-root does not exist: {VAULT_ROOT}",
            file=sys.stderr,
            flush=True,
        )
    asyncio.run(main())
