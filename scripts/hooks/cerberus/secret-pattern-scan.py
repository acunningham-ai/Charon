#!/usr/bin/env python3
"""
Cerberus secret-pattern-scan.py
Shared regex engine used by block-secrets.sh.
Run as: echo '<json>' | python3 hooks/secret-pattern-scan.py
Exits 2 with stderr message on a match. Exits 0 if clean.
"""

import json
import os
import re
import sys
from datetime import datetime

# ---------------------------------------------------------------------------
# Pattern registry — (category_name, regex_string)
# Order: most specific first to reduce false-positive overlap.
# ---------------------------------------------------------------------------
SECRET_PATTERNS = [
    # File paths that should never be touched
    ("env-file", r"\.env($|\.)"),
    ("pem-cert", r"\.pem$"),
    ("key-file", r"\.key$"),
    ("id-rsa", r"id_rsa"),
    ("id-ed25519", r"id_ed25519"),
    ("p12-cert", r"\.p12$"),
    ("pfx-cert", r"\.pfx$"),
    ("jks-keystore", r"\.jks$"),

    # Credential directories
    ("aws-credentials-dir", r"\.aws/credentials"),
    ("ssh-dir", r"\.ssh/"),
    ("gcloud-dir", r"\.gcloud/"),
    ("kube-config", r"\.kube/config"),
    ("gnupg-dir", r"\.gnupg/"),

    # AWS access keys
    ("aws-akia-key", r"AKIA[0-9A-Z]{16}"),
    ("aws-asia-key", r"ASIA[0-9A-Z]{16}"),
    ("aws-aroa-key", r"AROA[0-9A-Z]{16}"),

    # GitHub tokens
    ("github-pat", r"github_pat_[a-zA-Z0-9]{82}"),
    ("github-ghp", r"ghp_[a-zA-Z0-9]{36}"),
    ("github-gho", r"gho_[a-zA-Z0-9]{36}"),
    ("github-ghs", r"ghs_[a-zA-Z0-9]{36}"),

    # Anthropic / Claude keys — check before generic sk- pattern
    ("anthropic-key-api", r"sk-ant-api[0-9]{2}"),
    ("anthropic-key", r"sk-ant-[a-zA-Z0-9\-]{90,}"),

    # OpenAI keys
    ("openai-proj-key", r"sk-proj-[a-zA-Z0-9\-]{80,}"),
    ("openai-key", r"sk-[a-zA-Z0-9]{48}"),

    # Slack tokens
    ("slack-bot-token", r"xoxb-[0-9]{11}-[0-9]{11}-[a-zA-Z0-9]{24}"),
    ("slack-user-token", r"xoxp-"),

    # Private keys (PEM headers)
    ("private-key-header", r"-----BEGIN (RSA |EC |DSA |OPENSSH |PGP )?PRIVATE KEY"),

    # JWT
    ("jwt-token", r"eyJ[A-Za-z0-9_-]{20,}\.eyJ[A-Za-z0-9_-]{20,}"),

    # Bash commands that read .env files
    ("bash-cat-env", r"cat.*\.env"),
    ("bash-head-env", r"head.*\.env"),
    ("bash-tail-env", r"tail.*\.env"),
    ("bash-less-env", r"less.*\.env"),
    ("bash-grep-env", r"grep.*\.env"),
]

_COMPILED = [(name, re.compile(pattern)) for name, pattern in SECRET_PATTERNS]

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
def _collect_strings(obj, depth: int = 0) -> list[str]:
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


def _extract_targets(tool_name: str, tool_input: dict) -> list[tuple[str, str]]:
    """Return list of (description, text) pairs to scan.

    Primary extraction is tool-specific (for clean labeling). A secondary
    sweep of all string values in tool_input catches any field the tool
    exposes (e.g. a 'content' field on a Read call in tests, or future
    tool schema changes).
    """
    targets: list[tuple[str, str]] = []
    seen: set[str] = set()

    def add(desc: str, text: str) -> None:
        if text and text not in seen:
            seen.add(text)
            targets.append((desc, text))

    if tool_name == "Bash":
        add("command", tool_input.get("command", ""))

    elif tool_name == "Read":
        add("file_path", tool_input.get("file_path", ""))

    elif tool_name in ("Write", "Edit"):
        add("file_path", tool_input.get("file_path", ""))
        add("content", tool_input.get("content", ""))
        add("content", tool_input.get("new_string", ""))

    elif tool_name == "MultiEdit":
        add("file_path", tool_input.get("file_path", ""))
        edits = tool_input.get("edits", [])
        combined = " ".join(e.get("new_string", "") for e in edits)
        add("content", combined)

    # Secondary sweep: catch any remaining string fields not covered above
    for text in _collect_strings(tool_input):
        add("tool_input", text)

    return targets


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    try:
        raw = sys.stdin.read()
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        sys.exit(0)  # Can't parse — don't block

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {})
    session_id = data.get("session_id", "default")

    targets = _extract_targets(tool_name, tool_input)
    if not targets:
        sys.exit(0)

    # Check every target against every pattern
    for desc, text in targets:
        for cat_name, pattern in _COMPILED:
            m = pattern.search(text)
            if m:
                # Load dedup state
                state = _load_state(session_id)
                seen = set(state.get(STATE_KEY, []))
                first_hit = cat_name not in seen

                # Always update state
                seen.add(cat_name)
                state[STATE_KEY] = list(seen)
                _save_state(session_id, state)

                # Verbose on first hit, terse on subsequent — but ALWAYS exit 2
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
