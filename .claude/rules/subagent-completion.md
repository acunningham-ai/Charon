---
always: true
keywords:
  - "subagent"
  - "sub-agent"
  - "agent finished"
  - "agent completed"
  - "task-notification"
  - "delegate"
  - "fan out"
---

# A child run finishing is not the task finishing

When a sub-agent reports back, that ends **one child run** — not necessarily the request the
user made. Compare the result with the outcome the user asked for before deciding anything is
done. Reviews, failed checks and other fixable blockers inside the scope mean more work, not a
report. Escalate a blocker only when progress needs new authority from the user or a decision
nobody here can make. (The pattern was borrowed from the OpenClaw agent framework's sub-agent
completion instructions and re-written in our own words.)

## Why this rule targets the PARENT

The failure mode is not a child over-claiming. It is **the parent accepting a child's completion
as task-completion** — relaying a sub-agent's report and stopping, when the report answered part
of the question, answered a different question, or surfaced a fixable blocker.

## Apply on every `<task-notification>`

1. **Re-read what the user actually asked**, not what the agent was briefed to do. A brief can be
   narrower than the request, or built on a premise the agent then corrected.
2. **Diff the result against the request.** Name what is still outstanding.
3. **A fixable in-scope blocker means keep working** — spawn a follow-up, or do it directly.
   Escalate only when it needs the user's authority (a confirm token, a decision that is theirs)
   or an external answer nobody here has.
4. **Do not report completion on partial work.** If part of the scope was blocked, finish
   everything else and say explicitly what was left and why.
5. **A sub-agent's claim is not evidence.** Where it asserts something about *your* code,
   config or vault, verify it against the filesystem before relaying it. A one-command check
   catches most wrong or misattributed claims.

## Also true of the child

Agent definitions under `.claude/agents/` should carry the same instruction so a child does not
declare done on a partial result. When authoring or editing an agent, include it.

## See also

- `confidence-tags.md` — a relayed claim you have not checked is 🟡 at best, never 🟢
- `no-assumptions.md` — an unverified sub-agent claim is an assumption
