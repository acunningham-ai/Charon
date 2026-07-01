---
description: Hypothesis→test→eliminate debugging for the harness / a deployed service / the capture pipeline — pin the symptom, rank hypotheses, test one variable at a time, fix only the confirmed root cause, verify by reproduction.
argument-hint: "[the symptom, e.g. 'escalations not appearing in the approval queue' or 'the morning refresh didn't update TODO']"
allowed-tools: Read, Glob, Grep, Bash, Edit
---

# /systematic-debug — methodical root-cause debugging

You are debugging a real fault methodically. The discipline that matters: **don't jump to a fix.** Pin the symptom, form ranked hypotheses, test one variable at a time against evidence, confirm the root cause by **reproduction (not inference)**, then make the minimal fix and prove the symptom is gone. Targets: the harness scripts/hooks, a deployed service you operate, the capture pipeline, the review/security tooling, the mail/calendar layer.

Source: pattern borrowed (build-new, not vendored) from obra/superpowers' `systematic-debugging` skill — inspiration, not a code dependency.

## Scope

$ARGUMENTS

If provided, that's the symptom. If **empty**, ask: *"What's the symptom — what did you see, and what did you expect instead?"* — then wait. Don't guess the bug.

## Recipe

### 1. Pin the symptom
State precisely: **observed** behaviour vs **expected** behaviour, **when it started**, and **what changed** around then (a deploy, an `.env` edit, a new rule). Get or define a **reproduction** — the exact command/steps that show the fault. No repro yet? Finding one is the first task.

### 2. Form hypotheses — don't fix yet
List candidate causes, **ranked by likelihood × cheapness-to-test**. Resist the first-fix urge; a wrong fix on an unconfirmed cause hides the real one.

### 3. Test one variable at a time
Work the list cheapest/most-likely first. **Read-only diagnosis before any change** — logs, service status, a SELECT, file contents, `git`/mtime. Each test should *eliminate or confirm* a hypothesis. Known diagnostic paths:
- A deployed service: tail its logs, check its status (`/check-service`); **don't restart services to "see if it helps"** — that destroys state and isn't a test.
- Harness: `TODO.md` mtime + content first (the heartbeat); per-script logs second; `python scripts/check-capture-state.py`.
- Capture pipeline: the cursor doesn't advance on failure → state self-heals; check for a `REAUTH-NEEDED.flag`.

### 4. Confirm the root cause
Name the cause, **demonstrated by the reproduction** — not "this is probably it." If you can't reproduce-then-explain, you haven't found it yet (clean-signal discipline: don't declare on a guess; `/fp-check` rigour).

### 5. Fix + verify
Make the **smallest** change that addresses the confirmed cause. Then **re-run the reproduction** to prove the symptom is gone, and sanity-check for regressions. For credential-path / broker / settings edits, show the diff and get confirmation before applying.

### 6. Capture
If it's a named bug, recurring gotcha, or non-obvious fix → save it (`/save-feedback` or project memory) the same turn. Note what the symptom looked like so it's findable next time.

## Guardrails
- **One variable at a time** — parallel changes destroy the signal about which fix worked.
- **Read before write; reproduce before claiming fixed.** Confidence-tag the root-cause claim (🟢 reproduced / 🟡 strongly indicated / 🔴 suspected).
- **No destructive "tests"** (service restarts, data deletes, `--hard` resets) as probes — only as a confirmed fix, with a go for anything irreversible.

## Done criteria
- Symptom pinned (observed/expected/when/what-changed) + a reproduction.
- Ranked hypotheses, tested one at a time, with the eliminations recorded.
- Root cause **confirmed by reproduction**, not inferred.
- Minimal fix applied (diff shown first for sensitive paths) and verified by re-running the repro.
- Named bug/gotcha captured to memory.

## When to use
- A concrete, reproducible fault in the harness / a deployed service / the pipeline / the review tooling / the mail-calendar layer.

## When NOT to use
- **Greenfield design / "what should I build"** → `/brainstorm` or the `Plan` agent.
- **A security audit of working code** → `/secure-code-review` / `/owasp-*-review`.
- **You haven't read the actual error yet** → read it first; this isn't a substitute for the traceback.
- **Poisoned-signal / data-quality issues** (e.g. a learning loop trained on its own output) → that's a signal problem (the clean-signal gate), not a code bug.

## Co-change couplings
- Fix touches the credential broker / secrets dir / settings → diff-before-apply, human-gated.
- Named bug fixed → project memory + index, same turn.
