---
description: Review a verdict-layer shadow window — per-rule fire counts, user-classified TP/FP, and a promotion / kill / extend recommendation per the trust-build threshold.
argument-hint: "[YYYY-MM-DD..YYYY-MM-DD]  (default: last 14 days)"
allowed-tools: Read, Glob, Grep, AskUserQuestion, Write
---

# /harness-watch-review — shadow-fortnight promotion call

End-of-shadow review for hook rules that have been running in monitor mode. Reads the verdict audit log over a window (default: last 14 days), surfaces per-rule fire counts + contexts, asks the user to classify each fire as true / false / borderline, then recommends — per rule — **promote to enforcing**, **kill**, or **extend monitor period** against the trust-build threshold (`>2 false positives in a fortnight → kill`).

Companion to the verdict layer (`_verdict.py` + `verdict-vocabulary.md`). Use this when you've shipped a new hook rule in monitor mode and need to decide whether to promote it.

## When to use

- ~14 days after a new rule first starts firing in monitor mode — the canonical promotion call point.
- Whenever a new rule is added to any hook in monitor mode and its own shadow window completes.
- After a noisy stretch where you suspect a rule is firing too often — diagnostic, even outside the regular 14-day window.

## Scope

`$ARGUMENTS` — optional date range, two forms supported:
- `2026-05-22..2026-06-05` — explicit window
- empty — last 14 days ending today (default; today is computed from system clock)

If `$ARGUMENTS` is malformed or unclear: stop and ask. *"Window unclear — defaulting to last 14 days from today, or specify YYYY-MM-DD..YYYY-MM-DD"*.

## Process — strict order

### 1. Resolve window

- Parse `$ARGUMENTS` to get `since` (inclusive) and `until` (inclusive, defaults to today).
- Confirm window is non-empty (`since <= until`) and not entirely in the future. If suspect, ask before proceeding.
- Format both as `YYYY-MM-DD` for downstream queries.

### 2. Load the verdict audit log

Source: `state/verdict/{YYYY-MM-DD}.jsonl` (the daily-rotation audit log written by `_verdict.py`).

- Use `Glob` to enumerate JSONL files within window.
- Use `Grep` to filter to lines where `"mode": "monitor"` AND `"declared" in ("ask", "deny")` — these are the shadow-mode fires that would have blocked in production.
- For each matching line, parse: `hook`, `rule`, `declared`, `effective`, `mode`, `reason`, `context`, `ts`, `session_id`.

If no monitor-mode fires were captured in window → stop, report empty window. (Likely cause: no monitor-mode rules are wired up, or the wrapper script isn't setting `HARNESS_MODE=monitor`.)

### 3. Aggregate per rule

Build a table: `(hook, rule)` → (fire count, declared distribution, date range of fires, sample contexts).

```
| Hook                  | Rule                | Fires | Declared          | First       | Last        |
|---|---|---|---|---|---|
| validate-write-path   | allowlist-miss      | 3     | deny: 3           | 2026-05-29  | 2026-06-01  |
| my-new-hook           | sensitive-content   | 1     | ask: 1            | 2026-05-26  | 2026-05-26  |
| my-new-hook           | rate-limit-exceeded | 7     | ask: 7            | 2026-05-23  | 2026-06-04  |
```

Rules that fired ZERO times in the window get a separate "no-signal" section — those don't go to classification, but flag them in the report so the user knows they remained silent. (Rule registered, but no event surfaced — either the failure mode didn't occur, or the threshold is too lenient.)

### 4. User classification — per fire, not per rule

For each rule that fired, present each fire as a row:

```
Hook/Rule: validate-write-path/allowlist-miss
  Fire 1/3 — 2026-05-29 06:55
    declared: deny
    reason: target not on allowlist for this unattended run
    context: automation=weekly-checkin, target=08-Projects/foo/bar.md
```

For each, use `AskUserQuestion` to classify:
- **True positive** — the signal was right; the underlying issue existed.
- **False positive** — signal fired but the underlying state was actually fine.
- **Borderline** — signal fired correctly but the threshold was probably wrong (too eager / too lazy); rule worth keeping with adjustment.

If there are many fires (>10 for a single rule), batch the AskUserQuestion to one per rule with a summary, and accept a single classification covering all of that rule's fires unless the user explicitly distinguishes.

### 5. Recommend per rule

Apply trust-build logic — ≥2 false positives in a fortnight kills the rule until reviewed:

| Fires | TP | FP | Borderline | Recommendation |
|---|---|---|---|---|
| 0 | — | — | — | **Hold in monitor.** Rule registered but no signal — extend window OR review threshold. |
| ≥1 | all | 0 | 0 | **Promote to enforcing.** Rule's signal track record is clean. |
| ≥1 | most | ≤2 | any | **Promote with caveat.** Note the FP/borderline cases as known-acceptable noise. |
| ≥1 | any | >2 | any | **Kill or revise.** Threshold too eager; either disable the rule or push the threshold and restart the shadow window. |
| ≥1 | none | any | any | **Kill.** Signal isn't tracking a real issue. |

Promotion mechanically means: remove `HARNESS_MODE=monitor` from the wrapper script for the automation that owns this rule. If multiple rules share one wrapper and only some are ready to promote, the rule code itself needs a per-rule override — surface this in the recommendation: *"Promoting `<rule>` requires either dropping monitor mode for the whole automation OR adding a per-rule override — which?"*

### 6. Confidence tagging

Apply 🟢 / 🟡 / 🔴 on findings:
- 🟢 on counts and dates (verified from the file reads)
- 🟡 on inferred classifications from context (before user confirms)
- 🔴 on any recommendation that depends on a guess about underlying state the user hasn't confirmed

### 7. Output

Inline report (no auto-write). Format:

```
## /harness-watch-review — <since> to <until>
**Window:** <N> days, <Y> verdict-audit entries in monitor mode

### Summary by rule

| Hook/Rule | Fires | Recommendation |
|---|---|---|
| validate-write-path/allowlist-miss | 3 | Promote to enforcing |
| my-new-hook/sensitive-content | 1 | Promote with caveat |
| my-new-hook/rate-limit-exceeded | 7 | Kill — 5 FP, threshold too eager |

### Per-rule detail

#### validate-write-path/allowlist-miss — Promote
**Classified:** 3 TP, 0 FP, 0 borderline
**Mechanism:** [explain how to promote — drop HARNESS_MODE=monitor from the wrapper, or add a per-rule override]
**Risk if promoted:** [name the false-positive class that would actually break the harness if it fired]

(repeat per rule)

### Rules that did not fire
- my-new-hook/auth-expiry — silent for 14 days. Real (no auth failures occurred) or threshold too lenient? Recommend leaving in monitor for another fortnight.

### Recommended next moves
1. <ordered list>
```

If the user says **"save it"** → write to `state/harness-reviews/review-{YYYY-MM-DD}.md` with frontmatter `type: harness-watch-review`, `window_since: ...`, `window_until: ...`, `verdict: ...`.

### 8. Quality loop

After presenting:
- *Are the false-positive classifications correct?* (especially borderline calls)
- *Any rules that should be re-checked before final promotion?*
- *If a rule was killed, should I draft the replacement rule with a tuned threshold, or is the failure mode just not worth detecting?*

## When NOT to use

- **Before day 7 of a shadow window** — too little data to make a promotion call. Premature reviews invite over-fitting.
- **For hooks already in production (`HARNESS_MODE` not set to monitor)** — those have no monitor-mode fires; there's nothing to review.
- **For routine daily diagnostics** — this skill is decision-grade only, run end-of-shadow-window.
- **As a substitute for reading the actual verdict audit log** — if a single fire is interesting, read its line directly. This skill is for cross-window pattern analysis.

## Anti-patterns

- **Classifying fires without user input.** The skill MUST ask. Don't infer TP/FP from context alone — the underlying state is operational truth only the user holds.
- **Recommending promotion on zero fires.** A silent rule isn't a clean rule, it's an unmeasured one. Extend window or revisit threshold.
- **Auto-saving the review.** Only on explicit "save it". Otherwise the report stays inline.
- **Treating monitor-mode downgrade lines as enforcing.** A line with `effective: observe` in monitor mode is NOT a real block; classify based on `declared` not `effective`.

## Co-change couplings

- **New rule added to a hook in monitor mode** → flag in the review that this rule is new and its window may differ from the rest.
- **Promotion call accepted** → propose updating the wrapper script to drop `HARNESS_MODE=monitor` (or add a per-rule override).
- **Kill call accepted** → propose either removing the rule from the hook OR adjusting its threshold; ask which.

## See also

- `.claude/rules/verdict-vocabulary.md` — the verdict schema this skill reviews
- `scripts/hooks/_verdict.py` — the implementation that writes the audit log
- `scripts/hooks/validate-write-path.py` — first verdict-emitting hook (reference implementation)
- `.claude/commands/fp-check.md` — verify findings before action; applies if you want to double-check a recommendation
