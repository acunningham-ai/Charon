#!/usr/bin/env python3
"""
PostToolUse hook for Bash: when an SSH command fails with an auth error,
nudge Claude to run the credential recovery script before escalating.

The hook does NOT exfiltrate the credential itself — it just tells Claude
the recovery recipe is available, who to recover for, and what to run.
This keeps creds out of hook telemetry and out of the conversation log
unless Claude explicitly invokes the recovery script in the next turn.

Stdin: PostToolUse JSON with `tool_input.command` and `tool_response`.
Stdout: short context message Claude sees in its next turn.
Exit:   0 always (this hook nudges, never blocks).

## Configuring SSH aliases

Add your SSH host aliases to the `SSH_ALIAS_TO_USER` dict below — they'll
be parsed from `ssh <alias>` commands and used to drive the recovery
suggestion. Without this mapping, the hook can only recognise explicit
`user@host` patterns.
"""
import json
import re
import shlex
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

# SSH host aliases that map to a specific user. Populate during first-run
# from your `~/.ssh/config` or your project CLAUDE.md "Recovery Recipes".
# Example: {"prod-bot": "deploy"}  →  `ssh prod-bot ...` will surface
# `python scripts/recover-ssh-creds.py deploy` on auth failure.
SSH_ALIAS_TO_USER: dict[str, str] = {
    # Add your aliases here, or populate via the first-run wizard
}


SSH_AUTH_PATTERNS = [
    r"Permission denied \(publickey",
    r"Permission denied \(password",
    r"Permission denied, please try again",
    r"Authentication failed",
    r"too many authentication failures",
]


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    tool_input = data.get("tool_input", {}) or {}
    cmd = tool_input.get("command", "") or ""
    if "ssh" not in cmd.lower() and "scp" not in cmd.lower():
        return 0

    response = data.get("tool_response", {})
    output = ""
    if isinstance(response, dict):
        output = " ".join(
            str(response.get(k, "") or "")
            for k in ("output", "stdout", "stderr", "error")
        )
    elif isinstance(response, str):
        output = response
    if not output:
        return 0

    if not any(re.search(p, output, re.I) for p in SSH_AUTH_PATTERNS):
        return 0

    try:
        tokens = shlex.split(cmd, posix=True)
    except ValueError:
        tokens = cmd.split()

    user = None

    # 1. Explicit user@host
    for tok in tokens:
        if tok.startswith("-") or not tok or "@" not in tok:
            continue
        candidate = tok.split("@", 1)[0]
        if candidate and re.match(r"^[A-Za-z0-9_.\-]+$", candidate):
            user = candidate
            break

    # 2. Known SSH alias mapping
    if not user:
        for tok in tokens:
            if tok.lower() in SSH_ALIAS_TO_USER:
                user = SSH_ALIAS_TO_USER[tok.lower()]
                break

    if user:
        print(
            f"[ssh-recovery hook] SSH authentication failed for user `{user}`. "
            f"Per `CLAUDE.md` Recovery Recipes, run "
            f"`python scripts/recover-ssh-creds.py {user}` to retrieve the "
            f"credential before escalating. Only escalate if both the "
            f"history grep and the .secrets fallback come back empty."
        )
    else:
        print(
            "[ssh-recovery hook] SSH authentication failed but the target user "
            "could not be parsed from the command. If you know the user, run "
            "`python scripts/recover-ssh-creds.py <user>`. Otherwise ask the user."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
