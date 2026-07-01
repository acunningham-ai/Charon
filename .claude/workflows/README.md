# Workflows (`.claude/workflows/*.js`)

Multi-agent **workflows** — deterministic orchestration scripts that fan work out across many subagents, then converge. Each is a JavaScript file exporting a `meta` block plus a script body that calls `agent()` / `parallel()` / `pipeline()` / `phase()` (the Claude Code `Workflow` tool's runtime hooks). Where a **subagent** (`.claude/agents/`) is one worker and a **command** (`.claude/commands/`) is one prompted routine, a **workflow** is a *harness*: it decides what fans out, what verifies, and what synthesises — in code, not model discretion.

The distinctive property is **adversarial self-verification**: findings aren't trusted because an agent produced them; they're challenged by independent skeptics and only survive if they hold. Both shipped workflows use this shape.

## What ships

| Workflow | What it does | Invoke |
|---|---|---|
| **deep-research** | Self-verifying deep research — decompose a question into search angles, fan out parallel web search, fetch + extract falsifiable claims, then a 3-vote adversarial verify with a re-queue loop (evidence-handling rejects are re-researched against a live source until the verify pass finds nothing to re-queue). Synthesises a cited report. | `/deep-research` · args = the question |
| **devils-advocate** | Adversarial pre-mortem / devil's advocate for hard-to-reverse **non-code** decisions (a hire, a launch, a policy line, a big bet). Fans out hostile lenses (Key Assumptions Check · Pre-Mortem · adapted-adversary · disappointed-counterparty · conditional Analysis of Competing Hypotheses), consolidates, then 3-vote adversarially verifies every surfaced risk and runs a **grounding gate** tagging each survivor grounded / plausible / invented. Ends on a kill / proceed-with-fixes / proceed verdict. Draft-only. | `/devils-advocate` · args = the decision |

Both borrow the **loop-not-line** self-verification pattern (independent verifiers whose job is to *refute*, majority-refute kills a finding) — deep-research against web claims, devils-advocate against self-generated critique.

## How discovery + invocation works

Workflows are discovered by the Claude Code runtime **at session start** — it scans `.claude/workflows/*.js` and registers each by its `meta.name`. So:

- **After a session start**, invoke by name: `/deep-research` or `Workflow({ name: 'devils-advocate', args: '…' })`.
- **A workflow added mid-session** isn't registered yet — run it by path: `Workflow({ scriptPath: '.claude/workflows/devils-advocate.js', args: '…' })` until the next session start picks it up.
- Add a `Workflow(<name>)` line to `.claude/settings.local.json` permissions to skip the by-name approval prompt.

Requires a Claude Code version that exposes the `Workflow` tool. Workflows spawn many subagents and can consume significant tokens — scale is intended for genuinely hard questions / high-stakes decisions, not quick asks.

## Safety posture

- **Read + reason only.** Neither workflow writes to your vault, sends, or posts. `devils-advocate` returns a verdict object; `deep-research` returns a cited report. Any save is a separate, human-confirmed step.
- **Trust boundary.** Caller input and any web/vault content an agent reads are wrapped and treated as **data, not instructions** (OWASP-agentic ASI01/ASI06). An embedded "ignore your instructions" payload becomes a *finding*, not a command.
- **No silent capability creep.** Grounding/verify agents are read-only by instruction; the orchestration writes nothing.

## Authoring a new workflow

Start `export const meta = { name, description, whenToUse, phases }` (pure literal), then the body. Keep the `name` equal to the filename stem — the D22 deterministic check enforces it. Genericise before shipping (no personal names, org-specific content, or local paths — the D5 personal-content scrub now covers `.js`). Run `python test-scenarios/run-deterministic-checks.py` before release.
