---
description: Evaluate a skill before shipping — trigger-accuracy (does its description fire on the right prompts and NOT collide with adjacent skills?) and, opt-in, a paired skill-vs-baseline A/B with real token/timing deltas. Static + cheap by default; --live spawns subagents (costs tokens). Read-only; proposes description tweaks, never auto-edits the skill.
argument-hint: "<skill-name> [--live]  e.g. /skill-eval prometheus   /skill-eval docs --live"
allowed-tools: Read, Grep, Glob, Agent, Skill
---

# /skill-eval — does this skill trigger right, and does it actually help?

Evaluates a skill in `.claude/skills/` or `.claude/commands/` on the two things a skill-authoring
review doesn't already measure: **trigger accuracy** and **measured benefit vs baseline**. This is
a native rebuild of the author→eval→iterate loop — Claude-only, subagents via the Agent tool, no
external harness.

**Complements, doesn't replace** the existing pre-ship gates (`/secure-code-review`,
`/owasp-*-review`, `/fp-check`, first-run calibration). Those check *safety* and *correctness*;
this checks *triggering* and *usefulness*.

## Modes

- **static (default)** — no subagents, cheap. The everyday pre-ship check.
- **`--live`** — adds the paired A/B (spawns subagents; **costs tokens** — say so and only run when the static pass looks good).

## Step 1 — Load the target + its neighbourhood (static)

1. Read the target skill's `SKILL.md` (or `commands/<name>.md`): capture its `description`,
   trigger phrases, and **When NOT to use** list.
2. `Grep` the `description:` line of every OTHER skill/command for the target's trigger phrases.
   Build the **adjacency set** — skills whose triggers overlap.

## Step 2 — Trigger-accuracy check (static)

Derive two prompt sets from the skill's own metadata (no invention beyond its stated triggers):

- **should-fire** — 3-5 prompts a user would naturally phrase for this skill (from its trigger
  phrases + purpose).
- **should-NOT-fire** — 2-3 prompts that belong to an *adjacent* skill (from the adjacency set's
  triggers + this skill's own "When NOT to use").

For each prompt, judge — from the descriptions alone — **which skill's description matches most
strongly**. Report:

- ✅ **clean** — should-fire prompts match the target; should-NOT prompts match the neighbour.
- ⚠️ **collision** — a should-fire prompt matches a neighbour as strongly (ambiguous trigger), or
  a should-NOT prompt matches the target (over-broad trigger).

For every collision, propose a **specific description edit** (add a distinguishing phrase, tighten
a trigger, sharpen "When NOT to use") — as a suggestion for the user, **do not edit the skill**.

## Step 3 — Assertion scaffold (static)

For one representative should-fire prompt, write 2-4 **assertions** the skill's output must satisfy
(e.g. for a review skill: "cites file:line for each finding", "tags each finding by severity",
"frames output as risk-evidence, not approval"). These are the grading rubric for `--live`, and are
useful on their own as a definition-of-done.

## Step 4 — Paired A/B benefit (`--live` only)

For 1-2 should-fire prompts, spawn **two subagents** on the same prompt:

- **with-skill** — instructed to use the target skill (via Skill/the command).
- **baseline** — same prompt, instructed NOT to use it (plain response).

Then:
1. **Grade** both outputs against Step 3's assertions (how many satisfied).
2. **Benefit delta** — assertions passed with-skill minus baseline. A skill that doesn't beat
   baseline on its own assertions is not earning its context cost — flag it.
3. **Cost delta** — report each subagent's `subagent_tokens` + `duration_ms` (from the Agent
   result usage). State the token/time the skill adds.

Keep it to ≤2 prompts × 2 arms (≤4 subagents) unless the user asks for more — this is a spot-check,
not a benchmark suite.

## Step 5 — Report

```
### Skill eval — <name> — <date>
Trigger accuracy: <clean | N collisions>
  - <prompt> → matched <skill> [✅/⚠️]  ...
Description tweaks suggested: <list, or none>
Assertions (definition-of-done): <list>
--live (if run):
  Benefit: with-skill <n>/<m> vs baseline <k>/<m> assertions  → delta +<d>
  Cost: with-skill <tok>/<ms>, baseline <tok>/<ms>  → skill adds <Δtok>/<Δms>
Verdict: <ship | tighten-description-first | reconsider-value>
```

## Confidence + honesty
- Tag the trigger-accuracy judgement 🟢 (read the descriptions this turn) / 🟡 (inferred).
- **Small-sample caveat:** `--live` is a 1-2 prompt spot-check, not statistical proof. Say so.
  Don't present a 2-prompt A/B as a definitive verdict on the skill's value.
- First-run calibration still applies — a fresh skill's own eval can be as miscalibrated as the
  skill; sanity-check before trusting a "reconsider-value" verdict.

## When NOT to use
- **Safety/correctness review** → `/secure-code-review`, `/owasp-*-review`, `/fp-check`. This is
  triggering + usefulness, not security.
- **A skill with no LLM-judgement surface** (pure deterministic script) → trigger-accuracy still
  applies, but skip `--live` (there's no baseline-vs-skill quality gap to measure).
- **Mid-authoring iteration on content** → just edit; run this once the skill is close to shippable.

## Co-change couplings
- Added as a pre-ship gate → reference it from the skill-authoring rule's "Run before shipping" table.
- New skill built → consider running `/skill-eval <name>` before announcing it done.
