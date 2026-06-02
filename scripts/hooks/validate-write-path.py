#!/usr/bin/env python3
"""
PreToolUse hook: enforce write-path allowlist for UNATTENDED claude -p runs.

Dormant by default. Only activates when the env var
`HARNESS_UNATTENDED_ALLOWLIST` is set to the path of a JSON allowlist file.
That file is set by the wrapper bat / shell script that invokes `claude -p`,
so this hook has zero effect on interactive sessions.

This is the C-3 preventive control from the harness security baseline —
bounds the blast radius of an injection attack on a captured-content read.

**Verdict-layer integration:** This hook is the first adopter of the
verdict vocabulary (`_verdict.py`). Decisions are emitted as structured
verdicts to `<project>/state/verdict/{YYYY-MM-DD}.jsonl` for audit. Exit
codes are unchanged for backwards compatibility; the verdict log is purely
additive observability.

Allowlist file shape:
  {
    "automation": "weekly-checkin",
    "write_globs": [
      "**/07-References/weekly-digest/*.md"
    ]
  }

Behaviour:
  - No env var set                       -> exit 0 (allow). Interactive default.
  - Env var set, file unreadable         -> exit 2 (block). Fail closed.
  - Tool call with no target path        -> exit 0 (allow). Not our business.
  - Target matches any allowlist glob    -> exit 0 (allow).
  - Target matches none                  -> exit 2 (block), explain in stderr.

Exit codes match the Claude Code hook protocol used by deny-destructive.py:
  0 = allow, 2 = block.

This hook's own failures (file I/O, JSON parse error, etc.) fail CLOSED when
the env var is set — we'd rather a scheduled run crash loudly than silently
allow a write outside scope.
"""
import json
import os
import re
import sys
from pathlib import Path

try:
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# Local sibling module — fail-silent if missing so the hook stays operable
# even if _verdict.py is removed or broken.
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _verdict import emit_verdict  # noqa: E402
except Exception:
    def emit_verdict(*args, **kwargs):  # type: ignore
        return kwargs.get("verdict", "allow")

HOOK_NAME = "validate-write-path"
ENV_VAR = "HARNESS_UNATTENDED_ALLOWLIST"


def glob_to_regex(glob: str) -> str:
    g = glob.replace("\\", "/")
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


def matches(glob: str, path: str) -> bool:
    return re.fullmatch(glob_to_regex(glob), path.replace("\\", "/")) is not None


def main() -> int:
    allowlist_path = os.environ.get(ENV_VAR)
    if not allowlist_path:
        # Interactive session — not our gate. No verdict emitted (would be
        # noise: every interactive tool call would log "allow").
        return 0

    try:
        cfg = json.loads(Path(allowlist_path).read_text(encoding="utf-8"))
    except Exception as e:
        reason = f"allowlist unreadable at {allowlist_path} ({type(e).__name__}: {e})"
        emit_verdict(
            hook=HOOK_NAME,
            rule="config-error",
            verdict="deny",
            reason=reason,
            context={"allowlist_path": allowlist_path, "error": str(e)},
        )
        sys.stderr.write(f"BLOCKED by validate-write-path: {reason}. Failing closed.\n")
        return 2

    automation = cfg.get("automation", "<unnamed>")
    write_globs = cfg.get("write_globs") or []
    if not isinstance(write_globs, list) or not write_globs:
        reason = f"allowlist for '{automation}' has no write_globs"
        emit_verdict(
            hook=HOOK_NAME,
            rule="config-empty",
            verdict="deny",
            reason=reason,
            context={"automation": automation, "allowlist_path": allowlist_path},
        )
        sys.stderr.write(f"BLOCKED by validate-write-path: {reason}. Failing closed.\n")
        return 2

    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0  # malformed hook input — not our place to block on this

    tool_input = data.get("tool_input", {}) or {}
    target = (
        tool_input.get("file_path")
        or tool_input.get("notebook_path")
        or ""
    )
    if not target:
        return 0  # not a path-targeted tool call

    target_norm = target.replace("\\", "/")
    for glob in write_globs:
        if matches(glob, target_norm):
            emit_verdict(
                hook=HOOK_NAME,
                rule="allowlist-match",
                verdict="allow",
                reason=f"target matches glob '{glob}'",
                context={
                    "automation": automation,
                    "target": target_norm,
                    "matched_glob": glob,
                    "tool_name": data.get("tool_name", ""),
                },
                session_id=data.get("session_id", ""),
            )
            return 0  # allowed

    emit_verdict(
        hook=HOOK_NAME,
        rule="allowlist-miss",
        verdict="deny",
        reason="target not on allowlist for this unattended run",
        context={
            "automation": automation,
            "target": target_norm,
            "write_globs": write_globs,
            "tool_name": data.get("tool_name", ""),
        },
        session_id=data.get("session_id", ""),
    )

    sys.stderr.write(
        f"BLOCKED by validate-write-path hook (automation='{automation}'): "
        f"target `{target}` is not on the allowlist for this unattended run.\n\n"
        f"Allowed write globs:\n"
    )
    for g in write_globs:
        sys.stderr.write(f"  - {g}\n")
    sys.stderr.write(
        f"\nIf this write is intentional, update the allowlist file at "
        f"{allowlist_path} or run the task interactively.\n"
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
