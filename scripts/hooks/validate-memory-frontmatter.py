#!/usr/bin/env python3
"""
PostToolUse hook: validate frontmatter on memory file writes.

Required fields:
  - name         — short label
  - description  — one-line hook used to decide relevance
  - type         — one of: user, feedback, project, reference

Skips:
  - MEMORY.md (the index — different shape, no frontmatter)
  - memory/sessions/*.md (auto-generated session journals)

Exit codes:
  0 = OK or non-applicable
  1 = warning emitted on stderr (non-blocking)
"""
import json
import re
import sys
from pathlib import Path

try:
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


REQUIRED = ["name", "description", "type"]
VALID_TYPES = {"user", "feedback", "project", "reference"}


def is_memory_file(path_str: str) -> bool:
    p = path_str.replace("\\", "/")
    return "/memory/" in p and p.endswith(".md")


def is_skipped(path_str: str) -> bool:
    p = path_str.replace("\\", "/")
    if p.endswith("/MEMORY.md"):
        return True
    if "/memory/sessions/" in p:
        return True
    return False


def parse_top_level(fm_text: str) -> dict:
    """Tiny YAML reader for top-level scalar fields."""
    out: dict = {}
    for raw in fm_text.split("\n"):
        line = raw.rstrip()
        if not line.strip() or line.startswith(" "):
            continue
        if ":" in line:
            k, _, v = line.partition(":")
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    tool_input = data.get("tool_input", {}) or {}
    file_path = tool_input.get("file_path", "")
    if not file_path or not is_memory_file(file_path) or is_skipped(file_path):
        return 0

    try:
        content = Path(file_path).read_text(encoding="utf-8")
    except Exception:
        return 0

    issues = []
    m = re.match(r"^---\r?\n(.*?)\r?\n---", content, re.S)
    if not m:
        issues.append("missing frontmatter block (must start with `---`)")
    else:
        fm = parse_top_level(m.group(1))
        for f in REQUIRED:
            if not fm.get(f):
                issues.append(f"missing or empty `{f}` field")
        t = fm.get("type", "")
        if t and t not in VALID_TYPES:
            issues.append(
                f"`type: {t}` is not a recognised type "
                f"(expected one of: {', '.join(sorted(VALID_TYPES))})"
            )

    if issues:
        name = Path(file_path).name
        sys.stderr.write(
            f"WARN (memory frontmatter validator): `{name}` has issues:\n"
        )
        for i in issues:
            sys.stderr.write(f"  - {i}\n")
        sys.stderr.write(
            "These are non-blocking — fix in the next edit so the file "
            "stays consistent with the MEMORY.md convention.\n"
        )
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
