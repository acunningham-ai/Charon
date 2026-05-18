---
description: Quarterly report prep — gather inputs, draft commentary, assemble report
argument-hint: "[optional: quarter e.g. 'Q3-2026' (default: current/next quarter)]"
allowed-tools: Read, Write, Edit, Glob, Grep
---

# /quarterly-report-prep — quarterly stakeholder report

You are running the quarterly report prep workflow. The `quarterly-report.md` and `board-reporting.md` rules will auto-load — read them before you begin.

**Output convention:** tag findings, recommendations, and judgements inline with 🟢 verified / 🟡 medium / 🔴 assumed per `confidence-tags.md`. Particularly important for board-facing material — anything stakeholder-facing must make its verified/inferred boundary visible.

## Quarter selection
$ARGUMENTS

If empty, infer from today's date:
- Today in Jan/Feb/Mar → Q1 of current year
- Apr/May/Jun → Q2
- Jul/Aug/Sep → Q3
- Oct/Nov/Dec → Q4

Per the user's nominated cadence (configured during first-run, stored in `project_*_schedule.md`): typically start on a specific day of the cycle. If today is more than 2 weeks before that start date, ask the user if they want to defer. If today is past the next due date, use the next upcoming quarter.

## Process — strict order, do not skip

### 1. Three-question gate (NON-NEGOTIABLE)
Per the quarterly-report rule, before doing anything else, ask the user:

> It's time for the **{quarter}** quarterly report. I need three things from you:
> 1. A paste of the dashboard / source-of-truth snapshot for all org-units
> 2. Any vendor or deployment changes since last quarter
> 3. Any org-units to exclude from scoring and why

**STOP.** Wait for all three. Don't proceed with partial input. Don't compute scores yourself "just to get started" — replicating dashboard logic typically diverges from the source.

### 2. Capture the inputs verbatim
Save the user's paste to:
```
08-Projects/<your-reporting-project>/{quarter}/inputs.md
```
With frontmatter:
```yaml
---
type: quarterly-input
quarter: {quarter}
captured_at: {today ISO date}
source: "User paste from authoritative dashboard"
---
```
This is your reference for the rest of the run. **Do not transform it. Do not summarise it. Do not normalise the org-unit names.**

### 3. Verify completeness
Cross-check the dashboard paste against the user's authoritative org-unit register. If an org-unit is in the register but not in the paste, flag it: *"Org-unit {X} missing from paste — is it excluded, or did the dashboard miss it?"*

### 4. Draft commentary, NOT scores
For each rated org-unit, the report needs:

| Org-unit | Real Cause (the WHY) | Recommended Action |
|---|---|---|

The *Real Cause* and *Recommended Action* come from the user's per-unit context memory (typically `reference_per_unit_context.md`, populated during first-run + over time).

**If an org-unit's *why* isn't in that memory** — STOP. Ask the user: *"Org-unit {X} is rated {Compliant/Partial/Not Compliant} but I don't have plain-language context for why. Can you tell me?"* Save the answer to the per-unit context memory immediately (save-on-mention rule).

### 5. Assemble the report
Output: `08-Projects/<your-reporting-project>/{quarter}/quarterly-report-{quarter}.md`

Structure:
- **Executive summary** — one paragraph, plain language, no scores
- **Portfolio / sub-group rollups** — if your org has portfolio structure, one rollup per portfolio
- **Org-unit-level table** — Org-unit | Rating | Real Cause | Recommended Action
- **Movements since last quarter** — what changed, who's responsible for the change
- **Vendor / deployment changes** — from the user's answer to question 2
- **Exclusions** — from the user's answer to question 3, with reasons

### 6. User reviews
Show the draft. Per the quarterly-report rule:
- **Corrections go back to the user to fix in the dashboard / source of truth, NEVER in a separate file.**
- If the user disagrees with a rating in the paste, the answer is "fix it in the dashboard, then re-paste, then I'll regenerate."

### 7. Final delivery
Once the user approves, the report is final. Don't continue editing it after delivery — corrections to the underlying data go to the dashboard, and the report is regenerated next cycle.

## Things this command must NEVER do
- Compute scores (the dashboard is canonical, your replication will diverge)
- Carry forward data from a previous quarter
- Quote scores in commentary (per board-reporting rule — the *why* carries the meaning)
- Edit an org-unit's rating because it "looks wrong" (it goes back to the user to fix in the dashboard)
- Save anything to memory silently — surface every memory write proposal explicitly
