#!/usr/bin/env python3
"""
PreToolUse hook: high-stakes phase-gate (E2(b), superpowers borrow → SH track).

Requires an explicit confirmation before a write lands on a HIGH-STAKES artefact
(e.g. publishing a policy, board or audit-committee papers, a governance
sign-off record). The artefacts whose mistakes are most expensive get a deliberate
"are you sure this is the final, signed-off version?" beat — the verdict layer's
`ask` semantics — instead of sailing through like a routine note edit.

Built on the verdict vocabulary (`_verdict.py`, allow/deny/ask/observe). Ships
SHADOW-FIRST per the shadow-before-enforce discipline (verdict-vocabulary.md):
for its first fortnight it emits `observe` (logs only, never blocks) so the audit
log shows how often it WOULD fire and on what — `/harness-watch-review` then
decides promotion to enforcing `ask` (flip SHADOW=False), per >2-FP-kills-it.

Config-driven (no hardcoded vault paths): reads `high_stakes_globs` from
`scripts/hooks/phase-gate-config.json` beside this hook. An EMPTY list means the
hook never fires — the safe default, and it ships empty. Populate it with your
own high-stakes paths to switch the gate on.

Behaviour:
  - Config missing / unreadable / empty globs  → exit 0 (allow). Nothing to gate.
  - Tool is not a write (no file_path)         → exit 0 (allow). Not our gate.
  - Target matches no high-stakes glob         → exit 0 (allow). No verdict (no noise).
  - Target matches a high-stakes glob:
      · SHADOW (config "shadow": true, default) → emit `observe` (logs the would-be
        `ask`), exit 0. Never blocks during the shadow window.
      · ENFORCING ("shadow": false)            → emit `ask`, explain on stderr, exit 2.

Fail-silent on ALL errors: a phase-gate that crashes must never block your
interactive edits. Every failure path returns exit 0.
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

# Verdict layer — fail-silent if absent so the hook stays operable.
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _verdict import emit_verdict, write_ask_stderr  # noqa: E402
except Exception:
    def emit_verdict(*args, **kwargs):  # type: ignore
        return kwargs.get("verdict", "allow")

    def write_ask_stderr(*args, **kwargs):  # type: ignore
        return None

HOOK_NAME = "phase-gate"
CONFIG_PATH = Path(__file__).resolve().parent / "phase-gate-config.json"
WRITE_TOOLS = {"Write", "Edit", "NotebookEdit", "MultiEdit"}


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
    try:
        return re.fullmatch(glob_to_regex(glob), path.replace("\\", "/")) is not None
    except Exception:
        return False


def main() -> int:
    # Load config. Absent/unreadable/empty → nothing to gate (fail-open: this is a
    # convenience gate on the user's OWN edits, not a security boundary — a broken
    # config must not block interactive work).
    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        return 0
    globs = cfg.get("high_stakes_globs") or []
    if not isinstance(globs, list) or not globs:
        return 0
    shadow = cfg.get("shadow", True)  # default to shadow; enforcing is an explicit opt-in

    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0

    if data.get("tool_name") not in WRITE_TOOLS:
        return 0
    tool_input = data.get("tool_input", {}) or {}
    target = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if not target:
        return 0
    target_norm = target.replace("\\", "/")

    matched = next((g for g in globs if isinstance(g, str) and matches(g, target_norm)), None)
    if not matched:
        return 0  # not a high-stakes artefact — no verdict, no noise

    # DRAFT EXCLUSION (2026-08-10 shadow review). The gate asks "is this the
    # final, signed-off version?" — a question that is meaningless mid-draft.
    # In the reference deployment it fired 17× on ONE agenda and 9× on another
    # while they were being iterated: 77 real fires, almost all on drafts. Asking
    # someone 17 times whether their draft is final is how a gate gets switched off.
    # Skipping drafts is what makes this rule promotable at all.
    # Fail-safe: if the discriminator is unavailable, nothing is excluded and
    # the gate behaves exactly as before.
    if cfg.get("exclude_drafts", True):
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from _provenance import artefact_role
            if artefact_role(target_norm) == "draft":
                return 0
        except Exception:
            pass

    reason = (
        f"write targets a high-stakes artefact (matched '{matched}') — "
        f"confirm this is the final, signed-off version before it lands"
    )
    ctx = {
        "target": target_norm,
        "matched_glob": matched,
        "tool_name": data.get("tool_name", ""),
        "would_emit": "ask",
    }
    sid = data.get("session_id", "")

    if shadow:
        # Shadow window: log the would-be `ask` as `observe`; never block.
        emit_verdict(hook=HOOK_NAME, rule="high-stakes-write-shadow",
                     verdict="observe", reason=f"[SHADOW] {reason}",
                     context=ctx, session_id=sid)
        return 0

    # Enforcing: ask for confirmation.
    emit_verdict(hook=HOOK_NAME, rule="high-stakes-write",
                 verdict="ask", reason=reason, context=ctx, session_id=sid)
    write_ask_stderr(
        rule="phase-gate / high-stakes-write",
        reason=reason,
        retry_hint=(
            f"re-issue the write to `{target}` once you've confirmed it's the "
            f"finalised version (or move the gate's path out of phase-gate-config.json)."
        ),
    )
    return 2


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Absolute backstop — never block an edit because the gate errored.
        sys.exit(0)
