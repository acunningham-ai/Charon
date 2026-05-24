#!/usr/bin/env bash
# Cerberus secret-leak prevention hook
# Blocks Claude from accessing files or content matching known secret patterns.
# PreToolUse — matched against Bash|Read|Edit|Write|MultiEdit

set -u

# Locate the Python scanner relative to this script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Pipe stdin directly to the Python scanner.
# Dedup state and per-session tracking live inside the Python layer,
# which reads session_id from the JSON payload.
INPUT=$(cat)
echo "$INPUT" | python3 "${SCRIPT_DIR}/secret-pattern-scan.py"
exit $?
