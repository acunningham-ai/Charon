#!/usr/bin/env python3
"""
UserPromptSubmit hook: load path-specific rules from .claude/rules/*.md
and inject the matching ones as additional context.

Each rule file has YAML-ish frontmatter with three optional matchers:

    ---
    always: true
    paths:
      - "08-Projects/LinkedIn-Agent/**"
      - "**/Board-*.md"
    keywords:
      - "linkedin"
      - "draft a post"
    ---

A rule is injected when ANY of:
  - `always: true` (rule fires on every prompt — for baseline behavioural
    rules like no-assumptions, save-on-mention, session-start-ritual), OR
  - any path mentioned in the user's prompt matches one of `paths`, OR
  - any keyword in `keywords` appears in the prompt (case-insensitive,
    substring match — keywords with spaces match across words).

Stdin: JSON from Claude Code with at minimum a "prompt" field.
Stdout: markdown injected as additional context for the model.
Failures are silent — never block the prompt.
"""
import json
import os
import re
import sys
from pathlib import Path

# Force UTF-8 stdout — Windows defaults to cp1252 and chokes on common
# unicode (e.g. ≠, em-dashes) found in rule bodies.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def find_vault_root(start: Path) -> Path:
    """Walk up looking for a .claude/rules dir. Falls back to start's parent."""
    cur = start
    for _ in range(6):
        if (cur / ".claude" / "rules").is_dir():
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return start


def parse_frontmatter(content: str):
    """Tiny YAML-ish frontmatter parser: handles scalars and `- ` lists."""
    m = re.match(r"^---\r?\n(.*?)\r?\n---\r?\n?(.*)$", content, re.S)
    if not m:
        return {}, content
    fm_text, body = m.group(1), m.group(2)
    fm: dict = {}
    current_key = None
    for raw in fm_text.split("\n"):
        line = raw.rstrip()
        if not line.strip():
            continue
        stripped = line.lstrip()
        indent = len(line) - len(stripped)
        if stripped.startswith("- ") and current_key and indent > 0:
            val = stripped[2:].strip().strip('"').strip("'")
            fm.setdefault(current_key, []).append(val)
            continue
        if ":" in stripped and indent == 0:
            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            current_key = key
            if val:
                fm[key] = val
            else:
                fm[key] = []
    return fm, body


def glob_to_regex(pattern: str) -> str:
    """Convert a glob (with `**`, `*`, `?`) to a regex string.
    `**/` and `/**` collapse zero-or-more directory segments so leading-`**/`
    matches zero-prefix paths (`**/foo` matches `foo` AND `dir/foo`).
    """
    g = pattern.replace("\\", "/")
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


def glob_match(pattern: str, path: str) -> bool:
    pattern_n = pattern.replace("\\", "/")
    path_n = path.replace("\\", "/")
    return re.fullmatch(glob_to_regex(pattern_n), path_n) is not None


PATH_PATTERNS = [
    re.compile(r"\b(0\d-[A-Za-z][\w\-]*/[\w\-./]+)"),
    re.compile(r"`([^`\n]+\.(?:md|json|py|js|ts|sh|bat|yaml|yml))`"),
    re.compile(r"(?<![\w/])([\w\-]+/[\w\-/.]+\.(?:md|json|py|js|ts|sh|bat|yaml|yml))"),
]


def extract_paths(prompt: str) -> set:
    found = set()
    for pat in PATH_PATTERNS:
        for m in pat.finditer(prompt):
            found.add(m.group(1))
    return found


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return

    cwd = Path(data.get("cwd") or os.getcwd())
    project_dir = Path(os.environ.get("CLAUDE_PROJECT_DIR") or cwd)
    vault = find_vault_root(project_dir)
    rules_dir = vault / ".claude" / "rules"
    if not rules_dir.is_dir():
        return

    prompt_lower = prompt.lower()
    prompt_paths = extract_paths(prompt)

    matched = []
    for rule_file in sorted(rules_dir.glob("*.md")):
        try:
            content = rule_file.read_text(encoding="utf-8")
        except Exception:
            continue
        fm, body = parse_frontmatter(content)

        rule_paths = fm.get("paths") or []
        if isinstance(rule_paths, str):
            rule_paths = [rule_paths]
        rule_keywords = fm.get("keywords") or []
        if isinstance(rule_keywords, str):
            rule_keywords = [rule_keywords]

        why = None
        if str(fm.get("always", "")).strip().lower() in ("true", "yes", "1"):
            why = "always-fire rule"
        if not why:
            for prompt_path in prompt_paths:
                for glob in rule_paths:
                    if glob and glob_match(glob, prompt_path):
                        why = f"path `{prompt_path}` matched `{glob}`"
                        break
                if why:
                    break
        if not why:
            for kw in rule_keywords:
                if not kw:
                    continue
                if kw.lower() in prompt_lower:
                    why = f"keyword `{kw}` matched"
                    break
        if why:
            matched.append((rule_file.name, why, body.strip()))

    if not matched:
        return

    out = ["# Path-specific rules (auto-loaded by load-rules.py)\n"]
    for name, why, body in matched:
        out.append(f"## `{name}` — {why}\n")
        out.append(body)
        out.append("")
    sys.stdout.write("\n".join(out))


if __name__ == "__main__":
    main()
