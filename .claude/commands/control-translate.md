---
description: Generate stakeholder-readable plain-language commentary for a control rating — pulls per-unit context + framework rubric language; never computes scores
argument-hint: "<scope> <target> — e.g. 'unit <Name> patching' | 'portfolio <Name> mfa' | 'control patching all-units' | 'framework iso42001 supplier-risk'"
allowed-tools: Read, Write, Edit, Glob, Grep
---

# /control-translate — control rating → stakeholder paragraph

You are translating a maturity rating into language a non-technical stakeholder (GM, exec, board, customer) can act on. Source-of-truth for *scores* is the user's authoritative dashboard — you NEVER compute or guess one. You take ratings as given and produce the **why** + **so what** that the board-reporting rule demands.

Sibling to `/quarterly-report-prep`: that skill runs the whole quarterly ritual; this one is the paragraph generator. Use this for ad-hoc commentary (a customer question, an audit response paragraph, a single-unit board appendix, a framework citation lookup) — not the full quarterly report.

**Auto-loaded rules:** `quarterly-report.md` and `board-reporting.md` rules will inject on keyword match. Re-read your `feedback_board_reporting.md` and `feedback_security_guidance_lens.md` (user-configured during first-run) plus the relevant section of `reference_per_unit_context.md` before drafting.

**Output confidence tagging:** every prose finding gets 🟢 verified / 🟡 medium / 🔴 assumed per `confidence-tags.md`. Stakeholder-facing output without verified/inferred markers is unacceptable.

## Scope

`$ARGUMENTS` — required. First token = mode, remainder is target. Modes:

| Mode | Args | Output |
|---|---|---|
| `unit <unit-name> <control>` | Org-unit name + control name (your configured control set) | One 3-sentence paragraph (the cause, the so-what, the action), with optional framework citation |
| `portfolio <portfolio-name> <control>` | Portfolio + control | Portfolio rollup — common root cause, exceptions called out, action-owner clarity |
| `control <control> all-units` | Single control across all units | Cross-unit view of a single control; reds named, greens summarised |
| `framework <framework-key> <topic>` | Any framework key (e.g. `iso42001`, `nist-csf`, `e8`, `iso27001`, `soc2`) + topic phrase | Framework-informed commentary — frame / risks / what good / where to start / mitigations / who to talk to. URN references demoted to provenance footer. Standards are scaffolding, not URN quotes to paste. |

If `$ARGUMENTS` is empty: stop and ask *"Which mode? Examples: `unit <Name> patching`, `portfolio <Name> mfa`, `control eol all-units`, `framework iso42001 supplier-risk`."*

## Process — strict order

### 1. Resolve the target

- For `unit` / `portfolio`: confirm the unit/portfolio exists in your org-unit register. If not, stop and ask — don't guess.
- For `control`: confirm it's in your configured critical-control list.
- For `framework`: confirm the framework reference exists in `07-References/frameworks/`. Read the relevant clauses/sections for the topic before drafting — this is central to the mode, not optional.

### 2. Read the per-unit context

For `unit` and `portfolio` modes:
- Open your per-unit context memory file.
- Locate the entry for the target.
- **If the entry is empty or the unit isn't there** — STOP. Ask the user:
  > *"Unit {X} / control {Y} isn't in your per-unit context memory. I won't make up the why. Can you tell me the root cause, or paste the relevant dashboard row so I can read it back?"*

  Save the answer to that memory file in the same turn (save-on-mention rule). Then continue.

### 3. Read the framework rubric (optional context)

For `unit` / `portfolio` / `control` modes, optionally consult the matching framework reference for polished plain-language description of *what good looks like*. Use selectively — the framework's job is to inform the *what good* sentence, not to replace voice.

Cite the framework as `(<Framework> <Clause> — <Topic>)` style. Don't dump the full reference text; quote 1 phrase max.

### 4. Apply the 5-question security-guidance lens

Every section the stakeholder reads should let them come away with:

1. **What good looks like** — the posture the unit should be at
2. **Where to start** — first move, framed for a busy stakeholder
3. **The risks** — what can actually go wrong, plain language
4. **How to think about mitigating them** — the controls or habits
5. **Who to talk to** — the named function (CISO office, MSSP, IT lead, etc.)

For a 3-sentence paragraph you can't hit all five — pick the 2-3 most load-bearing. For a portfolio rollup, hit four of five. **For `framework` mode, hit all five** — frame / risks / what good / where to start / mitigations / who to talk to. The framework gives you the lens; you produce the synthesis in voice.

### 5. Draft — board-reporting rule applies

**Never report a score without root cause.** Per the board-reporting rule:

- ❌ "<Unit> RED at 0.8 for patching"
- 🟢 "<Unit> has no patch management tool deployed — small team, no dedicated IT FTE, relying entirely on manual processes. Risk: missed critical patches. Action: deploy an automated patching tool (e.g. <Vendor>, or similar tool) for endpoints; coordinate with <responsible function> for server patching."

Score can appear in a table cell for visual reference, but commentary carries the meaning.

### 6. Confidence-tag the draft

Inline 🟢 / 🟡 / 🔴 markers on prose findings:

- 🟢 verified — sourced from per-unit context memory, dashboard snapshot, or framework reference.
- 🟡 medium — inferred from context (e.g. portfolio-level rollup pattern the user has confirmed before).
- 🔴 assumed — anywhere you've extrapolated. Flag it for the user to fact-check.

### 7. Output artefact

- For ad-hoc requests: return the paragraph inline. Don't auto-write a file unless the user asks.
- If the user says "save it", write to: `08-Projects/<your-reporting-project>/snippets/{YYYY-MM-DD}-{scope}-{target}.md` with frontmatter:
  ```yaml
  ---
  type: stakeholder-snippet
  scope: {unit|portfolio|control|framework}
  target: {target string}
  generated: {YYYY-MM-DD}
  generator: claude-code /control-translate
  sources: [<per-unit context file>, <framework references used>]
  ---
  ```

### 8. Quality loop

Show the user the draft. Ask:
- *Is the root cause right?* (most common correction — per-unit context memory may be stale)
- *Is the action right?* (ownership and timing change quarter to quarter)
- *Confidence tags accurate?*

If the user corrects the root cause → save the corrected version to the per-unit context memory in the same turn (save-on-mention). The next `/control-translate` and the next `/quarterly-report-prep` both benefit.

## Things this command must NEVER do

- **Compute scores.** The dashboard is canonical. If the user hasn't given you a rating, ask for one — don't infer.
- **Fabricate root cause.** If the per-unit context memory doesn't have the unit/control, ask. Never write *"likely lacks a formal process"* without source.
- **Default to URN citation in `framework` mode.** Standards are context, not citation. Output is informed commentary; URN/clause references live in the provenance footer for auditability. URN-as-body is opt-in only when the audience genuinely needs the clause number (e.g. customer due-diligence questionnaire).
- **Touch the source-of-truth system.** This is a vault-side reasoning skill. Vault holds REASONING; dashboard holds DECISIONS.
- **Edit per-unit context memory silently.** Every save is acknowledged in chat (save-on-mention rule).
- **Generate the full quarterly report.** That's `/quarterly-report-prep`. This skill produces snippets that the quarterly run consumes, not the whole report.

## When to use

- Customer or insurer asks "where do we stand on {control}" mid-quarter — generate the paragraph, paste into the response.
- An audit / board appendix needs a single-unit paragraph between cycles.
- Governance / policy / guidance drafting needs framework-informed framing on a topic.
- Reviewing draft board commentary written by someone else — paste their version, ask `/control-translate` to re-apply the lens, compare.

## When NOT to use

- For the actual quarterly report assembly — use `/quarterly-report-prep`.
- For a control rating that isn't in the most recent dashboard snapshot — get the paste first via `/quarterly-report-prep` step 1, then come back.
- For technical detail directed at the security team — wrong audience. The paragraph this skill produces strips technical depth on purpose.
- For policy text — the Guidelines / Procedure / Policy distinction matters. This skill produces commentary on operational posture, not binding policy text.

## Co-change couplings

When this skill writes a snippet file, consider:
- Has per-unit context memory been updated this run? Did `MEMORY.md` need re-indexing?
- Is the snippet recurring enough that the underlying unit context has drifted from the dashboard? Flag for a dashboard re-check.

## See also

- `.claude/commands/quarterly-report-prep.md` — full quarterly ritual
- `07-References/frameworks/README.md` — framework reference library curation
- `confidence-tags.md` — convention used on every derived claim
- User memory (populated during first-run): your per-unit context file, `feedback_board_reporting.md`, `feedback_security_guidance_lens.md`, `feedback_frameworks_as_context.md`
