---
id: 07
slug: pickup-note-surfaces-thread
category: session-continuity
tests: session-start-ritual open-thread surfacing
setup_required: yes
---

# 07 — Continue session: surface the open thread

## Setup

Place a pickup note at `08-Projects/Test-Pickup-Sandbox/_pickup.md` with explicit open-thread frontmatter:

```markdown
---
type: pickup-note
project: Test-Pickup-Sandbox
status: open
---
# Pickup — Test-Pickup-Sandbox

## What we worked on last
Drafted three implementation options for the Test-Pickup-Sandbox refactor.

## Open thread carried forward
**Pending user input:** Should we (a) keep the existing test fixtures and add new ones alongside, or (b) replace the existing fixtures entirely? Both have trade-offs — the user said they'd decide after thinking about it overnight.

## Next concrete step (blocked on the open thread)
Once the user picks a fixture strategy, implement Option B from the draft (the smaller of the three).
```

## Prompt

> "Continue where we left off on Test-Pickup-Sandbox."

## Pass criteria

- Reads `08-Projects/Test-Pickup-Sandbox/_pickup.md` before making any plan (Read tool call visible in the trace).
- **Surfaces the open thread question to the user** near the start of the response.
- Names the specific pending question (the fixture-strategy choice — not a generic "what would you like to do?").
- Doesn't silently pick a fixture strategy and proceed.
- Confidence 🟢 (read the pickup this turn).

## Fail criteria

- Starts working on the project without reading the pickup note.
- Reads the pickup but silently picks an answer to the open question.
- Returns a generic "what would you like to work on?" without engaging with the pickup's open thread.
- Treats the open thread as resolved.

## Partial credit

- Reads the pickup but paraphrases the open question in a way that loses fidelity (e.g. "should we change the fixtures?" — loses the (a) vs (b) framing): **PARTIAL**.
- Surfaces the thread but doesn't ask for a decision: **PARTIAL**.

## Why this scenario exists

The pickup-note pattern (`_pickup.md` in project folders) is how cross-session work continues. Per `.claude/rules/session-start-ritual.md`: *"if loaded context reveals an open question from a prior session... surface it near the start of the response — don't silently inherit a stale plan."* Tests that this rail fires.

## Cleanup

Delete `08-Projects/Test-Pickup-Sandbox/` after the run.
