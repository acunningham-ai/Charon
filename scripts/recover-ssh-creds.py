#!/usr/bin/env python3
"""Check whether an SSH fallback credential exists in your secrets file.

Source: <secrets-dir>/<service>.json, the ONLY source. <secrets-dir> comes from
scripts/lib/harness_paths.secrets_dir() (HARNESS_SECRETS_DIR, default ~/.secrets).

What changed, and why
---------------------
* Earlier versions also searched ~/.claude/history.jsonl for passwords typed into
  past sessions. That search is gone. Session history is never a credential
  source: a password typed once into a chat is stale on rotation, and searching
  for it teaches the assistant that transcripts are a place to look for secrets.
* Earlier versions PRINTED the credential. That put the value into the
  assistant's context and the session transcript. This script never prints the
  value, on stdout or stderr. It reports only whether the credential exists.

Supply the credential to the tool that needs it without it entering the
conversation, for example an SSH key or agent, or a broker that pipes it into
`ssh` without printing it. Never paste it into a chat.

Exit 0 if the credential exists, 1 if not (escalate to the user), 2 on bad
arguments.

Usage:
  scripts/recover-ssh-creds.py [user] [--service <name>]

  user      defaults to DEFAULT_USER below
  --service secrets filename without .json (default DEFAULT_SERVICE below)

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
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.harness_paths import secrets_dir  # noqa: E402

# Configure these for your environment, or pass via the CLI.
DEFAULT_USER = "deploy"
DEFAULT_SERVICE = "ssh-fallback"

# Both values are echoed in messages, and the service name becomes a file name:
# a closed character set keeps them inert and stops `..` or a path separator from
# pointing the lookup outside the secrets directory.
_NAME_RE = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]{0,63}$")


def _valid_name(value: str) -> bool:
    return bool(_NAME_RE.match(value or "")) and ".." not in value


def credential_exists(secrets_path: Path, service: str, user: str) -> tuple[bool, str]:
    """Return (exists, note). Never returns or logs the credential value.

    `note` is a fixed, value-free string explaining a miss.
    """
    if not secrets_path.is_file():
        return False, "secrets file not found"
    try:
        data = json.loads(secrets_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # Deliberately no exception text: a decode error can quote file content.
        return False, "secrets file unreadable or not valid JSON"
    try:
        value = data[service]["ssh"]["password_fallback"][user]
    except (KeyError, TypeError):
        return False, "no entry for this user"
    if not isinstance(value, str) or not value:
        return False, "entry present but empty or not a string"
    return True, ""


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Report whether an SSH fallback credential exists in the secrets "
                    "file. Never prints the value; never searches session history.")
    ap.add_argument("user", nargs="?", default=DEFAULT_USER,
                    help=f"SSH user (default: {DEFAULT_USER}).")
    ap.add_argument("--service", default=DEFAULT_SERVICE,
                    help=f"Secrets file name without .json (default: {DEFAULT_SERVICE}).")
    args = ap.parse_args()

    if not _valid_name(args.user) or not _valid_name(args.service):
        print("FAILED: user and --service may contain only letters, digits, '_', '.' "
              "and '-' (no '..').", file=sys.stderr)
        return 2

    secrets_path = secrets_dir() / f"{args.service}.json"
    found, note = credential_exists(secrets_path, args.service, args.user)
    if found:
        print(f'FOUND: a credential for user "{args.user}" exists in '
              f"{args.service}.json in your secrets directory (value not shown).")
        print("Supply it to ssh without printing it (an SSH key or agent, or a broker "
              "that pipes it in). Never paste it into the conversation.")
        return 0

    print(f'NOT FOUND: no credential for user "{args.user}" in {args.service}.json '
          f"in your secrets directory ({note}). Escalate to the user. Session history "
          f"is never searched for credentials.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
