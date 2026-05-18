#!/usr/bin/env python
"""Recovery recipe for SSH credentials.

Source order (canonical first):
  1. <secrets-dir>/<service>.json — CANONICAL.
  2. ~/.claude/history.jsonl — LAST FALLBACK ONLY. Stale on rotation.

Per `CLAUDE.md` "Recovery Recipes": history grep is the last fallback
because inline-typed creds go stale on rotation.

Prints credential to stdout. Exits 1 if not found.

Usage:
  python recover-ssh-creds.py [user] [--service <name>]

  user      — defaults to whatever you've nominated as DEFAULT_USER below
  --service — secrets filename (default `<service>.json` in your secrets dir).
              Configure DEFAULT_SERVICE below or pass --service.

Schema expected in the secrets JSON:
  {
    "<service>": {
      "ssh": {
        "password_fallback": {
          "<user>": "<password>"
        }
      }
    }
  }

Called by the assistant when SSH auth fails before escalating.
"""
import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.harness_paths import secrets_dir  # noqa: E402

# Configure these for your environment, or pass via CLI / first-run wizard.
DEFAULT_USER = "deploy"
DEFAULT_SERVICE = "ssh-fallback"


def grep_history(history_path: str, user: str) -> str | None:
    """Search ~/.claude/history.jsonl for prior credentials typed inline.

    Returns the most recent matching credential, or None.
    """
    if not os.path.exists(history_path):
        return None
    try:
        with open(history_path, "r", encoding="utf-8") as f:
            content = f.read()
    except OSError:
        return None

    patterns = [
        rf"{re.escape(user)}.{{0,80}}?(?:password|pwd)\s+(?:is|=|:)\s+([A-Za-z0-9!@#$%^&*]{{6,}})",
        rf"(?:password|pwd)\s+(?:is|=|:)\s+([A-Za-z0-9!@#$%^&*]{{6,}}).{{0,80}}?{re.escape(user)}",
    ]
    candidates = []
    for pat in patterns:
        candidates.extend(re.findall(pat, content, re.IGNORECASE))
    if candidates:
        # history.jsonl is append-only, last match is most recent
        return candidates[-1]
    return None


def read_secrets(secrets_path: str, service: str, user: str) -> str | None:
    """Read credential from the configured secrets JSON file."""
    if not os.path.exists(secrets_path):
        return None
    try:
        with open(secrets_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return None

    # Schema: <service>.ssh.password_fallback.<user>
    return (
        data.get(service, {})
        .get("ssh", {})
        .get("password_fallback", {})
        .get(user)
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("user", nargs="?", default=DEFAULT_USER,
                    help=f"SSH user (default: {DEFAULT_USER}).")
    ap.add_argument("--service", default=DEFAULT_SERVICE,
                    help=f"Service name for secrets file lookup (default: {DEFAULT_SERVICE}.json).")
    args = ap.parse_args()

    secrets_path = str(secrets_dir() / f"{args.service}.json")
    pwd = read_secrets(secrets_path, args.service, args.user)
    if pwd:
        print(pwd)
        print(f"# source: {secrets_path}", file=sys.stderr)
        return 0

    history = os.path.join(os.path.expanduser("~"), ".claude", "history.jsonl")
    pwd = grep_history(history, args.user)
    if pwd:
        print(pwd)
        print(
            "# source: ~/.claude/history.jsonl (LAST FALLBACK — may be stale; "
            "rotate via secrets file if auth fails)",
            file=sys.stderr,
        )
        return 0

    print(
        f'FAILED: no credential for user "{args.user}" in '
        f"{secrets_path} or ~/.claude/history.jsonl. Escalate to the user.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
