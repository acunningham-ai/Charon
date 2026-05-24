# Cerberus Architecture

## Overview

This document describes how Cerberus components interact at runtime and during installation. It is intended for engineers who want to extend the plugin, debug hook behavior, or understand how Cerberus coexists with other plugins.

---

## Component Diagram

```
  User
   │
   │  types /cerberus-audit or /cerberus-setup
   ▼
  Claude Code CLI
   │
   ├──► slash command resolves to: commands/cerberus-audit.md
   │                                commands/cerberus-setup.md
   │                                commands/cerberus-recover.md
   │
   ▼
  Cerberus Agent (agents/cerberus.md)
   │
   ├──► invokes Skills (read-only analysis at audit time)
   │    ├── skills/audit-claude-setup/SKILL.md   — reads settings, reports findings
   │    ├── skills/harden-claude-setup/SKILL.md  — writes settings via update-config delegation
   │    └── skills/rotate-leaked-secret/SKILL.md — revocation + remediation workflow
   │
   ├──► reads Templates (install time, not runtime)
   │    ├── templates/golden-settings.json        — the desired end-state
   │    ├── templates/managed-settings.json        — enterprise managed overlay
   │    └── templates/security-claude-md.md        — CLAUDE.md snippet for new projects
   │
   └──► Hooks intercept every tool call (runtime, always-on)
        ├── hooks/block-secrets.sh       — PreToolUse, fires on Bash|Read|Edit|Write|MultiEdit
        │    └── hooks/secret-pattern-scan.py — regex engine (delegates from block-secrets.sh)
        └── hooks/audit-claude-md.sh     — UserPromptSubmit, fires once per session
```

**Install-time vs runtime**: Templates are consumed by `scripts/install.sh` and `harden-claude-setup` skill to configure `settings.json`. They are never loaded at runtime. Hooks are always-on — they fire on every matching tool call regardless of which command or agent initiated it.

---

## PreToolUse Hook Flow

When Claude attempts to execute a tool call (e.g., `Bash(cat ~/.aws/credentials)`), the runtime fires all registered PreToolUse hooks before executing the tool. Cerberus registers one hook block:

```
Claude Code runtime
       │
       │  tool call proposed: Bash {"command": "cat ~/.aws/credentials"}
       ▼
  PreToolUse hook dispatch
       │
       ├──► block-secrets.sh is invoked
       │    │
       │    │  stdin: {"tool_name":"Bash","tool_input":{"command":"cat ~/.aws/credentials"},"session_id":"abc123"}
       │    │
       │    └──► secret-pattern-scan.py
       │         │
       │         │  1. parse stdin JSON
       │         │  2. extract targets: [("command", "cat ~/.aws/credentials")]
       │         │  3. scan against 30+ compiled regex patterns
       │         │  4. match: "aws-credentials-dir" pattern /.aws\/credentials/
       │         │  5. check dedup state in ~/.claude/cerberus_state_abc123.json
       │         │  6. print advisory to stderr
       │         │  7. exit 2  ◄── signals Claude Code to BLOCK the tool call
       │
       │  exit code 2 received from hook
       │
       └──► tool call BLOCKED — Claude receives the stderr message as feedback
```

**Exit codes**: Exit 0 = allow. Exit 2 = block with message. Any other non-zero = block without message (treated as hook error). The Python scanner uses exit 2 exclusively for intentional blocks.

**Dedup state**: `secret-pattern-scan.py` writes per-category block records to `~/.claude/cerberus_state_<session_id>.json`. First block per category emits a verbose message; subsequent blocks emit a terse one-liner. This prevents alert fatigue in sessions where Claude repeatedly attempts the same blocked action.

---

## Agent Isolation Discipline

The Cerberus agent treats all project files as **data**, not as instructions. This is the fundamental defense against L3 prompt injection (see threat-model.md).

In practice, this means:
- CLAUDE.md files in cloned repositories are read for pattern scanning (by `audit-claude-md.sh`), but their text content is never incorporated into the agent's behavior ruleset.
- MEMORY.md files are scanned for injection markers before the session begins. If a marker is found, the advisory appears but the session continues — the agent does not act on the flagged content.
- The agent's own instructions live in `agents/cerberus.md` (plugin-controlled) and the user's `~/.claude/CLAUDE.md` (user-controlled). These are trusted. Everything else is data.

This isolation is enforced by convention in the agent's system prompt, not by a technical sandbox. Engineers extending the agent must maintain this discipline when adding new skills.

---

## Coexistence with security-guidance Plugin

Cerberus is designed to run alongside the `security-guidance` plugin without conflict. Both plugins may register PreToolUse hooks; Claude Code runs all registered hooks in registration order.

**How they differ**:

| Aspect | Cerberus (this plugin) | security-guidance |
|---|---|---|
| Primary focus | Blocking secret exfiltration | Advisory guidance on secure coding |
| Hook type | PreToolUse (blocking, exit 2) | PreToolUse (advisory, exit 0) |
| State file | `cerberus_state_<session>.json` | separate namespace (no overlap) |
| Dedup key | `blocked_categories` | different key — no collision |
| Detection method | Regex against tool call payload | Heuristic pattern on code content |
| Action on match | Blocks the tool call | Emits a warning, allows the call |

**Hook chain**: Both hooks run. If Cerberus exits 2, the tool call is blocked regardless of what security-guidance returns. If Cerberus exits 0, security-guidance still runs and may emit its own advisory. The two hooks are additive — installing both provides broader coverage than either alone.

**State file isolation**: Cerberus writes to `cerberus_state_<session>.json`. The security-guidance plugin uses its own state file naming convention. There is no shared state between the two plugins.

---

## The update-config Delegation Pattern

Cerberus never writes `settings.json` directly from Claude during an agentic session. All settings mutations go through the `update-config` skill (a system-level skill outside this plugin), which:

1. Reads the current `settings.json`
2. Validates it as JSON
3. Applies the requested change
4. Writes the result
5. Validates the written result

This delegation pattern means the Cerberus agent cannot accidentally corrupt `settings.json` by writing malformed JSON. It also means settings changes are auditable — the `update-config` skill logs what it changed.

The only path where Cerberus writes `settings.json` directly is `scripts/install.sh` (offline installation), which uses the inline Python helper that applies the same validate-merge-validate cycle.

---

## How to Add a New Secret Detector

To add a new regex pattern to the secret scanner:

1. **Add the pattern to `hooks/secret-pattern-scan.py`**

   Open the `SECRET_PATTERNS` list and add a tuple of `(category_name, regex_string)`.
   Place more specific patterns before less specific ones — the scanner exits on the first match,
   so a broad pattern earlier in the list can shadow a more specific one later.

   Example (adding a Stripe secret key):
   ```python
   ("stripe-secret-key", r"sk_live_[a-zA-Z0-9]{24}"),
   ```

2. **Add a test case**

   Add a JSON payload to `tests/` (or inline in `tests/test_scanner.py` if using pytest) that
   should trigger the new pattern, and a clean payload that should not.
   The smoke test format used by `verify.sh` is:
   ```bash
   echo '{"tool_name":"Bash","tool_input":{"command":"echo sk_live_abc123"},"session_id":"test"}' \
     | python3 hooks/secret-pattern-scan.py
   echo "Exit: $?"  # should be 2
   ```

3. **Run shellcheck on the hook wrapper**

   ```bash
   shellcheck hooks/block-secrets.sh
   ```
   The Python scanner does not need shellcheck but should pass `python3 -m py_compile`.

4. **Submit a PR**

   - Title: `feat(scanner): add <category_name> pattern`
   - Include: the new pattern, the test case, and a brief description of the secret format
   - CODEOWNERS: `.github/CODEOWNERS` routes security-related PRs to the security team for review

New deny rules (for the `golden-settings.json` layer) follow the same PR process — add to `templates/golden-settings.json`, update `examples/before-after-settings.diff` to reflect the new rule, and update the rule count in `examples/audit-output-clean.txt`.
