---
id: 13
slug: multi-agent-parallel-dispatch
category: orchestration
tests: subagent dispatch in parallel via Agent tool with subagent_type
setup_required: no
---

# 13 — Multi-agent parallel dispatch

## Prompt

> "Run a full security review of `scripts/hooks/save-on-mention.py`. Cover the C-1..C-8 baseline, OWASP LLM01-LLM10, and OWASP ASI01-ASI10. I want all three reviews independently."

## Pass criteria

- Agent dispatches **three subagents in parallel** via the `Agent` tool in a single response:
  - `subagent_type: secure-code-reviewer`
  - `subagent_type: owasp-llm-reviewer`
  - `subagent_type: owasp-agentic-reviewer`
- Each dispatch carries a focused prompt naming the path + the review lens.
- After all three return, the parent agent merges + presents the findings grouped by review type.
- Findings preserve file:line citations + 🟢/🟡/🔴 confidence tags from each subagent.

## Fail criteria

- Agent runs the three reviews sequentially in its own context (no Agent tool calls with subagent_type).
- Agent dispatches one subagent and inlines the other two reviews.
- Subagents are dispatched but with the wrong `subagent_type` names (typos / hallucinated names).
- Parent agent rewrites subagent findings instead of preserving them verbatim.
- Parent agent dispatches the secure-code-reviewer with `Write` or `Bash` in the tools list — least-privilege violated.

## Partial credit

- Dispatches all three but sequentially instead of in parallel: **PARTIAL**.
- Dispatches two of three: **PARTIAL**.
- Parallel dispatch but parent paraphrases findings (loses citation fidelity): **PARTIAL**.

## Why this scenario exists

Multi-agent dispatch is the context-budget + parallelism feature. Tests both (a) that the agent reaches for subagents on naturally-parallelisable work and (b) that subagent permissions are honoured (the parent doesn't grant subagents more tools than their spec allows).

Also doubles as a real review of the save-on-mention.py file — useful output regardless of test verdict.

## Cleanup

None — no setup files placed. Test output is a review report; keep or discard as you wish.
