#!/usr/bin/env python3
"""
Verdict vocabulary + monitor mode for harness hooks.

Emits structured allow/deny/ask/observe verdicts to a daily JSONL audit log
and returns the *effective* verdict after HARNESS_MODE=monitor downgrade,
so callers can shadow-test new rules without breaking the harness.

Verdicts:
  - allow   : proceed silently (exit 0)
  - deny    : block; stderr explains (exit 2)
  - ask     : block; stderr explains AND invites the user to confirm and retry
              (exit 2). Claude Code's hook protocol has no native "ask" exit —
              semantically this is a deny that signals "you can retry once
              confirmed", and Claude should surface the reason rather than
              route around it.
  - observe : allow + log (exit 0). For shadow-testing rules during their
              first fortnight before promoting to ask/deny.

Monitor mode: set HARNESS_MODE=monitor in the environment to downgrade
every ask/deny to observe. Useful for:
  - Shadow-testing a new rule for a fortnight before promoting.
  - Debugging a hook misbehaving without losing other hook protection.

Audit log: <project>/state/verdict/{YYYY-MM-DD}.jsonl (daily rotation,
matching the _telemetry.py pattern). Append-only.

Fail-silent: any IO error in logging is swallowed. The returned verdict
is correct regardless. The harness must never be broken by audit-logging
failure.

Fail-closed on unknown verdict: typo'd or invalid declared verdicts are
treated as `deny` so they surface loudly rather than silently permitting.
The audit log preserves the original value via a rule tag for debugging.

Concurrent-safe audit-log append via `_jsonl_append.safe_append_line`.

Usage:
    from _verdict import emit_verdict, verdict_to_exit_code
    effective = emit_verdict(
        hook="validate-write-path",
        rule="allowlist-match",
        verdict="allow",
        reason="target matches glob X",
        context={"target": file_path, "glob": matched_glob},
    )
    return verdict_to_exit_code(effective)
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

# Shared safe-append helper (cross-platform file locking). Resilient import:
# if _jsonl_append is missing/broken, fall back to an unlocked write so the
# verdict layer keeps working.
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _jsonl_append import safe_append_line  # noqa: E402
except Exception:
    def safe_append_line(path: Path, line: str) -> bool:  # type: ignore
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as f:
                f.write(line)
            return True
        except Exception:
            return False


ALL_VERDICTS = ("allow", "deny", "ask", "observe")
PRODUCTION_MODE = "production"
MONITOR_MODE = "monitor"
MODE_ENV_VAR = "HARNESS_MODE"
PROJECT_ENV = "CLAUDE_PROJECT_DIR"


def _project_root() -> Path:
    env = os.environ.get(PROJECT_ENV)
    if env:
        return Path(env)
    here = Path(__file__).resolve().parent
    for cand in [here, *here.parents]:
        if (cand / ".claude").is_dir():
            return cand
    return here


def _audit_log_path() -> Path:
    day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return _project_root() / "state" / "verdict" / f"{day}.jsonl"


def current_mode() -> str:
    """Return the active harness mode (production or monitor)."""
    return os.environ.get(MODE_ENV_VAR, PRODUCTION_MODE).lower()


def is_monitor_mode() -> bool:
    return current_mode() == MONITOR_MODE


def emit_verdict(
    hook: str,
    rule: str,
    verdict: str,
    reason: str,
    context: dict = None,
    session_id: str = "",
) -> str:
    """Log a verdict and return the effective verdict.

    In production mode, effective == declared.
    In monitor mode, ask/deny are downgraded to observe (logged, not enforced).

    Never raises. Returns the effective verdict so callers can map to exit
    codes even if audit logging fails.
    """
    if verdict not in ALL_VERDICTS:
        # Fail-closed: unknown verdict is treated as deny so typos and
        # programmer errors surface loudly. Audit log preserves the original
        # value via the rule tag. Security hygiene wins over
        # no-accidental-block.
        rule = f"{rule} [verdict-unknown:{verdict!r}]"
        verdict = "deny"

    mode = current_mode()
    effective = verdict
    if mode == MONITOR_MODE and verdict in ("ask", "deny"):
        effective = "observe"

    try:
        now = datetime.now(timezone.utc)
        line = {
            "ts": now.isoformat(timespec="seconds"),
            "hook": hook,
            "rule": rule,
            "declared": verdict,
            "effective": effective,
            "mode": mode,
            "reason": reason,
            "session_id": session_id or "",
            "context": context or {},
        }
        safe_append_line(
            _audit_log_path(),
            json.dumps(line, ensure_ascii=False) + "\n",
        )
    except Exception:
        pass

    return effective


def verdict_to_exit_code(effective_verdict: str) -> int:
    """Map effective verdict to Claude Code hook exit code.

    allow / observe -> 0 (proceed)
    deny / ask      -> 2 (block; caller should explain via stderr)
    """
    if effective_verdict in ("deny", "ask"):
        return 2
    return 0


def write_ask_stderr(rule: str, reason: str, retry_hint: str = "") -> None:
    """Write a standard 'ask' explanation to stderr.

    Distinguishes 'ask' from 'deny' in the message so the user knows this is
    a confirmation prompt, not a hard block. Caller still returns exit 2.
    """
    msg = (
        f"ASK ({rule}): {reason}\n\n"
        f"This action is not blocked outright -- review and confirm before "
        f"proceeding. "
    )
    if retry_hint:
        msg += f"\n\nIf intentional: {retry_hint}\n"
    else:
        msg += "\n"
    try:
        sys.stderr.write(msg)
    except Exception:
        pass
