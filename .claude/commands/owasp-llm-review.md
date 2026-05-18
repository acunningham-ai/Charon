---
description: OWASP Top 10 for LLM Applications 2025 (LLM01-LLM10) review over LLM-consuming code — prompt injection, sensitive info disclosure, supply chain, data/model poisoning, improper output handling, excessive agency, system prompt leakage, vector weaknesses, misinformation, unbounded consumption.
argument-hint: "<path> [--diff] — e.g. 'capture-pipeline' | '08-Projects/<llm-service>/bot' | 'scripts/hooks --diff'"
allowed-tools: Read, Glob, Grep
---

# /owasp-llm-review — LLM01-LLM10 lens on LLM-consuming code

Reviews code through OWASP Top 10 for LLM Applications 2025 (LLM01-LLM10). Distinct from `/owasp-agentic-review`:

- **This skill** — code that USES an LLM as a component (a service calls Claude to classify items, capture pipeline runs `claude -p`, hook scripts pass content to a model). **Application lens.**
- **owasp-agentic-review** — code where the LLM has agentic autonomy (tool dispatch, sub-agents, persistent memory, autonomous decisions). **Agent lens.**

Both lenses often apply. If the code under review has agentic surface, run both.

Output: structured report with 🟢/🟡/🔴 findings, `file:line` citations, LLM category tag per finding, hand-off to `/fp-check` on 🔴 findings.

## Scope

Targets:
- **`capture-pipeline/**`** — scheduled runners with LLM calls
- **`08-Projects/<llm-service>/**`** — LLM-driven workflows
- **`scripts/hooks/**`** — hook-side LLM calls (C-6 hygiene)
- **`.claude/commands/**`** — skill files (narrower scope; see §1a)
- **Any code that imports `anthropic` / calls `client.messages.create` / invokes `claude -p`**

Out of scope: pure static code with no LLM calls (use `/secure-code-review`); captured content review (C-7).

## When to use

- Before deploying a new LLM-consuming workflow.
- After material changes to an LLM-driven service's classification logic.
- When an app adds AI features.
- Quarterly audit pass over LLM-callers in the harness.

## When NOT to use

- For code with no LLM calls — `/secure-code-review` covers those.
- As a substitute for `/owasp-agentic-review` on agentic code — run both.
- For captured-content vetting — that's C-7 at the pipeline source.

## Process — strict order

### 1. Resolve context

- Confirm path exists. If not, stop and ask.
- Identify LLM-consumer surface:
  - **LLM call sites** — `claude -p`, `client.messages.create`, `anthropic.messages`, `Anthropic(`
  - **Prompt construction** — `--system-prompt`, `system=`, string templates with user input
  - **Output consumption** — code that reads LLM output and uses it downstream
  - **RAG / context injection** — retrieved content passed into the prompt
  - **Budget controls** — `--max-budget-usd`, token limits, retry/backoff logic

If no LLM-consumer surface: report *"No LLM-consumer surface in <path>. Try `/secure-code-review` for general checks."* and stop.

### 1a. Applicability — scope checks to the path

| Path | LLM categories that apply |
|---|---|
| `.claude/commands/**` (slash-command skill files) | LLM01 (skill-body framing only), LLM02, LLM03, LLM05, LLM06, LLM07, LLM09. LLM04 partial. LLM10 N/A (budget caps live in scheduled callers). LLM08 N/A unless embeddings present. |
| `capture-pipeline/**` + scheduled runners | All except LLM08 unless embeddings present (full unattended LLM-app threat model) |
| `scripts/hooks/**` | LLM01 (C-6 hook-side), LLM02, LLM05, LLM06, LLM07, LLM09 |
| LLM-driven service paths | All except LLM08 unless embeddings present |

**LLM08 — Vector and Embedding Weaknesses** is **N/A unless the harness uses embeddings** (Claude-only stacks without vector stores typically don't). If a feature adds embeddings, re-introduce LLM08.

**Cite N/A categories in the verdict block** ("LLM08, LLM10 — N/A at this path"). Do NOT generate findings against N/A categories.

### 2. Run LLM01-LLM10 checks

Each finding cites a `file:line` and tags one LLM category.

**Search discipline:** case-insensitive (`-i`) on security terms (`UNTRUSTED`/`untrusted`, `injection`, `secret`, `password`, `api[_-]?key`, `token`, `bearer`). Case-sensitive misses cause fabricated findings.

**LLM01 — Prompt Injection** *(separate trusted instructions from untrusted data, filter outputs)*
- System prompt contains explicit injection-recognition rule + protected-file allowlist (C-1). Grep `--system-prompt`, `system=`. 🔴 absent on unattended LLM calls.
- Untrusted input (external data feeds, email body, user input, captured content) wrapped in delimited "UNTRUSTED" blocks before reaching the LLM. 🔴 on raw untrusted strings concatenated into prompt.
- Output filtering: LLM output checked for unexpected control characters / instruction-shaped content before downstream use. 🟡 if absent.

**LLM02 — Sensitive Information Disclosure** *(sanitise context, strip PII)*
- Data with PII (TFN, SSN, full DOB, account numbers) is NEVER unredacted in LLM prompts. 🔴 on unredacted PII in prompt construction.
- No credentials in system prompts or context (overlaps LLM07). 🔴 if API keys / passwords / hostnames-with-creds in prompt strings.
- RAG retrievals from sensitive sources scrubbed of secrets before LLM consumption. 🟡 if scrubber absent.

**LLM03 — Supply Chain** *(model provenance + third-party hubs)*
- LLM invoked through Anthropic SDK or `claude -p` only (provenance: Anthropic). 🔴 on arbitrary HuggingFace pulls / unvetted model endpoints in production paths.
- **Third-party** MCP servers in `.mcp.json` pass the MCP evaluation rubric. 🟡 if any third-party MCP lacks documented eval. **Local-internal MCPs** (`scripts/mcp/**`) exempt — review via `/secure-code-review` against source.
- No `curl ... | bash` install of LLM-related frameworks. 🔴 on framework auto-install.

**LLM04 — Data and Model Poisoning** *(validate sources, anomaly-detect)*
- No fine-tuning on uncurated data.
- Captured content (untrusted) NOT auto-incorporated into authoritative reference docs without user review. 🔴 on direct auto-write from `_captured/**` to `MEMORY.md` / `CLAUDE.md` / `07-References/**` / `TODO.md`.
- Anomaly detection on incoming captures (unusually large items, injection-shaped content, abnormal frequency). 🟡 if absent.

**LLM05 — Improper Output Handling** *(treat output as untrusted)*
- LLM output validated / sanitised before being used as input to another system. 🟡 if no validation step.
- No `eval(LLM_output)` / `exec(LLM_output)` / `subprocess(shell=True, cmd=LLM_output)`. 🔴 on direct execution of LLM output.
- Generated SQL / regex / file paths from LLM output validated against allowlist. 🟡 if absent.
- Structured-output writers (frontmatter values, tags, labels, classifications) constrained to closed enum (C-3.1). 🟡 on free-text writes to structured fields.

**LLM06 — Excessive Agency** *(minimise tools/permissions, require approval)*
- `allowedTools` minimal (C-2). 🔴 on `Bash` allowed AND no deterministic wrapper invocation visible in body. 🟡 if Bash granted but never used.
- Destructive / state-changing actions require human approval — write-path validation hook gates writes. 🔴 if Write enabled without allowlist.
- Tools granted match actual usage in body. 🟡 if granted but not invoked.

**LLM07 — System Prompt Leakage** *(no secrets/keys/auth in prompt)*
- No credentials in `--system-prompt` flags or `system=` parameter strings. Grep `--system-prompt.*pass`, `system=.*key`, `system=.*token`. 🔴 on any match.
- No API keys, passwords, hostnames-with-creds, secret-bearing URLs in prompt body literals. 🔴 on match.
- Credentials read at moment of need from configured secrets dir — never embedded in prompt template. 🟢 confirms pattern.

**LLM08 — Vector and Embedding Weaknesses** — applies only if the harness uses embeddings. Tenant-isolate vector stores, access-control on retrieval, sanitise retrieved content before prompt injection.

**LLM09 — Misinformation** *(cite sources, surface confidence, AI provenance)*
- Stakeholder-facing outputs (board, exec, governance docs) carry confidence tags 🟢/🟡/🔴 per `confidence-tags.md`. 🟡 if outputs lack provenance markers.
- Source citations on board reports / exec briefs / governance synthesis. 🟡 if absent on derived claims.
- AI-provenance disclosure on user-facing material where appropriate. 🟡 if absent.

**LLM10 — Unbounded Consumption** *(rate limits, token caps, tool-call caps)*
- Budget cap on every unattended LLM call (C-4). 🔴 if missing on unattended invocations.
- Loop / retry logic has step counter or depth limit. 🟡 if unbounded loop possible.
- Provider extra-usage cap monitoring — alert recipients defined. 🟢 confirms.

### 3. Confidence-tag findings

- 🔴 violates LLM category + no compensating control — blocks merge
- 🟡 partial coverage / risk-flagged — needs review or explicit acceptance
- 🟢 load-bearing pass — include only for material passes; skip noise

### 4. Output

```
## LLM-app security review — <path>
**Verdict:** PASS / PASS-WITH-WARNINGS / FAIL
**LLM-consumer surfaces present:** <call sites | prompt construction | output consumption | RAG | budget controls>
**LLM categories fired:** <LLM01..LLM10 — which fired>
**LLM categories N/A at this path:** <e.g. LLM08, LLM10>
**Files reviewed:** <count>

### 🔴 Critical findings
- **[LLM<NN>] <title>** — `<file>:<line>`
  - **Why it matters:** <one sentence linking to LLM category>
  - **Fix:** <one sentence — control to add>
  - **FP-check:** run `/fp-check "<finding citation>"` before treating as block

### 🟡 Warnings
- (same shape, no FP-check requirement)

### 🟢 Load-bearing passes
- (same shape, no Fix)

### Recommendations
- <ordered, only if the user will act>

### Companion review
- If agentic surface also present, run `/owasp-agentic-review <path>` for the ASI01-ASI10 lens.
```

If the user says "save it" → write to `08-Projects/<project>/security-reviews/{YYYY-MM-DD}-llm-<path-slug>.md`.

### 5. Hand-off

- 🔴 findings → run `/fp-check` before blocking merge
- Agentic surface present → run `/owasp-agentic-review` for complementary ASI lens
- General secure-coding gap → run `/secure-code-review` for C-1..C-8 + general checks

## Things this skill must NEVER do

- **Edit the code being reviewed.** Read-only.
- **Fabricate LLM category mappings.** If a finding doesn't map cleanly, don't force it — tag as "general LLM concern" and explain.
- **Skip a category that applies** (per §1a). Each applicable LLM either has a finding, a load-bearing pass, or a documented exemption.
- **Generate findings against N/A categories.**
- **Use case-sensitive grep on security terms** — always `-i`.
- **Apply LLM03 supply-chain checks to local-internal MCPs.** `scripts/mcp/**` is local code; use `/secure-code-review`.
- **Re-derive ASI checks here.** Overlap categories (LLM01/05/06/09) cover the LLM-app lens; agentic-specific behaviour is `/owasp-agentic-review`'s job.
- **Flag `Bash` grants as 🔴 when the skill body shows a deterministic wrapper invocation.** The wrapper IS the justification.

## Co-change couplings

- **Finding pattern recurs across projects** → consider promoting to a path-specific rule in `.claude/rules/` or a new C-* control in `07-References/security-baselines.md`.
- **LLM08 stops being N/A** (future embedding adoption) → update §1a applicability matrix and remove the N/A exception.
- **New LLM-consumer added** → re-run this skill plus `/owasp-agentic-review` (if agentic) plus `/secure-code-review` before live.

## See also

- `07-References/security-baselines.md` — C-1..C-8 (sibling harness-hygiene lens)
- `.claude/commands/secure-code-review.md` — general secure-coding sibling
- `.claude/commands/owasp-agentic-review.md` — ASI01-ASI10 agentic lens
- `.claude/commands/fp-check.md` — false-positive verification gate
- `confidence-tags.md` — convention used on every derived claim
