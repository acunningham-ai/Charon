#!/usr/bin/env bash
# Charon scheduled capture wrapper (macOS / Linux).
# Register with cron or launchd — see EMAIL-PROVIDER-SETUP.md §Scheduling.
#
# Per harness convention: scheduled runs should NOT store passwords on disk.
# OAuth providers (M365, Gmail) cache refresh tokens — silent runs work
# after the one-time interactive auth. IMAP uses an app password stored
# in the secrets dir; never embed it in this script.

set -e

# Resolve script dir so cron / launchd can invoke from anywhere
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

mkdir -p state
LOG="$SCRIPT_DIR/state/scheduled-run.log"

{
  echo "=========================================="
  echo "Run started: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "=========================================="
  node fetch-mail.mjs all
  EXITCODE=$?
  echo "Run finished: $(date -u +%Y-%m-%dT%H:%M:%SZ) (exit=$EXITCODE)"
  echo
} >> "$LOG" 2>&1 || true

exit ${EXITCODE:-0}
