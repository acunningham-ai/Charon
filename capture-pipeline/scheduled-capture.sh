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
  # --non-interactive: on silent-auth failure, fetch-mail.mjs writes a
  # REAUTH-NEEDED.flag and exits with code 2 instead of hanging on a
  # device-code prompt nobody is there to answer.
  node fetch-mail.mjs all --non-interactive
  EXITCODE=$?
  echo "Run finished: $(date -u +%Y-%m-%dT%H:%M:%SZ) (exit=$EXITCODE)"
  echo
} >> "$LOG" 2>&1 || true

# Re-auth required (exit code 2): surface via the platform's native notifier.
# macOS uses osascript; Linux uses notify-send if available. Both are no-ops
# if the binary doesn't exist — failure to notify never blocks the run.
if [ "${EXITCODE:-0}" = "2" ]; then
  echo "*** Pipeline halted: re-auth required. Flag file written. ***" >> "$LOG"
  if command -v osascript >/dev/null 2>&1; then
    osascript -e 'display notification "Run: node fetch-mail.mjs auth" with title "Charon capture: re-auth required"' 2>/dev/null || true
  elif command -v notify-send >/dev/null 2>&1; then
    notify-send "Charon capture: re-auth required" "Run: node fetch-mail.mjs auth" 2>/dev/null || true
  fi
fi

exit ${EXITCODE:-0}
