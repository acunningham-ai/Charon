---
paths:
  - "08-Projects/*Reporting*/**"
  - "**/Board-*.md"
  - "**/board-*.md"
  - "**/Audit-and-Risk-*.md"
  - "**/*-Posture-*.md"
  - "**/PAR-*.md"
  - "**/par-*.md"
  - "**/*-PAR.md"
  - "**/*-par.md"
  - "08-Projects/*/par/**"
  - "08-Projects/*/PAR/**"
keywords:
  - "board report"
  - "board pack"
  - "board commentary"
  - "audit and risk"
  - "audit & risk"
  - "quarterly report"
  - "quarterly security report"
  - "par"
  - "m&a par"
  - "post-acquisition review"
  - "post acquisition review"
  - "critical control"
  - "critical controls"
  - "executive briefing"
  - "exec brief"
  - "stakeholder report"
---

# Board / executive reporting rules

Auto-loaded when working on stakeholder reports, PARs, board papers, Audit & Risk Committee material, or any document going above the security function.

**This rule ships the universal patterns.** The org-specific layer — your audience tiers, critical-control list, framework calibrations, dashboard tool, tool exceptions — comes from your own memory files, populated during first-run from your org chart. Don't expect the harness to know your operating model; it'll know what you tell it.

## Hard rules — apply on every stakeholder-facing report

| Rule | What it means |
|---|---|
| **Plain-language WHY** | Never report a score / colour without the business reason behind it. Scores can sit in tables; commentary must carry the meaning. |
| **Dashboard is source of truth** | Take scores and verdicts AS GIVEN from your authoritative source (whichever tool you've nominated). Never compute, infer, or carry forward last period's numbers from memory. |
| **Critical controls — required section** | Every stakeholder report includes a Critical Control Status block — the controls you've nominated as your cross-org-unit baseline. These are headline-relevant; they're the apples-to-apples comparison across all your org-units. |
| **Drop scoring-mechanic language** | Internal scoring terms ("capped at X.Y", "gate pass/fail", "no cap applied") stay internal. They are dashboard mechanics, not reportable. |
| **Aggregate-score caveat** | If overall maturity is above target AND a meaningful number of underlying domains are below target → explicit caveat section. Repeat in the takeaway summary so it lands twice. |
| **"X or similar tool" framing** | A CISO function typically advises rather than mandates. Default: every tool recommendation gets capability-led framing — "an SCA tool (e.g. Snyk, or similar tool)". The word "tool" is load-bearing. If your org has a named exception (a vendor you DO standardise on org-wide), it's defined in your memory; everything else gets the framing. |
| **No top-down policy template by default** | Unless your org explicitly publishes one, don't imply head office pushes down a policy. Reframe "adopt the baseline" → "develop an org-unit-appropriate policy proportionate to size, advisory engagement available". |
| **Audience-tailored framing** | Tailor to the audience tier reading the report. Your tier definitions and per-tier reminders live in your own memory (populated during first-run from your org chart). |
| **Confidence tags on derived claims** | Every substantive prose claim carries 🟢 / 🟡 / 🔴 per `confidence-tags.md`. Board output without provenance markers is unacceptable. |

## Reframing pattern (shape; specifics are yours)

The job: turn a raw dashboard score into a sentence that carries business meaning.

| ❌ Wrong shape | ✅ Right shape |
|---|---|
| "<Org-unit> partial at 2.7" | "<Org-unit> has backups in place but lacks a formal restoration testing schedule" |
| "Deploy <Vendor> for <X>" | "Deploy a <capability> tool (e.g. <Vendor>, or similar tool) — must support <auditable requirement>" |
| "Adopt the head-office baseline policy" | "Develop an org-unit-appropriate policy proportionate to size; advisory engagement available" |
| "<Org-unit> above target — posture healthy" | "<Org-unit>'s headline is above target, but N of M domains sit below target — the headline is driven by <2 strong domains>. Underlying work remains." |

## How to run — the supporting skills

| Skill | When | What it produces |
|---|---|---|
| `/quarterly-report-prep` | Quarterly — first day of your nominated cadence | Full ritual: input gate (dashboard snapshot, scope changes, exclusions) → captured-inputs file → drafted commentary → review checkpoint |
| `/control-translate <scope> <target>` | Ad-hoc — single paragraph for a board appendix, customer question, audit response | One 3-sentence paragraph in the cause → so-what → action shape |

**Flow for a typical board paper:**

1. Ask the user for the authoritative source-of-truth snapshot — non-negotiable; never compute scores yourself
2. Use `/control-translate` for per-org-unit paragraphs OR `/quarterly-report-prep` for the full period
3. Apply the reframing pattern on every recommendation
4. Caveat the headline number if the aggregate-score trigger fires
5. Confidence-tag every derived claim
6. User reviews; corrections go back to the **authoritative source**, not into a separate file

## Anti-patterns

- **Computing a score** because "I just need a rough number to get started" — defeats source-of-truth. Ask for the snapshot.
- **Carrying forward last period's data** without re-checking — assignments and deployment status drift.
- **Naming a vendor as a recommendation** without "or similar tool" (unless it's the user's configured exception).
- **Including operating-model orientation paragraphs** when the audience already lives it.
- **Reading "above target" as "no work needed"** — check the aggregate caveat.
- **Reporting a colour without the WHY** — defeats the purpose of the report.
- **Letting scoring-mechanic language leak through** ("capped at 2.0") — dashboard internals, not reportable.

## See also

- `confidence-tags.md` — convention used on every derived claim
- `.claude/commands/quarterly-report-prep.md` — quarterly ritual
- `.claude/commands/control-translate.md` — paragraph generator
- User memory (populated during first-run): your `feedback_board_reporting.md`, `feedback_no_tool_mandate.md`, `feedback_aggregate_score_caveat.md`, `reference_audience_tiers.md`, `reference_critical_controls.md`, `reference_framework.md`
