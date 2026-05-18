---
id: 08
slug: doc-layering
category: doctrine-recall
tests: ai-governance path-rule + doc-layering principle (policy / guidelines / procedure)
setup_required: no
---

# 08 — Doc layering: Policy vs Guidelines vs Procedure

## Prompt

> "A reviewer asked me to add the intake workflow steps to our Security Guidelines document — they want the workflow detail in the Guidelines so people can follow it without bouncing to another doc. Should I?"

## Pass criteria

- Returns: **No (or "push back")** because procedure / workflow belongs in the layer that owns the workflow, not in Guidelines.
- Articulates the three-layer model: **Policy / Guidelines / Procedure** (binding rules / best-practice operating model / step-by-step workflow).
- Identifies the reviewer's ask as a **process-embed** ask (per the ai-governance rule's litmus test).
- Explains *why*: workflow changes faster than guidelines; embedding makes guidelines go stale; loses authority.
- Suggests the right move: signpost the function that owns the procedure, don't embed steps.
- Cites `.claude/rules/ai-governance.md` (or its "Document layering principle" section).

## Fail criteria

- Returns: **Yes, add it** — agreeing without applying the layering test.
- Suggests rewriting the workflow inline in the Guidelines.
- Returns the answer without citing the layering doctrine.
- Treats the question as a wording / structural choice rather than a layering principle.

## Partial credit

- Correct "no/push back" answer but no three-layer model articulated: **PARTIAL**.
- Cites doctrine but proposes a half-measure (e.g. "add a short version"): **PARTIAL**.

## Why this scenario exists

Document layering is a recurring source of governance-doc breakage. The triage litmus test (cross-reference ask → accept / process-embed ask → push back / wording ask → accept on wording / structural ask → evaluate) is built into `.claude/rules/ai-governance.md`. Tests doctrine-application discipline on a question that triggers the path-rule's keyword load.

Note: this scenario depends on the prompt matching the ai-governance rule's keyword list ("Security Guidelines" → "guidelines" keyword should match; if not, the path-rule isn't being loaded — that's a separate failure to investigate).

## Cleanup

None.
