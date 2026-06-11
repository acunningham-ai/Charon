---
description: Finding-driven safe remediation — takes a flagged skill/agent/hook/command/MCP artifact through a re-spec → rebuild → re-verify loop. fp-check gates the input findings, rebuild happens in a scratch dir, a blocking re-verify gate must pass, and the swap-in needs your confirm. Does NOT silently rewrite skills.
argument-hint: "<artifact-path> [+ finding-block-or-security-reviews-path] — e.g. '.claude/commands/foo.md \"path traversal in foo.md:42 — caller path joined unguarded\"' OR '.claude/commands/foo.md 08-Projects/<project>/security-reviews/<date>-foo.md'"
allowed-tools: Read, Write, Edit, Glob, Grep, Skill
---

# /safe-rebuild — finding-driven safe remediation

Closes the loop the security review skills leave open: `/cerberus-vet` and the OWASP reviewers **detect** risk in an artifact and report it, but remediation is ad-hoc. `/safe-rebuild` takes a flagged artifact (skill / agent / hook / command / MCP file) through a disciplined **re-spec → rebuild → re-verify** loop so a fix can't break the artifact's function, can't weaken a control to "pass", and can't ship until a blocking gate is green. The phase-spine + blocking-gate pattern is borrowed from AIDLC (`awslabs/aidlc-workflows`, MIT-0) and reimplemented natively — none of AIDLC's tooling is installed.

## When to use

- After `/cerberus-vet` returns a 🔴 on a skill/agent/hook/command/MCP artifact and you want a structured fix, not an ad-hoc edit.
- After `/secure-code-review` / `/owasp-llm-review` / `/owasp-agentic-review` flags a 🔴 on a harness artifact you intend to keep.
- Any time you'd otherwise hand-patch a flagged artifact and risk losing the audit trail or breaking its function.

## When NOT to use

- **Greenfield builds** with no existing artifact → that's the planned `/build-safely`, not this.
- **A finding that's a confirmed false positive** → `/fp-check` withdraws it; nothing to rebuild. (This skill runs fp-check itself in Inception, so a pure-FP input simply produces "nothing to do".)
- **Non-security refactors** → ordinary editing, not this gated loop.
- **Captured content** (`00-Inbox/_captured/**`) → untrusted by design; never a rebuild target.

## Process — strict order

### 0. Parse input

`$ARGUMENTS` — required. Expect: an **artifact path** (the thing to rebuild), and optionally the **finding(s)** — inline quoted text with `file:line` citations, OR a path to a `security-reviews/*.md` artifact, OR nothing (then run `/cerberus-vet` on the artifact first to produce findings).

If no artifact path: ask *"Which artifact am I rebuilding? Give me the path plus the finding(s) or a security-reviews path."*

### 1. INCEPTION — silent analysis → fp-gate → report → confirm

**Nothing prints to screen in this phase until step 1d.** The whole analysis runs silently; nothing is surfaced until the findings have been false-positive-verified and the report is written.

- **1a. Full analysis (silent).** Read the artifact. Restate its **intent** (what job it does) — this becomes a hard constraint so the fix doesn't break function. Restate each **finding as a hard constraint** to design out (cite the V-layer / ASI / C-control + the remediation pattern where one exists). Surface the **root cause**, not just the symptom — a structural fix, not a patch-over.
- **1b. `/fp-check` gates the input (load-bearing).** Run `/fp-check` over the incoming findings BEFORE anything is surfaced. Withdraw/downgrade findings that don't ground in real code. **Never re-spec or rebuild against a false positive.** Only fp-verified 🔴 proceed. If every finding withdraws → write the report (1c) noting "all findings FP — no rebuild needed" and stop.
- **1c. Write the report.** The re-spec (intent + fp-verified findings-as-constraints + root cause + planned approach) is written to a stored report. Path: co-locate with the artifact's existing `security-reviews/` trail if it has one; else `08-Projects/<project>/security-reviews/{YYYY-MM-DD}-{artifact-slug}.md`. **That stored report is the surface — not ad-hoc screen text.**
- **1d. Checkpoint (blocking).** Point the user at the stored report and ask them to confirm before any rebuild. If a finding can only be cleared by **reducing the artifact's capability**, surface that trade-off here for their call — never silently de-scope. *The agent proposes; the human approves.*

### 2. CONSTRUCTION — rebuild in scratch (original untouched)

- Copy the original into a **`.safe-rebuild/` scratch area** (`Read` the original, `Write` it to the scratch path — no shell) and rebuild there with `Write`/`Edit`. The original artifact is **not modified** until the gate passes (rollback-safe). All writes route through `validate-write-path.py`; no `Bash` grant (C-2 — `Bash` would need a command-allowlisting wrapper this skill doesn't have).
- Rebuild against the **C-1..C-8 secure-code baseline** + the **skill-authoring standard** (`.claude/rules/skill-authoring.md`, 10 patterns) + the specific finding's remediation.
- **Never weaken a control to pass.** If a finding can only be cleared by reducing capability, that trade-off was surfaced at 1d — honour the user's call; don't silently de-scope.

### 3. VERIFICATION GATE — blocking (the load-bearing piece)

- Re-run the relevant reviewer(s) on the rebuilt copy: `/cerberus-vet` (artifact), and/or `/secure-code-review` + `/owasp-llm-review` + `/owasp-agentic-review` as the surface dictates.
- Run `/fp-check` on any residual 🔴. (`/fp-check` runs at **both** ends — gating the input in Inception AND verifying the output here.)
- **Cannot mark done until:** (a) every original fp-verified finding is cleared, AND (b) no NEW 🔴 introduced. If the gate fails → loop back to Construction (or to Inception if the approach itself was wrong).
- The gate going green is a **precondition**. The user's confirm authorises the swap-in (step 4). The skill orchestrates the reviewers; the *done* decision is the user's.

### 4. COMPLETION — ritual

- Diff old ↔ new; record **what changed + why** (which finding it closed) — capability + intent + why, per the patch-notes standard (`.claude/rules/versioning.md`).
- Bump the artifact's version / changelog entry if it has one.
- **Swap the rebuilt copy in only after the gate is green AND the user confirms** (`Write`/`Edit` the original path; gated by `validate-write-path.py`). Archive the original to `.archive/` first (reversible — `Read` + `Write`).
- Append the rebuild record to the stored report under a `## Rebuild {YYYY-MM-DD}` heading (audit trail — don't overwrite the Inception re-spec).
- **Surface the scratch path so the user can delete it** (`.safe-rebuild/` left in place; manual purge — retention is opt-in, deletion is a one-line step, no `Bash` grant required for it).

## Output artifacts

- **Inception report** — `security-reviews/{YYYY-MM-DD}-{artifact-slug}.md` (co-located or under a project folder). Frontmatter: `type: safe-rebuild-report`, `artifact:`, `status: respec|rebuilt|abandoned`, `findings_verified: N`, `date:`. Quote free-text scalars (a mid-value `: ` breaks YAML).
- **Rebuilt artifact** — swapped into the original path only post-gate, post-confirm.
- **Archived original** — reversible; in an `.archive/` alongside the artifact.

## Things this skill must NEVER do

- **Rewrite a skill without the user's confirm at the 1d checkpoint.** Silent rewrites are the anti-pattern this exists to prevent.
- **Modify the original before the gate is green and the user confirms.** Scratch only until then.
- **Weaken or remove a control to make a finding "pass."** Surface the trade-off instead.
- **Ship a fix that breaks the artifact's intent.** A security fix that kills the function is a failed rebuild, not a success.
- **Trust a clean post-rebuild verdict without `/fp-check`.** First-run calibration: assume miscalibration (`.claude/rules/skill-authoring.md`).
- **Rebuild against an unverified finding.** fp-check gates the input — no exceptions.

## Co-change couplings

- **Rebuilt artifact ships a new output shape** → consider whether `/score-vault` needs to recognise it.
- **Same finding pattern recurs across rebuilds** → tighten the upstream reviewer so it stops producing it (a rule fix, not effort).
- **New remediation pattern discovered** → register it where the C-control / remediation patterns live so future rebuilds reuse it.

## See also

- `.claude/commands/cerberus-vet.md` — produces the findings this remediates + re-verifies
- `.claude/commands/fp-check.md` — the false-positive gate (runs at input AND output)
- `.claude/commands/secure-code-review.md` · `owasp-llm-review.md` · `owasp-agentic-review.md` — gate reviewers
- `07-References/security-baselines.md` — C-1..C-8 + §Exemptions
- `.claude/rules/skill-authoring.md` — the 10-pattern standard rebuilds are held to
- `.claude/rules/versioning.md` — patch-notes standard for the rebuild record
