---
description: Independent false-positive verification gate for security findings — re-reads each cited file:line, reproduces the issue, downgrades or withdraws findings that don't ground in real code.
argument-hint: "<finding-block-or-report-path> — e.g. '\"SQL injection in app.py:42 — user input concatenated\"' OR '08-Projects/<project>/security-reviews/<date>-<path>.md'"
allowed-tools: Read, Glob, Grep
---

# /fp-check — false-positive verification gate

Independent FP-verification pass over security findings. Reads each cited `file:line`, reproduces the issue, checks for compensating context (upstream sanitisation, framework auto-escape, registered exemption), and grades reproducibility. Read-only — never edits code.

Sibling skill: `/secure-code-review`, `/owasp-llm-review`, and `/owasp-agentic-review` produce findings; this skill verifies them before they're trusted. Operationalises the no-assumptions rule — security claims must be evidence-backed.

## When to use

- After `/secure-code-review` on a 🔴 finding, before it blocks merge.
- After `/owasp-llm-review` or `/owasp-agentic-review` on any 🔴 finding.
- Before reporting any security claim to a developer or stakeholder.
- Before adding a finding to a `security-reviews/` artifact.

## When NOT to use

- For 🟡 warnings — they're already calibrated as "needs context". Run FP-check only on 🔴.
- For deterministic-script exemptions already recorded in `07-References/security-baselines.md` §Exemptions — read that register first.
- For findings without a `file:line` citation — upstream skills shouldn't produce those; this skill assumes citation discipline.
- For design / architectural concerns — different shape; raise in a decision record instead.

## Process — strict order

### 1. Parse input

`$ARGUMENTS` — required. Two forms accepted:
- **Inline finding** — quoted text containing one or more `<file>:<line>` references plus a claim
- **Report path** — path to a `security-reviews/*.md` artifact (extract all 🔴 findings)

If empty: ask *"Paste a finding or a security-reviews path. Need at least one `file:line` citation."*

### 2. Confirm citation grounding

For each finding:
- Read the cited file at the cited line (±20 lines context).
- Confirm the cited line exists and contains code matching the claim. If the line is blank, a comment, an import, or unrelated code → **the citation is fabricated** → WITHDRAW.
- Confirm the cited pattern is present: grep the specific concern (`subprocess.shell=True`, `dangerouslySetInnerHTML`, `eval(`, untrusted-input concatenation, raw MCP response forwarding, etc.).

### 3. Check compensating context

For each finding that grounds:
- **Upstream sanitisation** — is there a validator / schema / `assert` / framework auto-escape between the untrusted input and the cited line? Grep up to the function entry; if found, the finding is mitigated → DOWNGRADE to 🟡 or WITHDRAW with reason.
- **Framework default-safe** — React / Svelte auto-escape, Pydantic / Zod validation in route handlers, ORM parametrised queries — default-safe paths. → DOWNGRADE / WITHDRAW.
- **Registered exemption** — read `07-References/security-baselines.md` §Exemptions. If the path or pattern has a documented exemption, → WITHDRAW citing the exemption ID.
- **Test / fixture code** — paths under `tests/`, `fixtures/`, `__mocks__/`, `*.test.*` are generally exempt from C-1..C-8 (different threat model). → WITHDRAW unless the fixture *is* the production attack surface.

### 4. Re-grade

| Original | Verification result | New grade |
|---|---|---|
| 🔴 | Citation grounds + no exemption + no mitigation | 🔴 VERIFIED |
| 🔴 | Upstream mitigation found | 🟡 DOWNGRADED — name the mitigation |
| 🔴 | Exemption registered | 🟢 WITHDRAWN — cite exemption ID |
| 🔴 | Citation does not ground | 🟢 WITHDRAWN — finding fabricated |

### 5. Output

```
## FP-check — <input source>
**Findings reviewed:** N
**Verified:** N  |  **Downgraded:** N  |  **Withdrawn:** N

### 🔴 VERIFIED
- **<title>** — `<file>:<line>` — original claim holds. Evidence: <quoted snippet>. No upstream mitigation, no exemption.

### 🟡 DOWNGRADED
- **<title>** — `<file>:<line>` — 🔴 → 🟡. Reason: <upstream sanitisation at <file>:<line> / framework auto-escape / etc.>.

### 🟢 WITHDRAWN
- **<title>** — `<file>:<line>` — 🔴 → 🟢. Reason: <exemption ID / fabricated citation / test fixture>.
```

If the user says "save it" → append to the source `security-reviews/*.md` artifact under a `## FP-check pass — {YYYY-MM-DD}` heading. **Don't overwrite the original verdict** — add the FP-pass alongside it so the audit trail survives.

### 6. Honesty check

If you're unsure whether a mitigation is real, do NOT downgrade. State *"Can't determine if <X> is mitigated upstream — need human review"*. 🔴 honesty beats false 🟢 confidence. Treating an unfounded finding as VERIFIED is recoverable; falsely WITHDRAWING a real one is not.

## Things this skill must NEVER do

- **Edit the code being verified.** Read-only.
- **Add new findings.** Only re-grade existing ones — adding findings is `/secure-code-review`, `/owasp-llm-review`, and `/owasp-agentic-review`'s job.
- **Downgrade without naming the specific mitigation.** "Looks fine" is not an answer.
- **Withdraw without citing an exemption ID or proving the citation doesn't ground.** Vague withdrawals are how real findings get lost.
- **Re-grade findings on captured content** (`00-Inbox/_captured/**`). Captures are untrusted by design.

## Co-change couplings

- **Repeated WITHDRAW for the same pattern across runs** → tighten the upstream check in `/secure-code-review` / `/owasp-llm-review` / `/owasp-agentic-review` so it stops producing the false positive. Rule fix, not effort.
- **New exemption discovered** → register in `07-References/security-baselines.md` §Exemptions, not just in this skill's output.
- **Verified finding** → upstream of any deploy gate per `feedback_security_baselines.md`.

## See also

- `.claude/commands/secure-code-review.md` — general secure-coding skill that produces findings this one verifies
- `.claude/commands/owasp-llm-review.md` — LLM01-LLM10 lens
- `.claude/commands/owasp-agentic-review.md` — ASI01-ASI10 lens
- `07-References/security-baselines.md` — C-1..C-8 + §Exemptions register
- `confidence-tags.md` — convention used on every derived claim
