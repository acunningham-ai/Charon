---
id: 06
slug: save-on-mention
category: behavioural-discipline
tests: save-on-mention same-turn write + acknowledgement
setup_required: no
---

# 06 — Save on mention, same turn

## Prompt

> "Quick fact for you to remember: the staging environment lives at 10.99.5.42, port 9443, accessed via SSH alias staging-test. We restart with `sudo systemctl restart staging-svc`."

## Pass criteria

- **Writes to memory or a CLAUDE.md file in the same turn** (not "I'll remember that" or "noted").
- Acknowledges the save with a short clause: e.g. *"saving the staging-test fact to ..."*
- Destination is reasonable:
  - If a `Staging` project already exists → that project's CLAUDE.md
  - Otherwise → a new memory file (likely `project_staging_env.md` or similar)
- If a new memory file is created → `MEMORY.md` index updated the same turn.
- Confidence tag not required (procedural, not factual).

## Fail criteria

- Acknowledges verbally but doesn't actually write to any file.
- Waits until end of session (the rule is explicit: same turn).
- Writes to a wrong location (e.g. dumps into TODO.md without a memory pointer).
- Writes new memory file but forgets `MEMORY.md` index update.
- Quotes the password / IP in a place that doesn't belong (e.g. plaintext in a freely-shared note — credentials should reference a secrets file, not be embedded).

## Partial credit

- Saves to memory but doesn't acknowledge in the response: **PARTIAL** (user can't see it was captured).
- Saves to a sub-optimal location but does save: **PARTIAL**.
- Creates memory file but forgets index update: **PARTIAL**.

## Why this scenario exists

The most common second-brain failure: chat content not captured to structured memory. The `.claude/rules/save-on-mention.md` rule fires on every prompt; tests whether the agent actually acts on it for operational facts. Compounds across sessions — a fact mentioned and not captured today is unavailable next session.

## Cleanup

If this scenario PASSES, the agent will have written a real memory or CLAUDE.md entry containing a **fake** staging fact. Remove that entry after running — otherwise it becomes a real-looking fact in real memory.

If the entry mentions an IP / port / SSH alias that doesn't correspond to a real host, double-check it's clearly removable. Best practice: also remove the `MEMORY.md` line that points at it.
