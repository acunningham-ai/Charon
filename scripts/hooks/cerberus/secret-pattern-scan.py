#!/usr/bin/env python3
"""
Cerberus secret-pattern-scan.py
Shared regex engine used by block-secrets.sh (and wired directly as a PreToolUse hook).
Run as: echo '<json>' | python secret-pattern-scan.py
Exits 2 with stderr message on a match. Exits 0 if clean.

Scope model:
  Each pattern carries a scope:
    "path"  -> matched ONLY against pathlike targets (Read file_path, Bash command).
               File/dir/command patterns. NOT matched against Write/Edit content,
               so documentation that merely *describes* a secret path is not blocked.
    "value" -> matched against ALL targets incl. Write/Edit content. Real credential
               VALUES (keys/tokens/PEM/JWT) are a leak wherever they appear.

Override: set ENABLE_CERBERUS=0 in the hook environment to disable.
Self-exemption: edits to this scanner's own source are not scanned (it necessarily
                contains pattern literals that would otherwise self-block).
"""

import json
import os
import re
import sys

# ---------------------------------------------------------------------------
# Pattern registry — (category_name, regex_string, scope)
# scope: "path" = pathlike targets only; "value" = all targets incl. content.
# Order: most specific first to reduce false-positive overlap.
# ---------------------------------------------------------------------------
SECRET_PATTERNS = [
    # File paths / extensions that should never be touched — scope "path"
    ("env-file", r"\.env($|\.)", "path"),
    ("pem-cert", r"\.pem$", "path"),
    ("key-file", r"\.key$", "path"),
    ("id-rsa", r"id_rsa", "path"),
    ("id-ed25519", r"id_ed25519", "path"),
    ("p12-cert", r"\.p12$", "path"),
    ("pfx-cert", r"\.pfx$", "path"),
    ("jks-keystore", r"\.jks$", "path"),

    # Credential directories — scope "path"
    ("aws-credentials-dir", r"\.aws/credentials", "path"),
    ("ssh-dir", r"\.ssh/", "path"),
    ("gcloud-dir", r"\.gcloud/", "path"),
    ("kube-config", r"\.kube/config", "path"),
    ("gnupg-dir", r"\.gnupg/", "path"),
    ("secrets-store", r"\.secrets[\\/]", "path"),  # conventional secrets dir (e.g. ~/.secrets/)

    # Commands that read .env files — scope "path" (match against the command)
    ("bash-cat-env", r"cat.*\.env", "path"),
    ("bash-head-env", r"head.*\.env", "path"),
    ("bash-tail-env", r"tail.*\.env", "path"),
    ("bash-less-env", r"less.*\.env", "path"),
    ("bash-grep-env", r"grep.*\.env", "path"),

    # AWS access keys — scope "value"
    ("aws-akia-key", r"AKIA[0-9A-Z]{16}", "value"),
    ("aws-asia-key", r"ASIA[0-9A-Z]{16}", "value"),
    ("aws-aroa-key", r"AROA[0-9A-Z]{16}", "value"),

    # GitHub tokens — scope "value"
    ("github-pat", r"github_pat_[a-zA-Z0-9]{82}", "value"),
    ("github-ghp", r"ghp_[a-zA-Z0-9]{36}", "value"),
    ("github-gho", r"gho_[a-zA-Z0-9]{36}", "value"),
    ("github-ghs", r"ghs_[a-zA-Z0-9]{36}", "value"),

    # Anthropic / Claude keys — check before generic sk- pattern — scope "value"
    ("anthropic-key-api", r"sk-ant-api[0-9]{2}", "value"),
    ("anthropic-key", r"sk-ant-[a-zA-Z0-9\-]{90,}", "value"),

    # OpenAI keys — scope "value"
    ("openai-proj-key", r"sk-proj-[a-zA-Z0-9\-]{80,}", "value"),
    ("openai-key", r"sk-[a-zA-Z0-9]{48}", "value"),

    # Slack tokens — scope "value"
    ("slack-bot-token", r"xoxb-[0-9]{11}-[0-9]{11}-[a-zA-Z0-9]{24}", "value"),
    ("slack-user-token", r"xoxp-", "value"),

    # Private keys (PEM headers) — scope "value"
    ("private-key-header", r"-----BEGIN (RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY", "value"),

    # JWT — scope "value"
    ("jwt-token", r"eyJ[A-Za-z0-9_-]{20,}\.eyJ[A-Za-z0-9_-]{20,}", "value"),
]

_COMPILED = [(name, re.compile(pattern), scope) for name, pattern, scope in SECRET_PATTERNS]

# This file's own basename — edits to it are exempt (it contains pattern literals).
_SELF_BASENAME = os.path.basename(__file__)

# ---------------------------------------------------------------------------
# Per-session dedup state
# ---------------------------------------------------------------------------
STATE_DIR = os.path.expanduser("~/.claude")
STATE_KEY = "blocked_categories"


def _state_file(session_id: str) -> str:
    return os.path.join(STATE_DIR, f"cerberus_state_{session_id}.json")


def _load_state(session_id: str) -> dict:
    path = _state_file(session_id)
    if os.path.exists(path):
        try:
            with open(path) as fh:
                return json.load(fh)
        except (json.JSONDecodeError, IOError):
            pass
    return {}


def _save_state(session_id: str, state: dict) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    path = _state_file(session_id)
    try:
        with open(path, "w") as fh:
            json.dump(state, fh)
    except IOError:
        pass


# ---------------------------------------------------------------------------
# Content extraction per tool type
# ---------------------------------------------------------------------------
def _collect_strings(obj, depth: int = 0) -> list:
    """Recursively collect all string values from a JSON object."""
    if depth > 10:
        return []
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        result = []
        for v in obj.values():
            result.extend(_collect_strings(v, depth + 1))
        return result
    if isinstance(obj, list):
        result = []
        for item in obj:
            result.extend(_collect_strings(item, depth + 1))
        return result
    return []


def _extract_targets(tool_name: str, tool_input: dict) -> list:
    """Return list of (description, text, kind) tuples to scan.

    kind is "path" (pathlike: file_path / Bash command) or "content"
    (Write/Edit body). path-scope patterns only scan "path" targets.
    """
    targets = []
    seen = set()

    def add(desc: str, text: str, kind: str) -> None:
        if text and (text, kind) not in seen:
            seen.add((text, kind))
            targets.append((desc, text, kind))

    if tool_name == "Bash":
        add("command", tool_input.get("command", ""), "path")

    elif tool_name == "Read":
        add("file_path", tool_input.get("file_path", ""), "path")

    elif tool_name in ("Write", "Edit"):
        add("file_path", tool_input.get("file_path", ""), "path")
        add("content", tool_input.get("content", ""), "content")
        add("content", tool_input.get("new_string", ""), "content")

    elif tool_name == "MultiEdit":
        add("file_path", tool_input.get("file_path", ""), "path")
        edits = tool_input.get("edits", [])
        combined = " ".join(e.get("new_string", "") for e in edits)
        add("content", combined, "content")

    # Secondary sweep: any remaining string fields -> classify "content"
    # (conservative: path-patterns won't scan these; value-patterns will).
    file_path = tool_input.get("file_path", "")
    for text in _collect_strings(tool_input):
        if text == file_path:
            continue  # already added as a pathlike target
        add("tool_input", text, "content")

    return targets


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    # Override hatch.
    if os.environ.get("ENABLE_CERBERUS") == "0":
        sys.exit(0)

    try:
        raw = sys.stdin.read()
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)  # Can't parse — don't block

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    session_id = data.get("session_id", "default")

    # Self-exemption: don't scan edits to this scanner's own source — it
    # necessarily contains pattern literals that would otherwise self-block.
    if tool_name in ("Write", "Edit", "MultiEdit"):
        fp = tool_input.get("file_path", "")
        if fp and os.path.basename(fp) == _SELF_BASENAME:
            sys.exit(0)

    targets = _extract_targets(tool_name, tool_input)
    if not targets:
        sys.exit(0)

    for desc, text, kind in targets:
        for cat_name, pattern, scope in _COMPILED:
            if scope == "path" and kind != "path":
                continue  # path-patterns never scan Write/Edit content
            m = pattern.search(text)
            if m:
                state = _load_state(session_id)
                seen = set(state.get(STATE_KEY, []))
                first_hit = cat_name not in seen
                seen.add(cat_name)
                state[STATE_KEY] = list(seen)
                _save_state(session_id, state)

                if first_hit:
                    print(
                        f"\U0001f6a8 Cerberus blocked: {cat_name} pattern matched in {desc}\n"
                        f"   Tool: {tool_name}\n"
                        f"   Pattern: {cat_name} ({pattern.pattern!r})\n"
                        f"   Override: set ENABLE_CERBERUS=0 to disable (not recommended)",
                        file=sys.stderr,
                    )
                else:
                    print(
                        f"\U0001f6a8 Cerberus blocked: {cat_name} (repeated) — Tool: {tool_name}",
                        file=sys.stderr,
                    )

                sys.exit(2)

    sys.exit(0)


if __name__ == "__main__":
    main()
