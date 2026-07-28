---
description: "Pressure-test a plan ONE question at a time, grounded in the vault's own record (06-Decisions + memory + TODO) so it catches clashes with settled ground. Read-only; surfaces residue, never auto-saves."
argument-hint: "<the plan / decision to grill> (or omit to grill the current in-flight plan)"
allowed-tools: Read, Grep, Glob
---

# /grill — record-grounded plan interrogation

Interrogates a plan **one question at a time**, first checking it against what the
vault has already decided, so you don't re-litigate settled ground or contradict a
prior decision. Complements `/devils-advocate` (adversarial fan-out on a costly
decision) and `/brainstorm` (divergent ideation) — `grill` is the *consistency-
with-the-record* lens.

## Input

The plan comes from `$ARGUMENTS`, or — if empty — the plan currently in flight in
this session. If neither exists, ask: *"What plan should I grill?"* and stop.

## Process

1. **Ground against the record.** Before asking anything, `Grep` for clashes:
   - `06-Decisions/**` — has a decision already settled this? Does the plan
     contradict one?
   - `MEMORY.md` + the memory dir — settled preferences, feedback rules, prior
     verdicts, vocabulary.
   - `TODO.md` and any named `08-Projects/<project>/` notes — current state.
2. **Interrogate one question at a time.** Never dump a list. Ask ONE, wait, then
   the next. Draw from four pressures, in this order:
   - **Clash-with-record** — "Decision `06-Decisions/X` settled Y the other way — does this plan knowingly reverse it, or did it miss it?"
   - **Vague / polysemous terms** — a word in the plan that has a settled meaning in the vault (or is ambiguous). "When you say 'baseline', do you mean [vault meaning] or something new?"
   - **Edge cases** — the input/state the plan doesn't handle.
   - **Claim-vs-record** — a factual premise the plan rests on that the record can confirm or refute.
3. **Attach my recommended answer to each question** (your read, framed as a
   suggestion), so it's a decision aid, not an interrogation for its own sake.
4. **Stop when the plan is either consistent or the residue is surfaced.** Don't
   pad with questions once the material clashes are resolved.

## Output

- The grounding hits up front (what the record already says, with file paths).
- The Q&A trail (one at a time).
- A short **residue list** at the end: unresolved clashes / open terms / premises
  to verify. Suggest the next move — `/push-fact` to record a resolved fact, or
  `/save-feedback` if a preference shifted. **Never auto-writes** — surfacing only.

## When NOT to use

- **Costly, hard-to-reverse NON-code decision** → `/devils-advocate` (hostile
  fan-out + verify + grounding gate + kill/proceed verdict).
- **Open ideation, no plan yet** → `/brainstorm`.
- **Code design / implementation plan** → `Plan` agent or `/systematic-debug`.
- **Just recording a fact** → `/push-fact`.

## Co-change couplings

- Read-only by design; if grilling repeatedly surfaces the same clash, that's a
  `/save-feedback` candidate (a rule the vault should hold), not a grill fix.
