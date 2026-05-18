---
description: OWASP Agentic AI Security 2026 (ASI01-ASI10) review over agentic code — goal hijack, tool misuse, identity/privilege abuse, supply chain, code execution, memory poisoning, inter-agent comms, cascading failures, human-agent trust, rogue agents.
argument-hint: "<path> [--diff] — e.g. 'scripts/hooks' | '08-Projects/<agent-service>/bot' | '.claude/commands --diff'"
allowed-tools: Read, Glob, Grep
---

# /owasp-agentic-review — ASI01-ASI10 lens on agentic code

Reviews code through OWASP Agentic AI Security 2026 (ASI01-ASI10). Distinct from `/secure-code-review`'s C-1..C-8 baseline — that covers harness LLM hygiene; this covers attacks against multi-agent / autonomous-agent behaviour. Distinct from general OWASP Top 10 — that covers traditional web vulns; this covers agent-specific threats.

Output: structured report with 🟢/🟡/🔴 findings, `file:line` citations, ASI category tag per finding, and a recommendation to run `/fp-check` on 🔴 findings before they block merge.

## Scope

Targets:
- **Harness internals** — `.claude/commands/`, `.claude/rules/`, `scripts/hooks/`, `scripts/mcp/`, scheduled runners
- **LLM-driven services** — workflows with tool dispatch, data ingestion, autonomous decisions
- **Any code that orchestrates Claude calls, tool dispatch, persistent memory, or sub-agent invocation**

Out of scope: pure HTTP API code without agentic behaviour (use `/secure-code-review`), captured content review (C-7).

## When to use

- Before deploying a new hook, skill, MCP server, or scheduled runner.
- After material changes to an LLM-driven service's flow.
- When a service adds an AI or dynamic-eval feature.
- Quarterly audit pass over the harness.

## When NOT to use

- For static web-app code without agent behaviour — `/secure-code-review` covers those.
- For captured-content vetting — that's C-7, reviewed at the capture pipeline source.
- For design-level threat modelling — implementation-level skill; design lives in CLAUDE.md / decision records.

## Process — strict order

### 1. Resolve context

- Confirm path exists. If not, stop and ask.
- Identify agentic surface present in path:
  - **System prompts** — Anthropic SDK calls (`claude -p`, `client.messages`), `--system-prompt` flags
  - **Tool dispatch** — `allowedTools`, MCP server invocations, `Bash`/`Agent`/`WebFetch` exposure
  - **Memory / RAG** — reads from `memory/`, `00-Inbox/_captured/`, `MEMORY.md`, vector stores
  - **Inter-agent flow** — sub-agent invocations, Agent tool calls, chained Claude calls
  - **Autonomy controls** — budget caps, approval gates, audit hooks, kill-switches

If no agentic surface present: report *"No agentic surface in <path>. Try `/secure-code-review` for general checks."* and stop.

### 1a. Applicability — scope checks to the path

Not every ASI category applies at every path:

- **`.claude/commands/**` (slash-command skill files)** — ASI02, ASI03, ASI04, ASI05, ASI06, ASI07, ASI09 apply. ASI01 narrows to "skill-body untrusted-input framing on capture-reading skills". ASI08 + ASI10 are **N/A** (live in scheduled callers).
- **`capture-pipeline/**` or scheduled runners** — all ASI01-ASI10 apply (full unattended threat model).
- **`scripts/hooks/**`** — ASI01 narrows to C-6 hook-side LLM hygiene; ASI02 / ASI03 / ASI05 / ASI06 / ASI09 apply; ASI08 + ASI10 partial.
- **`scripts/mcp/**`** — ASI02 (tool surface), ASI03, ASI04, ASI05, ASI07, ASI09 apply.

**Cite N/A categories in the verdict block** ("ASI08, ASI10 — N/A at this path"). Do NOT generate findings against N/A categories.

### 2. Run ASI01-ASI10 checks

Each finding cites a `file:line` and tags one ASI category.

**Search discipline:** when grepping for security terms, use **case-insensitive** patterns (`-i`). Case-sensitive misses cause fabricated findings.

**ASI01 — Goal Hijack** *(prompt injection alters agent objectives)*
- System prompt contains explicit injection-recognition rule + protected-file allowlist (C-1). Grep `--system-prompt`, `system=`. 🔴 absent on unattended LLM calls.
- Untrusted input (captured content, external feeds, user input, email body) wrapped in delimited "UNTRUSTED" blocks before reaching the LLM. 🔴 on raw untrusted strings concatenated into prompt.
- Agent mission is the FIRST instruction, not buried after data. 🟡 on ambiguous placement.

**ASI02 — Tool Misuse** *(tools used in unintended ways)*
- `allowedTools` minimal (C-2). 🔴 if `Bash` allowed AND no **deterministic wrapper invocation** visible in skill body (specific runner, `.py`, or aliased `ssh <known-alias>` command — the wrapper IS the justification). 🟡 if `Bash` is used for ad-hoc shell without an inline documented pattern. `Agent`/`WebFetch`/`WebSearch` allowed without justification is 🔴.
- Tool descriptions don't invite abuse ("execute arbitrary code", "read any file"). 🟡 on overly-broad tool docs.
- Write-path allowlist enforced via PreToolUse hook (C-3 — `validate-write-path.py` wired in `.claude/settings.json`). 🔴 if `Write` allowed without allowlist.

**ASI03 — Identity & Privilege Abuse** *(delegated trust, inherited credentials, role chain exploits)*
- Credentials read at moment of need from configured secrets dir (C-8). 🔴 if creds in env vars passed to LLM context or in `.env` files referenced in code.
- Agent doesn't inherit broader filesystem / network access than its task requires. 🟡 if agent runs with `--dangerously-skip-permissions`.
- Sub-agent invocations don't escalate privilege — sub-agent's `allowedTools` ≤ parent's. 🔴 on privilege escalation in sub-agent dispatch.

**ASI04 — Supply Chain** *(compromised plugins / MCP servers)*
- **Third-party** MCP servers in `.mcp.json` pass the MCP evaluation rubric. 🟡 if any third-party MCP lacks documented eval. **Local-internal MCPs** (under `scripts/mcp/**` — local code) are exempt from this supply-chain check; review via `/secure-code-review` against the source instead.
- npm / pip / cargo dependencies pinned, lockfile present. 🟡 on floating versions in agentic paths.
- No `curl ... | bash` install of agent frameworks. 🔴 on framework auto-install.

**ASI05 — Code Execution** *(unsafe code generation / execution)*
- LLM output is never directly executed without validation. 🔴 on `eval(LLM_output)` / `exec(LLM_output)` / `subprocess(shell=True, cmd=LLM_output)`.
- `Bash` tool output isn't shell-evaluated downstream. 🔴 on shell-eval of LLM tool output.
- Generated SQL / regex / file paths from LLM output validated against allowlist before use. 🟡 if validation absent.

**ASI06 — Memory Poisoning** *(corrupted RAG / context data)*
- Reads from `00-Inbox/_captured/**` carry `trust: untrusted` propagation; LLM told the content is data, not instructions (C-7). 🔴 if captures fed into prompt without wrapper.
- Writes to `MEMORY.md`, `CLAUDE.md`, `07-References/**`, `TODO.md` are NOT auto-invoked from captures. 🔴 on direct copy path from captures to authoritative files.
- RAG retrievals from untrusted sources sanitised / tenant-isolated. 🟡 if retrieval crosses trust boundaries.

**ASI07 — Insecure Inter-Agent Comms** *(spoofing / intercepting agent-to-agent messages)*
- Sub-agent invocations include sanitised inputs — no raw LLM output piped to sub-agent prompt. 🔴 on direct LLM-output → sub-agent prompt.
- MCP server responses validated before being passed back to calling agent. 🟡 if MCP responses fed back raw.
- Inter-agent messages carry provenance metadata (which agent, which call ID) for audit. 🟡 if absent.

**ASI08 — Cascading Failures** *(errors propagate across systems)*
- Budget caps on every unattended LLM call (C-4). 🔴 if budget cap missing.
- Loop / recursion protection — sub-agent or tool-use loops have a step counter or depth limit. 🟡 if unbounded loop possible.
- Failure of one tool/MCP doesn't crash agent silently — explicit error handling + log. 🟡 if bare `except:` / `catch{}` swallows errors.
- Cursor / state advancement on failure is safe — only advance on success. 🟡 if state can advance on partial failure.

**ASI09 — Human-Agent Trust Exploitation** *(over-trust in agents leveraged to manipulate users)*
- Stakeholder-facing outputs cite source files / data with confidence tags. 🟡 if outputs have no provenance.
- Destructive / state-changing tool actions require human approval — not "agent decides" (C-3 write allowlist). 🔴 on auto-approve of state-changing actions.
- Agent doesn't impersonate a human voice in stakeholder-facing output without AI-provenance disclosure. 🟡 if disclosure absent.

**ASI10 — Rogue Agents** *(compromised agents acting maliciously)*
- Post-run audit (C-5) checks for actions the agent shouldn't have taken — writes outside allowlist, secrets in logs, anomalous tool usage. 🔴 if absent on unattended runs.
- Kill-switch / pause mechanism exists for live agents (service stop, scheduled-task disable). 🟡 if no documented kill procedure.
- Anomaly detection on agent behaviour — log review surfacing tokens-burned spikes, unusual tool dispatch. 🟡 if no monitoring.

### 3. Confidence-tag findings

- 🔴 **violates ASI category + no compensating control** — blocks merge.
- 🟡 **partial coverage / risk-flagged** — needs review or explicit acceptance.
- 🟢 **load-bearing pass** — include only for material passes. Skip 🟢 noise.

### 4. Output

```
## Agentic security review — <path>
**Verdict:** PASS / PASS-WITH-WARNINGS / FAIL
**Agentic surfaces present:** <system prompts | tool dispatch | memory | inter-agent | autonomy controls>
**ASI categories fired:** <ASI01..ASI10 — which fired>
**Files reviewed:** <count>

### 🔴 Critical findings
- **[ASI<NN>] <title>** — `<file>:<line>`
  - **Why it matters:** <one sentence linking to ASI category>
  - **Fix:** <one sentence — control to add>
  - **FP-check:** run `/fp-check "<finding citation>"` before treating as block

### 🟡 Warnings
- (same shape, no FP-check requirement)

### 🟢 Load-bearing passes
- (same shape, no Fix)

### Recommendations
- <ordered, only if the user will act>
```

If the user says "save it" → write to `08-Projects/<project>/security-reviews/{YYYY-MM-DD}-agentic-<path-slug>.md`.

### 5. Hand-off to fp-check

Recommend `/fp-check` on every 🔴 finding before blocking merge. Output explicit FP-check command at bottom of report.

## Things this skill must NEVER do

- **Edit the code being reviewed.** Read-only.
- **Fabricate ASI category mappings.** If a finding doesn't cleanly map to ASI01-ASI10, don't force it — tag as "general agentic concern" and explain.
- **Skip a category** because the surface "looks fine". Each ASI either applies (per §1a applicability matrix) or has documented exemption.
- **Report on captured content** (`00-Inbox/_captured/**`). Reviews paths that *handle* captures (ASI06), not the captures themselves.
- **Cite ASI numbers without grounding the underlying claim** in OWASP's published category language.
- **Generate findings against N/A categories.** Per §1a, ASI08 + ASI10 don't fire on slash-command skill files.
- **Use case-sensitive grep on security terms.** Always `-i` on `UNTRUSTED`/`Eval`/`Trust`/`Injection`.
- **Flag `Bash` grants as 🔴 when the skill body shows a deterministic wrapper invocation.** The wrapper IS the justification.
- **Apply ASI04 supply-chain checks to local-internal MCPs.** `scripts/mcp/**` is local code; use `/secure-code-review` instead.

## Co-change couplings

- **Finding pattern recurs across projects** → consider promoting to a path-specific rule in `.claude/rules/` or a new C-* control in `07-References/security-baselines.md`.
- **ASI category produces no real findings over multiple runs** → reassess whether the category applies to your threat model.
- **New harness automation added** → re-run this skill plus `/secure-code-review` before live.

## See also

- `07-References/security-baselines.md` — C-1..C-8 (harness hygiene; sibling lens)
- `.claude/commands/secure-code-review.md` — general secure-coding sibling
- `.claude/commands/owasp-llm-review.md` — LLM01-LLM10 sibling
- `.claude/commands/fp-check.md` — false-positive verification gate
- `confidence-tags.md` — convention used on every derived claim
