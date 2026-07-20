---
description: On-demand self-improvement survey — where could the harness do what it already does BETTER (higher-quality outcomes, less friction)? Surfaces each opportunity as a plain-English change + the benefit you'd get, and you decide. Read-only; proposes, never auto-applies.
allowed-tools: Read, Grep, Glob, Bash, Skill
---

# /harness-improve — what could be better, and what you'd get

The self-**improvement** counterpart to `/harness-doctor`. Where the doctor asks
*"is anything broken?"*, this asks *"where could the harness do what it already
does **better** — higher-quality outcomes, less friction — and is it worth it?"*

This is the **self-improving** capability: it doesn't do new things, it makes the
same things better over time. It unifies the harness's existing improvement
primitives into one survey and — like self-healing — **surfaces the change in
plain English with the concrete benefit, then leaves the decision to you.**

## The governing rule (same brakes as self-healing)

- **Human-final-say.** Every proposal is a suggestion. Nothing is applied here.
- **Plain-English change + benefit.** For each opportunity, state (a) *what would
  change*, in one plain sentence, and (b) *what you get out of it* — the concrete
  quality or efficiency gain. No jargon, no "optimise the pipeline."
- **Clean signal only.** Only surface improvements grounded in a deterministic or
  human-verified signal (usage counts, filesystem facts, trigger collisions,
  recurrence in `score-vault` / the vault-hygiene ledger) — never a model's
  unverified hunch. A loop that learns from its own noise degrades; this one
  reads facts and proposes.
- **Surface, don't act.** Applying a proposal is a separate, deliberate step you
  take by running the named command.

## What it surveys (existing primitives, unified)

Run each, collect the candidates, and present them together — ranked by benefit ÷ effort:

1. **Doctrine that's earned promotion** — run `/promote-rule`. A memory rule you've
   leaned on repeatedly is a candidate to become a path-scoped rule (fires
   automatically at the right moment) or a standalone skill.
   *Change:* "promote memory rule X to a path-rule." *You get:* "it fires
   automatically when you're in that context instead of only when recalled."
2. **Skills that could trigger or perform better** — run `/skill-eval` on skills
   whose descriptions overlap or look mis-firing. *Change:* "tighten skill Y's
   description." *You get:* "it fires on the right prompts and stops colliding
   with skill Z."
3. **Stale surface worth pruning** — run `/curate-skills`. *Change:* "archive
   dormant skill W." *You get:* "a smaller, sharper command surface — less noise
   when Claude picks a tool."
4. **Recurring hygiene drift → the closed learning loop.** This arm is a full
   propose→apply→measure cycle, not just a survey line — it's the one part that
   actually *learns*, grounded end-to-end on a deterministic signal:
   - `python scripts/vault-hygiene-recurrence.py` — the signal: which score-vault
     finding-classes PERSIST / RISE / REAPPEAR across the ledger's history (pure
     ledger maths, never the model's say-so — no autophagy).
   - `python scripts/vault-hygiene-proposal.py --targets` — the classes worth a
     STRUCTURAL fix; `--open --kind <category|finding> --key <key> --change "…"
     --benefit "…"` records a proposal and captures the class's baseline. You
     supply the fix text; it's observe/propose-only, nothing is applied.
     *Change:* "a structural guard so recurring class C can't come back."
     *You get:* "the whole class stops recurring; the hygiene score stops sagging."
   - You apply the fix, then `--apply <id>` timestamps it (YYYY-MM-DD validated).
   - `python scripts/vault-hygiene-postcheck.py` — the KEYSTONE: did that class's
     recurrence actually FALL after the fix? Deterministic, zero model
     self-assessment; `--record` appends the verdict to the proposal's
     append-only history. A fix that didn't hold returns `no_change`/`worse` —
     surface that honestly, don't bury it.
   The proposal→outcome history is what the loop learns from: which structural
   fixes genuinely reduced recurrence. Human-final-say at every step; the
   deterministic post-check is the ONLY thing allowed to conclude "it worked."

Skip any source whose primitive isn't present/applicable; say so rather than
inventing an opportunity.

## Output format

```
## /harness-improve — <date>

Ranked improvement opportunities (nothing applied — you choose):

### 1. <one-line title>   [benefit: high · effort: low]
**Change:** <one plain-English sentence — what would change>
**You get:** <one plain-English sentence — the concrete quality/efficiency gain>
**Signal:** <the deterministic/verified fact this rests on — e.g. "rule recalled 6× in 3 weeks">
**To apply:** `<the exact command to run>`

(repeat, most worth-it first)

### Nothing worth changing
<if a source is clean, say so — "no skills are mis-triggering", etc.>
```

## When NOT to use

- Not a nightly auto-runner — it proposes; you act. (A scheduled *surfacing* is
  fine; a scheduled *apply* is not — that would cross the human-final-say line.)
- Not for fixing what's broken — that's `/harness-doctor` (health) and
  `/harness-heal` (recovery). This is for making what works work better.
- Don't manufacture an opportunity to fill the list. A short, honest survey beats
  a padded one.

## Roadmap note (honest ceiling)

Most arms here **unify primitives that already exist** — each human-gated and
surface-only. The exception is arm 4: the vault-hygiene loop is a genuine
**deterministic learning loop**, but a *narrow* one — it learns only which
structural fixes reduced recurrence of a `score-vault` finding-class, and only
from the deterministic ledger (recurrence → propose → apply → post-check), never
from its own output. The broader capability — a loop that watches its own
operation *across the whole harness* and learns which changes raised outcome
quality — is a separate, gated build (its own clean-signal proof + shadow window
+ adversarial review) before it earns a place here. This command hosts that when
it ships; it does not claim it yet. It ships propose-only / human-final-say: the
deterministic post-check is the only thing allowed to conclude "it worked," and
nothing is ever auto-applied.

## See also

- `.claude/commands/harness-doctor.md` — the self-healing counterpart (what's broken)
- `.claude/commands/promote-rule.md` · `skill-eval.md` · `curate-skills.md` · `score-vault.md` — the primitives this unifies
- `.claude/rules/verdict-vocabulary.md` — the observe/ask/deny discipline both self-healing and self-improvement inherit
