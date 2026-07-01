---
description: Structured divergent→convergent brainstorming for non-code work — frame, diverge, converge, evaluate, recommend. Inline-first; optional save.
argument-hint: "[the problem/question, e.g. 'how to frame the training launch' or 'names for the delivery seat']"
allowed-tools: Read, Write, Edit, Glob, Grep
---

# /brainstorm — structured idea generation for non-code problems

You are running a disciplined brainstorm. The point is not to jump to the first plausible answer but to **widen the option space, then narrow it on explicit criteria** — for non-code work: policy/guidance framing, talk premises, training design, naming, stakeholder/unit messaging, strategy calls, tool evaluations. Within ~50 words the reader should know this is "spread the options, then pick with reasons", not free-association.

Source: pattern borrowed (build-new, not vendored) from obra/superpowers' `brainstorming` skill — inspiration, not a code dependency.

## Scope

$ARGUMENTS

If provided, that's the problem to brainstorm. If **empty**, ask one line: *"What's the problem or question you want to brainstorm?"* — then stop and wait. Don't invent a topic.

If the topic is under-specified (you can't tell what "good" looks like), ask **1–2 clarifying questions before diverging** — guessing the goal wastes the whole pass (per the `no-assumptions` rule).

## Recipe

### 1. Frame
Restate the real question in one line, then surface the **constraints** and **what "good" looks like** (the success criteria the options will be judged on). If the framing carried personal/emotional context, that's tone scaffolding — capture the energy, don't transcribe it.

### 2. Diverge
Generate **5–8 genuinely distinct options/angles** — distinct in *kind*, not variations of one idea. Include at least one unconventional or contrarian option. Hold judgement here; breadth is the job. Number them.

### 3. Converge
Cluster the options (collapse near-duplicates), then **shortlist 2–3** against the success criteria from step 1. State why each made the cut and why the rest didn't.

### 4. Evaluate the shortlist
For each shortlisted option: what it optimises for, its main trade-off/risk, and who/what it's best when. **Disagree actively** where an option reads attractive but would produce a worse outcome — say so, don't hedge.

### 5. Recommend + commit
Give a **clear recommendation** with the reasoning, and the **single next concrete step**. A recommendation framed as such doesn't need a confidence tag; tag any load-bearing *factual* premise (🟢/🟡/🔴) the recommendation rests on.

## Guardrails
- **Inline-first.** Produce the brainstorm in the conversation. Don't auto-write a file. At the end, offer: *"Want this saved to `08-Projects/<X>/`?"* — write only on a yes.
- **Unit/stakeholder-facing topics:** name the risk + pattern, never a class of tool; governance framings endorse a principle, not an implementation.
- No web research in this skill — it's a thinking tool over what's known. If a factual gap is load-bearing, flag it as an open question rather than guessing.

## Done criteria
- Problem framed with explicit success criteria.
- ≥5 distinct options diverged, then a 2–3 shortlist with reasons.
- Trade-offs surfaced incl. at least one active-pushback point where warranted.
- A clear recommendation + next step.
- Nothing written to disk unless the user said yes.

## When to use
- A decision or framing with a wide solution space (naming, positioning, training/talk design, strategy).
- When you'd otherwise anchor on the first idea.

## When NOT to use
- **Code design/implementation strategy** → use the `Plan` agent or a `Workflow`, not this.
- **The answer is already clear** → just do it; brainstorming is friction.
- **Daily/weekly synthesis of what happened** → `/eod-reflect` or `/weekly-checkin`.
- **Security finding analysis** → `/secure-code-review` / `/fp-check`.

## Co-change couplings
- Output saved to a project → consider whether that project's `CLAUDE.md` / memory needs a pointer.
- If a brainstorm hardens into a standing rule you want kept → `/save-feedback` (don't self-write memory).
