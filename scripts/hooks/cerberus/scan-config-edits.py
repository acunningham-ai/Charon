#!/usr/bin/env python3
"""
Cerberus scan-config-edits.py  —  PreToolUse(Write|Edit|MultiEdit) hook.

Runs the three Cerberus detection engines against edits to *config / agent-
instruction files* in real time, so a poisoned settings.json hook command, MCP
tool description, or agent-config (.cursorrules / CLAUDE.md / …) is caught at
write time — not only on-demand via /cerberus-vet.

Routing by target file:
  - settings*.json / hooks.json     -> claude_hook_rules.scan_hook_command
  - mcp.json / .mcp.json            -> mcp_tool_rules.scan_tool_description
  - is_agent_instruction_file(path) -> repo_poisoning_rules.scan_content

Verdict (per .claude/rules/verdict-vocabulary.md):
  Findings emit `ask` — you editing your own config is plausibly intentional, so
  this surfaces the reason and invites confirmation rather than hard-blocking.
  SHADOW MODE: while SHADOW=True the declared verdict is downgraded to `observe`
  (logged to the verdict audit log, NOT enforced) for its first fortnight. After
  reviewing state/verdict/*.jsonl for false positives (e.g. via /harness-watch-
  review), flip SHADOW=False to promote to enforcing `ask`.

Discipline:
  - Fail-silent and fast: cheap path gate first; only the matched engine runs.
  - Self-exempts the engine source files + this hook (they carry pattern
    literals that would otherwise self-flag — mirrors secret-pattern-scan.py).
  - Never raises; on any error it allows (exit 0) so the harness is never broken
    by this hook.

Promotion: 2026-06-30 ships SHADOW=True. Review window ends ~2026-07-14.
"""

import json
import os
import sys

# SHIPS IN SHADOW. Log-only: findings go to state/verdict/*.jsonl and nothing is
# blocked. Flip to False to enforce `ask` — but run your own shadow window first.
#
# WHY YOU RUN YOUR OWN WINDOW rather than inheriting a verdict: what counts as a
# false positive here depends on what YOUR config files look like. In the
# reference deployment this hook's whole false-positive class was one shape —
# trusted files that either *are* instruction files by design (agent definitions
# tripping RP-007 "instruction-override" — flagging an agent definition for
# containing instructions is like flagging a lock for having a keyhole) or merely
# *describe* a directive (notes about auto-approve policy tripping RP-005). The
# role/provenance calibration below handles that class. Whether it handles YOURS
# is a question only your own log answers.
#
# TWO THINGS TO KNOW BEFORE PROMOTING:
#
#  1. Judge the window from the last CALIBRATION change, not from install date.
#     Counting fires across a behavioural fix measures a hook that no longer
#     exists. In the reference deployment that distinction was the difference
#     between "12 false positives, kill it" and "2 fires in four weeks, promote".
#
#  2. An enforcing `ask` needs an answer channel or it is a `deny` in disguise.
#     deny-destructive.py ships the confirmation-token channel this relies on;
#     don't promote this hook if you have removed it.
#
# Expect roughly 1-2 fires a month once calibrated. Findings on files OUTSIDE your
# project root are never downgraded — a cloned repo's config is exactly the threat
# this exists for, so a fire there is working as intended, not noise.
SHADOW = True

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

# Resilient imports — if an engine or the verdict module is missing/broken, this
# hook degrades to allow rather than breaking edits.
try:
    from claude_hook_rules import scan_hook_command
except Exception:
    def scan_hook_command(_):
        return []
try:
    from mcp_tool_rules import scan_tool_description
except Exception:
    def scan_tool_description(_):
        return []
try:
    from repo_poisoning_rules import scan_content, is_agent_instruction_file
except Exception:
    def scan_content(_):
        return []

    def is_agent_instruction_file(_):
        return None
try:
    sys.path.insert(0, os.path.dirname(_HERE))  # scripts/hooks
    from _verdict import (emit_fell_open, emit_verdict, verdict_to_exit_code,
                          write_ask_stderr)
except Exception:
    def emit_verdict(*a, **k):
        return k.get("verdict", "allow")

    def emit_fell_open(*a, **k):
        return "allow"

    def verdict_to_exit_code(v):
        return 2 if v in ("deny", "ask") else 0

    def write_ask_stderr(*a, **k):
        pass

# Files whose edits we must NOT scan: the engines themselves + this hook carry
# pattern literals that would self-flag.
_SELF_EXEMPT = {
    "claude_hook_rules.py", "mcp_tool_rules.py", "repo_poisoning_rules.py",
    "scan-config-edits.py", "secret-pattern-scan.py",
}


def _written_text(tool_name: str, tool_input: dict) -> str:
    """The text being written/edited (content / new_string / joined MultiEdit)."""
    parts = []
    if tool_input.get("content"):
        parts.append(str(tool_input["content"]))
    if tool_input.get("new_string"):
        parts.append(str(tool_input["new_string"]))
    for e in tool_input.get("edits", []) or []:
        if isinstance(e, dict) and e.get("new_string"):
            parts.append(str(e["new_string"]))
    return "\n".join(parts)


def _route(relpath: str):
    """Return (engine_fn, rule_family) for the target path, or (None, None)."""
    p = relpath.replace("\\", "/").lower()
    base = os.path.basename(p)
    if base.startswith("settings") and base.endswith(".json"):
        return scan_hook_command, "hook-command"
    if base == "hooks.json":
        return scan_hook_command, "hook-command"
    if base in ("mcp.json", ".mcp.json"):
        return scan_tool_description, "mcp-tool"
    if is_agent_instruction_file(relpath):
        return scan_content, "repo-poison"
    return None, None


# --- Role/provenance calibration (2026-08-10 shadow review) -----------------
# 10 of 12 shadow fires were false positives of one class: a TRUSTED file that
# either *is* an instruction file by design (the Athena / Helios / Hephaestus
# seat definitions tripped RP-007 "instruction-override" — flagging an agent
# definition for containing instructions is like flagging a lock for having a
# keyhole) or merely *describes* a directive (memory notes about auto-approve
# tripped RP-005; a command discussing credential redaction tripped RP-003).
#
# The calibration DOWNGRADES to `observe` — it never drops the finding. And it
# applies ONLY on trusted provenance: on a foreign/cloned config (the real
# threat this hook exists for — RP-001 fired correctly on a repo .cursorrules)
# nothing is downgraded, so an attacker gains nothing by adding doc-register
# phrasing or backticks.
# Rule families that are INHERENT to prose about agent behaviour. An agent
# definition contains role instructions because that is what it is; a memory
# note about auto-approve policy necessarily contains the words. Downgraded
# only inside the trusted tree, and only for these two ids.
EXPECTED_INSTRUCTION_SHAPE = {"RP-005", "RP-007"}

# NEVER downgraded, in any zone. These are never "expected by design", and they
# are the highest-consequence findings the repo-poison engine emits:
#   RP-001 conceal-from-user   RP-003 credential-exfiltration
# A single fire on a legitimate file is an acceptable price; silently
# downgrading either would blind the control that matters most.
NEVER_DOWNGRADE = {"RP-001", "RP-003"}

# Trusted prose/definition artefacts — classified by PATH, not by content, so a
# payload cannot talk its way into this class.
_PROSE_DEFINITION_MARKERS = ("/.claude/agents/", "/.claude/commands/", "/memory/")


def _calibrate(file_path: str, text: str, family: str, rule_id: str):
    """Return a note if this finding should be downgraded to observe, else None.

    Downgrade requires ALL of: trusted provenance (facet A) + a prose/definition
    artefact class (path-derived) + a rule id that is inherent to that class.
    Content never influences the decision, so there is no evasion surface here.
    """
    try:
        sys.path.insert(0, os.path.dirname(_HERE))
        from _provenance import trust_zone
    except Exception:
        return None  # discriminator unavailable → no downgrade (fail-loud)

    try:
        if rule_id in NEVER_DOWNGRADE:
            return None
        if trust_zone(file_path) not in ("harness-own", "vault-authored"):
            return None  # foreign / untrusted / unknown → never downgrade
        if family != "repo-poison" or rule_id not in EXPECTED_INSTRUCTION_SHAPE:
            return None
        p = file_path.replace("\\", "/").lower()
        if any(mk in p for mk in _PROSE_DEFINITION_MARKERS):
            return ("instruction-shape is inherent to a trusted agent/command "
                    "definition or memory note")
        return None
    except Exception:
        return None


def main() -> None:
    try:
        data = json.loads(sys.stdin.read())
    except Exception:
        sys.exit(0)

    tool_name = data.get("tool_name", "")
    tool_input = data.get("tool_input", {}) or {}
    session_id = data.get("session_id", "")
    file_path = tool_input.get("file_path", "") or ""
    if not file_path:
        sys.exit(0)

    if os.path.basename(file_path) in _SELF_EXEMPT:
        sys.exit(0)

    engine, family = _route(file_path)
    if engine is None:
        sys.exit(0)  # not a config/agent file — not our gate

    text = _written_text(tool_name, tool_input)
    if not text:
        sys.exit(0)

    findings = engine(text)
    if not findings:
        sys.exit(0)

    top = findings[0]
    rule_id = top.get("id", family)
    calibration = _calibrate(file_path, text, family, rule_id)
    reason = (
        f"{family} detector flagged this {tool_name} to {os.path.basename(file_path)}: "
        f"{top.get('id')} {top.get('name')} — {top.get('message')} "
        f"({top.get('owasp_llm')}/{top.get('cwe')}). "
        f"Total findings: {len(findings)}."
    )
    declared = "observe" if (SHADOW or calibration) else "ask"
    if calibration:
        reason = f"{reason} [calibrated to observe: {calibration}]"
    effective = emit_verdict(
        hook="cerberus-scan-config-edits",
        rule=rule_id,
        verdict=declared,
        reason=reason,
        context={
            "target": file_path,
            "family": family,
            "tool": tool_name,
            "finding_ids": [f.get("id") for f in findings],
            "shadow": SHADOW,
            "calibrated": calibration or "",
        },
        session_id=session_id,
    )

    if effective == "ask":
        write_ask_stderr(
            rule=rule_id,
            reason=reason,
            retry_hint=(
                "If you are intentionally adding this content, re-issue the edit; "
                "otherwise remove the flagged pattern. Run /cerberus-vet for a full assessment."
            ),
        )
    elif effective == "deny":
        sys.stderr.write(f"BLOCKED (cerberus-scan-config-edits / {rule_id}): {reason}\n")
    # observe / allow -> exit 0 (logged only)

    sys.exit(verdict_to_exit_code(effective))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        # Absolute backstop -- a scanner fault must never block a write.
        # Recorded as a FALL-OPEN, not a plain allow: a gate that has
        # silently stopped evaluating must not look like a gate with
        # nothing to report. Query: jq 'select(.decided == false)'
        try:
            emit_fell_open(hook="cerberus-scan-config-edits", rule="backstop",
                           reason="hook raised; allowing",
                           error=repr(exc))
        except Exception:
            pass
        sys.exit(0)
