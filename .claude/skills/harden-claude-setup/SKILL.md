---
name: harden-claude-setup
description: "Interactive guided hardening of a Claude Code installation, applied after an audit. Use when you want to fix security findings, apply deny rules, configure hooks, enable bypass protection, or interactively remediate a Cerberus audit report. Trigger on: 'harden my claude setup', 'fix audit findings', 'apply security fixes', 'add deny rules', 'enable bypass protection', 'configure hooks', 'remediate findings', 'run hardening', 'cerberus harden'."
---

# harden-claude-setup

## Purpose

Walks through each Critical or Important finding from a `audit-claude-setup` report and interactively applies fixes. All settings mutations are delegated to the `update-config` skill — this skill never writes to settings files directly.

## Prerequisites

Run `audit-claude-setup` first and have the report available. This skill operates on the findings from that report. If you don't have a report, say so and the user can run `/audit-claude-setup` first.

## Key Constraint

**No direct writes.** This skill never modifies `~/.claude/settings.json` or any other settings file directly. Every change is delegated to the `update-config` skill. This ensures changes are applied correctly, are validated, and are reversible via the same tooling that created them.

---

## Phase 1 — Work Through Each Finding

For each **Critical** or **Important** finding in the audit report, in order (Critical first):

### Per-finding process

**a. Show the exact change needed**

Present the required change in diff format, for example:

```diff
// ~/.claude/settings.json
  "permissions": {
    "deny": [
-     // (missing)
+     "Read(**/.env)",
+     "Read(**/.env.*)"
    ]
  }
```

**b. Explain the risk in one sentence**

State clearly why this finding matters. Example: "Without this deny rule, Claude can read your .env file and expose API keys in the conversation transcript."

**c. Ask for confirmation**

Ask: "Apply this change? (yes/skip)"

Wait for the user's response before proceeding to the next finding.

**d. If yes — delegate to update-config**

Instruct the AI to invoke the `update-config` skill to apply the change. Do **not** write to `~/.claude/settings.json` directly. Pass the specific key path and value to `update-config`.

Example invocation pattern:
> "Invoke the update-config skill to add `Read(**/.env)` to the deny rules array in `~/.claude/settings.json`."

**e. If skip — note and continue**

Record the finding as skipped. If the skipped finding is **Critical**, flag it again at the end of the session with a warning that it remains unaddressed.

---

## Phase 2 — Verify Changes

After processing all findings, re-run the full audit:

> "Run `audit-claude-setup` now to verify all applied changes took effect."

Compare the new report against the original. For each finding that was applied:
- Confirm it no longer appears in the new report.
- If it still appears, note that the `update-config` application may not have saved correctly, and ask the user to check.

---

## Phase 3 — Final Checklist

Run through these four verification steps manually with the user. Confirm each one passes before moving to the next.

**Step 1 — Managed settings visible**

```
/status
```

Confirm the output shows managed settings if the user is in an enterprise environment. If managed settings are expected but not shown, note it as a follow-up item.

**Step 2 — Deny rules listed**

```
/permissions
```

Confirm that the deny rules section lists the expected baseline rules from the audit. If rules are present in the JSON but not shown in `/permissions`, the file may not have been reloaded — restart Claude Code and re-check.

**Step 3 — Settings JSON is valid**

```bash
python3 -m json.tool ~/.claude/settings.json
```

This must exit with code 0 and produce formatted JSON output. A parse error here means the config file is broken and Claude Code is likely ignoring it. If this fails, invoke `update-config` to inspect and repair the file.

**Step 4 — .env refusal test**

Ask Claude (in a new conversation or using a test prompt):

> "Can you show me the contents of my .env file?"

Claude should decline. If Claude reads and returns the file content, the deny rules are not active. Check that the rules are in the correct settings layer (user-level, not just project-level).

---

## Phase 4 — Session Report

Print a final summary:

```
Hardening session complete.

X of Y findings fixed.

Remaining findings:
- [List each unfixed finding with its severity]

[If all fixed]: No remaining Critical or Important findings. Run /audit-claude-setup periodically to maintain posture.

[If Critical remain]: WARNING: X Critical findings remain unaddressed. Run /harden-claude-setup again or address these manually before using Claude Code in sensitive environments.
```

If any Critical findings remain unresolved, end with a clear call to action rather than marking the session complete.
