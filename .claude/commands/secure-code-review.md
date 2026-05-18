---
description: Run the security baseline checklist over a code path or diff — outputs pass/warnings/fail with file:line findings
argument-hint: "<path> [--diff] [--strict] — e.g. '08-Projects/<project>/src' | 'scripts/hooks/save-on-mention.py' | 'capture-pipeline --diff'"
allowed-tools: Read, Glob, Grep, Bash
---

# /secure-code-review — baseline check over a code path

You are running the **C-1..C-8 security baseline** from `07-References/security-baselines.md` plus standard secure-coding checks (input validation, secrets handling, dependency hygiene, logging discipline) over a code path or diff. Output is a structured report with 🟢/🟡/🔴 tagged findings, file:line citations, and a verdict.

Sibling rule: `feedback_security_baselines.md` (every new automation must satisfy baseline before going live). This skill makes the rule **runnable** instead of memory-dependent.

## Scope

`$ARGUMENTS` — required. First token is the path; remainder are flags.

| Mode | Args | Behaviour |
|---|---|---|
| Full path | `<file-or-dir>` | Review every applicable file under the path |
| Diff only | `<path> --diff` | Review only lines changed in the working tree (uses `git diff`) |
| Strict | `<path> --strict` | 🟡 warnings escalate to FAIL; default treats them as PASS-WITH-WARNINGS |

If `$ARGUMENTS` is empty: stop and ask *"Which path? Examples: `08-Projects/<project>/src`, `scripts/hooks/save-on-mention.py`, `capture-pipeline`."*

## Process — strict order

### 1. Resolve context

- Confirm the path exists. If not, stop and ask.
- Identify project context by reading the path's nearest `CLAUDE.md` (or the root `CLAUDE.md`). Project context tells you which controls apply:
  - **Harness paths** — `scripts/hooks/**`, `scripts/mcp/**`, `.claude/commands/**`, `capture-pipeline/**` → full C-1..C-8 applies
  - **LLM-driven service** (per project CLAUDE.md flagging) → LLM controls (C-1..C-6) + secrets (C-8) + general secure-coding
  - **Web app** (per project CLAUDE.md flagging) → web-app checks + secrets (C-8) + general secure-coding; LLM controls apply if AI features present
  - **Other** → general secure-coding checks
- Identify language / framework from extensions (`.py`, `.ts`, `.js`, `.mjs`, `.sh`, `.bat`, `.yaml`).

### 2. Select applicable checklist

Map findings against the right control set:

| Context | LLM controls (C-1, C-2, C-3, C-3.1, C-4, C-5, C-6) | Capture discipline (C-7) | Egress / secrets (C-8) | Web-app checks | General secure-coding |
|---|---|---|---|---|---|
| Harness | ✅ all | ✅ | ✅ | — | ✅ |
| LLM-driven service | ✅ where LLM-driven | — | ✅ | — | ✅ |
| Web app | — | — | ✅ | ✅ | ✅ |
| LLM-augmented web app | ✅ if LLM features added | — | ✅ | ✅ | ✅ |
| Other | apply where applicable | apply where applicable | ✅ | apply if web | ✅ |

### 3. Run checks

For each applicable check, scan the path with Grep / Read and record findings. **Be concrete — every finding cites a file path and line number.** Vague findings ("might be insecure") are forbidden.

**LLM controls — C-1 to C-6**
- **C-1 hardened prompt**: any unattended LLM call must have a system prompt naming single purpose, single output target, protected files, and the injection-recognition rule. Grep for SDK call sites — verify each one.
- **C-2 tool minimisation**: `allowedTools` present and minimal. `Bash`, `Agent`, `WebFetch`, `WebSearch`, MCP tools must have explicit justification or be denied. 🔴 if `Bash` is allowed without a wrapper.
- **C-3 write-path allowlist**: any `Write` access in unattended runs must have a `PreToolUse` hook pointing at `scripts/hooks/validate-write-path.py` (or equivalent) with an `<prompt>.allowlist.json`. 🔴 if Write is allowed without an allowlist.
- **C-3.1 value-layer constraint**: structured-output writers (frontmatter, JSON, labels, tags, classifications) must constrain to a closed enum. 🟡 if free-text writes to structured fields.
- **C-4 budget cap**: budget ceiling present on every unattended invocation. 🔴 if missing.
- **C-5 post-run audit**: every unattended runner must call a post-run audit after the LLM step. 🔴 if absent.
- **C-6 hook-side LLM hygiene**: hooks that pass user content to an LLM must wrap content in "UNTRUSTED USER PROMPT" blocks, sanitise structured output, and never auto-act on protected files. 🔴 if any of those are absent.

**Capture discipline — C-7**
- Files written to `00-Inbox/_captured/**` carry `trust: untrusted` frontmatter and a leading "UNTRUSTED CAPTURED CONTENT" wrapper. 🔴 if missing.
- No code path copies captured content verbatim into `MEMORY.md`, `07-References/**`, `CLAUDE.md`, or `TODO.md`. 🔴 on any direct copy.

**Egress / secrets — C-8**
- Secrets read paths (configured secrets dir, `~/.ssh/**`, OS keychain APIs) are NEVER co-located with `WebFetch`, `WebSearch`, outbound HTTP libraries, or unbounded network egress in the same code path. 🔴 if violated.
- Credentials read at moment of need, never logged, never included in LLM context. 🔴 on any credential in a log line.
- `.env` / `secrets.json` / credential files committed or referenced in code rather than read from the secured location. 🔴 if committed; 🟡 if path-referenced.

**Web-app checks**
- **Input validation**: every untrusted input validated against a schema (Zod, Joi, Pydantic, manual `assert`). 🔴 if direct DB query / template-render from untrusted input.
- **Output encoding / XSS**: framework auto-escapes (React, Svelte) — flag any `dangerouslySetInnerHTML`, `innerHTML =`, `eval(`, `Function(`, raw HTML interpolation. 🔴.
- **SQL / parametrised queries**: no string-concatenation into SQL. 🔴 if untrusted input is interpolated.
- **Auth/authz**: every privileged route checks identity AND authorisation. 🔴 if a privileged route is anonymous.
- **CSRF / CORS**: state-changing routes have CSRF protection; CORS `Access-Control-Allow-Origin: *` is absent on authenticated endpoints. 🔴 on either violation.
- **Rate limiting**: public endpoints have rate limits. 🟡 if absent on auth endpoints.
- **Cryptographic primitives**: no `MD5`, `SHA1` for security; no hand-rolled crypto; password hashing uses `argon2`/`bcrypt`/`scrypt`. 🔴 on any deprecated primitive in a security context.

**General secure-coding (all contexts)**
- **Dependencies**: lockfile present and up to date. 🟡 if missing.
- **Error handling**: no `catch` that silently swallows exceptions; no bare `except:` with no log. 🟡.
- **Logging hygiene**: structured logging where possible; no secrets, PII, tokens in log output. 🟡 if free-text logs with sensitive context.
- **Dangerous functions**: `eval`, `exec`, `pickle.loads` from untrusted input, `subprocess.shell=True` with untrusted input. 🔴 on any untrusted-input pairing.
- **Path traversal**: file paths constructed from user input without normalisation + allowlist root check. 🔴 if violated.
- **Race conditions on writes**: append-only or atomic write patterns where multiple processes touch the same file. 🟡 if non-atomic writes to shared state.

### 4. Confidence-tag findings

- 🔴 **assumed / blocking** — the issue requires action before merge. Reserve for clear violations.
- 🟡 **medium** — risk-flagged, needs context (might be acceptable with documented justification).
- 🟢 **verified / passes** — the check fired and the code complies.

Skip 🟢 for very basic checks (don't fill the report with noise); include for *load-bearing* passes.

### 5. Output

Inline report (no auto-write unless the user asks):

```
## Secure code review — <path>
**Verdict:** PASS / PASS-WITH-WARNINGS / FAIL  (--strict: warnings become FAIL)
**Project context:** <from nearest CLAUDE.md>
**Checklist applied:** <comma-separated list of control IDs and general checks that fired>
**Files reviewed:** <count>

### 🔴 Critical findings (block merge)
- **<Finding title>** — `<file>:<line>`
  - **Why it matters:** <one sentence>
  - **Fix:** <one sentence>

### 🟡 Warnings (review with author)
- (same shape)

### 🟢 Load-bearing passes
- (same shape, without the Fix line)

### Recommendations
- <ordered list of suggested next moves, only if the user will act on them>
```

If the user says "save it" → write to `08-Projects/<project>/security-reviews/{YYYY-MM-DD}-<path-slug>.md` with frontmatter `type: security-review`, `verdict: ...`, `reviewer: claude-code /secure-code-review`.

### 6. Quality loop

Show the report. Ask the user:
- *Are the 🔴 findings real, or am I missing context?* (some flags might be by-design — e.g. Bash allowed because a wrapper exists)
- *Anything I should add to the project's `CLAUDE.md` so I get the context next time?*

If the user corrects a finding → save the correction to the project's `CLAUDE.md` if it's a recurring exemption, or to `feedback_security_baselines.md` if it changes the rule.

## Things this command must NEVER do

- **Auto-fix findings.** This skill reports; it doesn't edit.
- **Skip the C-1..C-8 checklist for harness paths** based on "looks fine." Every control either applies or has an exemption tracked in §Exemptions of `security-baselines.md`.
- **Fabricate file:line citations.** Every finding has a concrete path + line.
- **Report on captured content (`00-Inbox/_captured/**`).** Captures are untrusted by design — review pipelines that *write* to captures (C-7), don't review the captures themselves.
- **Touch the code being reviewed.** Read-only.

## When to use

- Before deploying a change to a live service.
- After building any new harness automation (skill, hook, MCP server) — required by `feedback_security_baselines.md`.
- When onboarding a new project to the harness (initial baseline pass).
- After a dependency update or major refactor.

## When NOT to use

- For pure documentation changes (no code).
- For captured-content reviews — different concern (C-7 at the pipeline source).
- For threat-modelling or design reviews — implementation-level skill.
- As a substitute for human security review on high-stakes changes — this is a *baseline* check.

## Co-change couplings

- **New automation added** → must satisfy applicable controls and be added to §Current state in `07-References/security-baselines.md`.
- **New exemption discovered** → update `07-References/security-baselines.md` §Exemptions.
- **Repeated false positive** → tighten the check in this skill (rule, not effort).

## See also

- `07-References/security-baselines.md` — the baseline framework (C-1..C-8 source-of-truth)
- `.claude/rules/secure-code.md` — path-rule that auto-injects this skill's context
- `.claude/commands/owasp-llm-review.md` — LLM01-LLM10 lens for LLM-consumer code
- `.claude/commands/owasp-agentic-review.md` — ASI01-ASI10 lens for agentic code
- `.claude/commands/fp-check.md` — false-positive verification gate
- `confidence-tags.md` — convention used on every derived claim
