---
paths:
  - "08-Projects/AI-Governance/**"
  - "08-Projects/*Governance*/**"
keywords:
  - "ai governance"
  - "ai security guidelines"
  - "ai usage policy"
  - "policy on the usage of ai tools"
  - "governance forum"
  - "ai governance forum"
  - "ai governance working group"
  - "ai governance group"
  - "approving authorities"
  - "ai champion"
  - "ai champions"
---

# AI Governance rules

Auto-loaded under `08-Projects/AI-Governance/**` or on governance keyword match.

**This rule ships the universal patterns.** Your org-specific layer — the actual document names and owners, your approving-authority composition, your reviewer roster, your forum schedule — comes from your own memory files, populated during first-run from your org chart.

## Hard rules — apply on every AI Governance artefact

| Rule | What it means |
|---|---|
| **Two layers — never conflate** | Most orgs have at least two AI documents: a binding **Policy** (legal / head-office owned) and an advisory **Guidelines** (function owned, often CISO/security). Confirm which doc the edit targets before changing anything. Reviewers conflate them; you can't. |
| **Guidelines are advisory, not binding** | An org-unit that follows Policy + Procedure and never reads the Guidelines is fully compliant. Guidelines exist to add **security thinking**, not to mirror Policy obligations. |
| **5-question security-guidance lens** | Every substantive Guidelines section must let the reader come away with: (1) what good looks like, (2) where to start, (3) the risks, (4) how to think about mitigating them, (5) who to talk to. If ≥3 come up empty, the section needs rework. |
| **Document layering** | Policy / Guidelines / Procedure are three layers with different owners and cadences. Guidelines **reference** policy and **signpost** procedure owners — don't embed procedure. Embedding procedure forces re-version on every workflow tweak → docs go stale → lose authority. |
| **CISO office is advisory, not approver** | Frame CISO contributions as **risk identification, risk communication, mitigation advice**. Never "architecture decision", never "tool approval". Approval authority lives elsewhere (your org's named Approving Authorities — configured during first-run). |
| **Don't force a tool class** | In stakeholder-facing artefacts, name the **risk + pattern**, never name a class of tool ("add a gateway", "use a runtime enforcement layer"). The reader asks "how?" — don't pre-empt the conversation. |
| **"X or similar tool" framing** | When tooling examples are needed: "an SCA tool (e.g. Snyk, or similar tool)". The word "tool" is load-bearing. Your configured tool exception (if any) is the one named exception; everything else gets the framing. |
| **No top-down policy template by default** | Unless your org explicitly publishes one, don't imply head office pushes down a policy template. Reframe "adopt the baseline" → "develop an org-unit-appropriate policy proportionate to size; advisory engagement available". |
| **Frameworks are context, not citation** | ISO 42001, NIST AI RMF, EU AI Act, etc. — use as **scaffolding for thinking**, not URN/clause quotes to paste. Default output is informed commentary; URN citation only when the audience genuinely needs it (formal customer due-diligence, audit response). |
| **Audience-tailored framing** | For internal leadership who live the operating model: drop tool-governance / cost orientation. Keep that framing for external readers only. Your audience tiers live in your own memory. |
| **Credit reviewer attribution inline** | Every `<!-- CHANGED vX.Y: ... -->` comment that reflects reviewer-driven feedback names the reviewer(s) by first name. Multi-source edits cite all contributors. Reviewers disengage when their input disappears into a black box. |

## Document layering principle

Three distinct layers, never mix:

| Layer | What it is | Owner | Cadence |
|---|---|---|---|
| **Policy** | Mandates, binding obligations, breach consequences | Legal / head office | Slow (yearly+) |
| **Guidelines / Standards** | Best-practice operating model | Function owner (CISO for security) | Medium (quarterly) |
| **Procedures** | Step-by-step workflows | The function that runs them | Fast |

**Why separate:** procedures change far more often than guidelines or policy. Embedding procedure into guidelines forces a re-version on every workflow tweak. **Guidelines reference policy + signpost procedure owners; they do not embed procedure.**

## Triage litmus test for reviewer feedback

When a reviewer says *"this isn't in the Guidelines"*:

| Ask shape | Verdict |
|---|---|
| **Cross-reference** ("Guidelines don't mention Policy requires X") | **Accept** — make Policy obligation unmissable |
| **Process-embed** ("Guidelines don't describe the intake workflow") | **Push back** — workflow lives with the function that runs it |
| **Wording** ("'Approval' overstates this role's authority — should be 'coordination'") | **Accept on wording** |
| **Structural** ("Section X doesn't fit this audience") | **Evaluate on merits** |

## Intake / coordination roles vs Approving Authorities

Many orgs have an intake/coordination role (often called an "AI Champion" or similar) that is distinct from formal approval. The pattern to watch:

- Intake/coordination roles **maintain the record** of AI tools in use, **escalate** new use cases to the right authority, **coordinate** training — they do NOT approve.
- Approving Authorities (your org's configured composition — typically some combination of BU/department lead, executive sponsor, senior legal counsel) own approval per your Policy.
- Never describe Guidelines as having approval authority — they don't; the Policy does.

## Reframing patterns — use these everywhere in the Guidelines

| ❌ Wrong | ✅ Right |
|---|---|
| "CISO office owns the security architecture call" | "CISO office owns the security risk call" |
| "CISO provides architecture review" | "CISO identifies security risk and advises on mitigation" |
| "Intake role + CISO review" | "Intake role + CISO advice" |
| "Adopt the head-office baseline security policy" | "Develop an org-unit-appropriate cyber-security policy proportionate to size. Advisory engagement available." |
| "Deploy <Vendor> for <X>" | "Deploy a <capability> tool (e.g. <Vendor>, or similar tool) — must support <auditable requirement>" |
| "Add a runtime enforcement layer" (in stakeholder artefact) | "Address the unconstrained outbound fetch" / "Isolate credentials from agent context" |
| "Per ISO 42001 A.10.3 suppliers must…" (in stakeholder body) | "When a supplier provides an AI capability, the security frame is: …" + small `Drawn from: ISO 42001 A.10.3` footer if needed |

## How to run — supporting skills

| Skill | When | What it produces |
|---|---|---|
| `/control-translate ai-frame <framework> <topic>` | Ad-hoc — need framework-informed commentary on a topic (supplier risk, patching, MFA) | One section in voice: frame / risks / what good looks like / where to start / mitigations / who to talk to. URN refs demoted to provenance footer. |
| `/draft-linkedin` | Pulling a forum or Guidelines insight into a LinkedIn post | Voice-matched draft. Not the place to lift talk content verbatim — use as premise. |
| `/promote-rule` | Repeated reviewer feedback pattern showing up in multiple Guidelines sections | Promotion-gradient — surface candidates for path-specific rules. |

**Flow for a Guidelines revision cycle:**

1. Capture each reviewer's feedback into `08-Projects/AI-Governance/<date>-<reviewer>-feedback-on-<version>.md`
2. Triage each item via the litmus test (cross-ref / process-embed / wording / structural)
3. Apply changes with inline `<!-- CHANGED vX.Y: ... -->` comments naming reviewers by first name
4. Run the 5-question lens over each substantive section
5. Apply the reframing patterns — sweep for tool-class language, "head-office baseline" phrasing, "CISO owns architecture", URN citations
6. Circulate with directed cover notes to each named reviewer
7. Forum ratification (date comes from your authoritative date register — never inferred from filenames)

## Anti-patterns (auto-flag if I'm drifting)

- **Calling the Guidelines binding** — they're advisory. Only the Policy binds.
- **Stating "the Guidelines require X"** — Guidelines don't require; they advise. Policy requires.
- **Framing CISO as "architecture decision" owner** — risk identification + communication + mitigation advice only.
- **Naming a tool class in a stakeholder artefact** — name risk + pattern.
- **Dropping a vendor name in a recommendation without "or similar tool"** — except your configured exception.
- **Implying head office hands you a policy template** — unless they explicitly do.
- **URN citation as the body of a stakeholder section** — frame in voice; URN goes in provenance footer if needed.
- **"Let me explain the operating model"** introductory paragraphs for audiences who already live it.
- **Embedding procedure into the Guidelines** — workflow tweaks force re-version, doc goes stale.
- **Changing a section without crediting the reviewer** whose feedback drove the change.
- **Inferring the forum date from a filename** — check your authoritative date register.

## Co-change couplings

- **New reviewer added** → add to your reviewer-lens memory file with their lens
- **New Policy version released** → re-check Approving Authorities composition, Appendix references
- **New AI Tool category in operational use** → check whether current Guidelines carve-outs still cover it
- **Framework newly relevant** (e.g. new ISO release) → consider whether it changes how the 5-question lens fires
- **Substantive memory rule update touching these rules** → update this file's hard-rules table in the same change

## See also

- `confidence-tags.md` — convention used on every derived claim
- `board-reporting.md` — adjacent rule; same audience-tailoring discipline
- `.claude/commands/control-translate.md` — `ai-frame` mode for framework-informed commentary
- `.claude/commands/draft-linkedin.md` — when a Guidelines insight becomes a post
- User memory (populated during first-run): your `reference_ai_policy_landscape.md`, `reference_approving_authorities.md`, `reference_reviewer_lenses.md`, `project_*_forum_dates.md`, `feedback_security_guidance_lens.md`, `feedback_doc_layering_principle.md`, `feedback_frameworks_as_context.md`
