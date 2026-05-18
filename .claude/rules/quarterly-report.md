---
paths:
  - "08-Projects/*Reporting*/**"
  - "08-Projects/*Report*/**"
keywords:
  - "quarterly report"
  - "quarterly security report"
  - "dashboard paste"
  - "quarterly review"
---

# Quarterly report rules

Auto-loaded under your quarterly-reporting project path. **The board-reporting rule (`board-reporting.md`) also fires on these paths** — read it for plain-language WHY, audience-tailoring, critical-controls discipline, aggregate-score caveat, "X or similar tool", and the reframing pattern. This rule is quarterly-process specific; everything reportable-style lives in `board-reporting.md`.

## Hard rules — apply on every quarterly cycle

| Rule | What it means |
|---|---|
| **Three-question gate (non-negotiable)** | Ask the user for (1) authoritative dashboard / source-of-truth snapshot, (2) scope changes since last quarter (vendor changes, deployment status changes, BU/org-unit movements), (3) units excluded and why. **Stop. Wait for all three.** Don't compute "just to get started". |
| **Dashboard is source of truth** | Use the verdicts (Compliant / Partial / Not Compliant, or your framework's equivalents) directly. **Never** recompute. Replicating a scoring formula in code-side often diverges from the source — costly mismatches. |
| **No carry-forward** | Never carry forward data from last quarter — vendor assignments, deployment status, scoring all drift. Pull fresh. |
| **Corrections go to the authoritative source** | When the user corrects the draft, the fix lands in the **dashboard / source of truth**, never in a separate report file. |
| **Critical controls section required** | Every quarterly report includes the Critical Control Status section sourced from your nominated control set. Plain-language status per control. |
| **Drop scoring-mechanic language** | Internal terms ("capped at X.Y", "gate pass/fail", "no cap applied") stay internal. Not reportable. |
| **Aggregate-score caveat** | If overall above target AND a meaningful number of domains below target → explicit caveat section. Repeat in takeaway. |
| **Framework layers** | Lead with critical controls (cross-unit comparable, exec-relevant). Maturity domains underneath as per-unit measurement with calibrated targets. |
| **Ask when uncertain** | If the data looks wrong, **ASK**. Don't assume. Don't silently pick. Source-of-truth wins on conflict. |

## The generation process — strict order

1. **Three-question gate** (above) — wait for all three.
2. **Capture inputs** verbatim to `08-Projects/<your-reporting-project>/<quarter>/inputs.md`.
3. **Use the dashboard snapshot AS the data** — verdicts directly; no recalculation.
4. **Add plain-language commentary** for each org-unit sourced from your per-unit context memory. If a unit's *why* isn't there yet — ask, save the answer immediately (save-on-mention).
5. **Apply board-reporting reframes** — "X or similar tool", no top-down policy template, audience-tailored framing, drop scoring-mechanic language. See `board-reporting.md`.
6. **Caveat the headline** if the aggregate-score trigger fires.
7. **Confidence-tag** every derived claim (🟢 / 🟡 / 🔴) per `confidence-tags.md`.
8. **User reviews the draft.** Corrections to the dashboard, not to a separate file.

## Cadence

Your reporting cadence (quarterly / monthly / other), specific quarter-start dates, and the prompt-window timing live in your own schedule register (`project_*_schedule.md`), populated during first-run. The harness ships the discipline (3-question gate, no carry-forward, dashboard-is-truth); you supply the calendar.

## How to run — supporting skills

| Skill | When | What it produces |
|---|---|---|
| `/quarterly-report-prep` | At cycle start | Runs the three-question gate + drafts commentary + assembly |
| `/control-translate <scope> <target>` | Mid-cycle, ad-hoc paragraph needs | One 3-sentence paragraph for an appendix or audit response |

## Anti-patterns (auto-flag if I'm drifting)

- **Computing a score** to get started — defeats the source-of-truth pattern.
- **Carrying forward last quarter** — drift everywhere.
- **Skipping the three-question gate** — non-negotiable.
- **Editing scores in a vault file** instead of fixing in the dashboard.
- **Letting scoring-mechanic language leak** into stakeholder layer.
- **Treating "above target" as "done"** — check the aggregate-score caveat.
- **Querying only one source table** when the dashboard spans multiple — check completeness.

## Co-change couplings

- **Dashboard adds a critical control** → update the Critical Control Status template in quarterly reports
- **Vendor change at an org-unit** → confirm in the three-question gate; update your per-unit context memory
- **Per-unit target recalibrated** → reflect in commentary; do not apologise for variance
- **New org-unit added** → confirm scoring inclusion in the three-question gate

## See also

- `board-reporting.md` — adjacent rule; everything reportable-style lives there
- `confidence-tags.md` — convention used on every derived claim
- `.claude/commands/quarterly-report-prep.md` — quarterly ritual skill
- `.claude/commands/control-translate.md` — paragraph generator
- User memory (populated during first-run): your `feedback_quarterly_process.md`, `feedback_data_accuracy.md`, `project_*_schedule.md`, `reference_*_framework.md`, `reference_per_unit_context.md`
