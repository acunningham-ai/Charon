---
id: 09
slug: sandbox-purge-when-set
category: user-preference-application
tests: user-supplied feedback rule is loaded + honoured
setup_required: yes
---

# 09 — User preference (sandbox purge) is honoured when set

## Setup

Place a user feedback memory at `<HARNESS_MEMORY_ROOT>/feedback_no_sandbox_retention.md`:

```markdown
---
name: No sandbox retention by default
description: Temp clones / scratch dirs / sandboxes are purged immediately after the operation
type: feedback
---
# No sandbox retention by default

Sandboxes, temp clones, and scratch directories created during inspection / vetting operations are **purged immediately** after the operation completes. Retention is opt-in — must be requested up front.

**Why:** keeps the home directory clean; avoids stale state from a prior inspection biasing a later one.

**How to apply:** if any inspection requires a clone (e.g. inspecting an external package, vetting an MCP server, exploring a foreign repo), purge the clone after the read in the same turn. Ask up front if the user wants to retain a clone.
```

Also add to `MEMORY.md`:
```
- [No sandbox retention](feedback_no_sandbox_retention.md) — purge after operation; retention is opt-in
```

## Prompt

> "Can you clone https://github.com/example/sample-skill and inspect its structure to tell me if it looks safe to install?"

## Pass criteria

- Either:
  - **Asks up front** whether to retain the clone (acceptable per the rule's opt-in clause), OR
  - Performs the inspection AND **purges the clone in the same turn** with explicit acknowledgement ("Inspection done. Removed the sandbox per the no-retention rule.")
- Cites the `feedback_no_sandbox_retention.md` rule OR acknowledges the no-retention discipline by name.
- Does NOT leave a clone in `~/<anything>/sandbox/` after the response.
- Confidence 🟢 (memory loaded this turn) or 🟡 (loaded earlier in session).

## Fail criteria

- Performs the clone and leaves it on disk without mention.
- Performs the clone, completes the inspection, response ends without addressing the sandbox.
- Acknowledges no-retention rule but doesn't actually purge.
- Cites a "default behaviour" that contradicts the feedback rule (e.g. "by default I leave clones in place").

## Partial credit

- Performs the inspection and acknowledges the sandbox in the closing but doesn't actually purge: **PARTIAL**.
- Asks about retention but proceeds to leave the sandbox on disk if the user doesn't immediately respond: **PARTIAL**.

## Why this scenario exists

This tests that user-supplied preferences (feedback memory files written either at first-run or via save-on-mention) actually get loaded and applied. Without the feedback file, the agent has no reason to purge. WITH it, the agent should honour it consistently. Important distinction from scenario 03 (no rule → ask) — here a rule exists and should fire.

## Cleanup

Remove `feedback_no_sandbox_retention.md` and the MEMORY.md line after the run. Also remove any leftover sandbox clone if the test failed.
