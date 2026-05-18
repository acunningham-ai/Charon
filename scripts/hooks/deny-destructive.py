#!/usr/bin/env python3
"""
PreToolUse hook: block writes/edits/deletes to immutable zones in the vault.

These zones are documented as read-only in the vault root `CLAUDE.md` under
"Self-Protection". This hook is belt-and-braces over that prose rule —
catches accidental writes the human-readable rule could miss.

Default protected zones (extend in your CLAUDE.md / by editing this script):
  - **/09-Archive/**                                  (cold storage)
  - **/voice-examples/**                              (voice anchors — input only; matches any project)
  - **/.claude/projects/**/memory/sessions/**         (past session journals are immutable)
  - **/published/*.md                                 (only if `posted:` field is set; matches any project)

Exit codes:
  0  = allow (default)
  2  = block; stderr is shown to Claude as the reason

Failures during the hook itself never block — exits 0 silently.
"""
import json
import re
import sys
from pathlib import Path

try:
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


PROTECTED_GLOBS = [
    "**/09-Archive/**",
    "**/voice-examples/**",
    "**/.claude/projects/**/memory/sessions/**",
]
PUBLISHED_GLOB = "**/published/*.md"

# Top-level frontmatter keys allowed to change on a published post.
# /linkedin-metrics writes 48h and 7d snapshots plus a qualitative reaction.
PUBLISHED_METRICS_FIELDS = {"metrics_48h", "metrics_7d", "gut_reaction", "notes"}


def glob_to_regex(glob: str) -> str:
    """Convert a glob (with `**`, `*`, `?`) to a regex string.
    `**/` and `/**` collapse zero-or-more directory segments so leading-`**/`
    matches zero-prefix paths (`**/foo` matches `foo` AND `dir/foo`).
    """
    g = glob.replace("\\", "/")
    out = []
    i = 0
    while i < len(g):
        if g[i:i + 3] == "**/":
            out.append("(?:.*/)?")
            i += 3
        elif g[i:i + 3] == "/**":
            out.append("(?:/.*)?")
            i += 3
        elif g[i:i + 2] == "**":
            out.append(".*")
            i += 2
        elif g[i] == "*":
            out.append("[^/]*")
            i += 1
        elif g[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(g[i]))
            i += 1
    return "^" + "".join(out) + "$"


def matches(glob: str, path: str) -> bool:
    return re.fullmatch(glob_to_regex(glob), path.replace("\\", "/")) is not None


def split_frontmatter_blocks(fm_text: str) -> dict:
    """Split a YAML frontmatter body into top-level key blocks."""
    blocks: dict = {}
    current_key = None
    current_lines: list = []
    for line in fm_text.split("\n"):
        is_top_level = bool(line) and not line[0].isspace() and ":" in line
        if is_top_level:
            if current_key is not None:
                blocks[current_key] = "\n".join(current_lines)
            current_key = line.split(":", 1)[0].strip()
            current_lines = [line]
        else:
            if current_key is not None:
                current_lines.append(line)
    if current_key is not None:
        blocks[current_key] = "\n".join(current_lines)
    return blocks


def is_metrics_only_edit(file_path: str, old_string: str, new_string: str) -> bool:
    """Allow Edit on a published post if it only touches metrics fields."""
    try:
        original = Path(file_path).read_text(encoding="utf-8")
    except Exception:
        return False
    if old_string not in original:
        return False
    hypothetical = original.replace(old_string, new_string, 1)

    m_old = re.match(r"^---\r?\n(.*?)\r?\n---", original, re.S)
    m_new = re.match(r"^---\r?\n(.*?)\r?\n---", hypothetical, re.S)
    if not m_old or not m_new:
        return False

    if original[m_old.end():] != hypothetical[m_new.end():]:
        return False  # body changed

    blocks_old = split_frontmatter_blocks(m_old.group(1))
    blocks_new = split_frontmatter_blocks(m_new.group(1))
    if set(blocks_old.keys()) != set(blocks_new.keys()):
        return False  # top-level keys added or removed

    differing = {k for k in blocks_old if blocks_old[k] != blocks_new[k]}
    return differing.issubset(PUBLISHED_METRICS_FIELDS)


def has_posted_set(path_str: str) -> bool:
    try:
        path = Path(path_str)
        if not path.exists():
            return False
        content = path.read_text(encoding="utf-8")
        m = re.match(r"^---\r?\n(.*?)\r?\n---", content, re.S)
        if not m:
            return False
        for line in m.group(1).split("\n"):
            line = line.strip()
            if line.startswith("posted:"):
                val = line.split(":", 1)[1].strip()
                if val and val.lower() not in ("null", "~", '""', "''"):
                    return True
        return False
    except Exception:
        return False


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    tool_input = data.get("tool_input", {}) or {}
    file_path = (
        tool_input.get("file_path")
        or tool_input.get("notebook_path")
        or ""
    )
    if not file_path:
        return 0

    for glob in PROTECTED_GLOBS:
        if matches(glob, file_path):
            sys.stderr.write(
                f"BLOCKED by deny-destructive hook: `{file_path}` is in a "
                f"protected zone (matched `{glob}`).\n\n"
                f"This zone is marked read-only in the vault root `CLAUDE.md` "
                f"\"Self-Protection\". If this edit is intentional, ask the user "
                f"to confirm before proceeding.\n"
            )
            return 2

    if matches(PUBLISHED_GLOB, file_path) and has_posted_set(file_path):
        tool_name = data.get("tool_name", "")
        if tool_name == "Edit":
            if is_metrics_only_edit(
                file_path,
                tool_input.get("old_string", ""),
                tool_input.get("new_string", ""),
            ):
                return 0  # metrics-only edit, allowed
        sys.stderr.write(
            f"BLOCKED by deny-destructive hook: `{file_path}` is a published "
            f"LinkedIn post (`posted:` is set in frontmatter). These are "
            f"read-only after publishing. Metrics updates are allowed via the Edit "
            f"tool when only these top-level fields change: "
            f"{', '.join(sorted(PUBLISHED_METRICS_FIELDS))}.\n"
        )
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
