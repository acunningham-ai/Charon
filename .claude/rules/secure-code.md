---
paths:
  - "08-Projects/*/**"
  - "capture-pipeline/**"
  - "scripts/**"
  - "**/*.py"
  - "**/*.js"
  - "**/*.ts"
  - "**/*.go"
keywords:
  - "secure code"
  - "secure coding"
  - "security review"
  - "security baseline"
  - "deploy"
  - "deployment"
  - "ship to prod"
  - "production"
  - "secure-code-review"
  - "owasp"
  - "agentic"
  - "agentic security"
  - "LLM security"
  - "prompt injection"
  - "tool use abuse"
  - "MCP security"
  - "agent identity"
  - "memory poisoning"
  - "fp-check"
  - "false positive"
  - "ASI"
---

# Secure coding — auto-injected on code paths

Auto-loaded when editing code under any project / capture-pipeline / scripts path, or when the prompt mentions secure-code keywords.

Full baseline framework: `07-References/security-baselines.md`. Configure your project-specific controls during first-run.

## Hard requirements before any change ships

Every code change must satisfy the applicable controls from C-1 through C-8. **Don't ship and retrofit** — implement controls in the same change that adds or modifies the behaviour.

| Control | Applies to |
|---|---|
| **C-1** Hardened system prompts | Any unattended LLM call (Anthropic SDK, `claude -p`, etc.) |
| **C-2** Tool minimisation | All unattended LLM agents; default-deny `Bash`, `Agent`, `WebFetch`, MCP tools |
| **C-3** PreToolUse write-path allowlist | Any unattended automation with `Write` access |
| **C-3.1** Value-layer constraint (closed enums) | Structured-output writers — tags, labels, classifications, frontmatter values |
| **C-4** Budget cap | Every LLM invocation — `--max-budget-usd` / per-call ceiling |
| **C-5** Post-run audit | Every unattended runner — deterministic audit after the LLM step |
| **C-6** Hook-side LLM hygiene | Hooks that pass user content to an LLM |
| **C-7** Captured-content discipline | Anything that reads from or writes to your captured-content tree (`00-Inbox/_captured/**` by default) |
| **C-8** Sensitive-data egress | Anything that touches secrets, credentials, or has network egress |

**Project-specific reminders** live in each project's own `CLAUDE.md` — populate them with the controls that matter for that project (e.g. a web app's input-validation discipline, an LLM service's prompt-injection wrapper, a dashboard's source-of-truth rule). The harness ships the C-1..C-8 framework; you supply the project context.

## How to run the security checks

Three complementary skills cover the security surface. Use them together, not in isolation.

| Skill | When | What it covers |
|---|---|---|
| `/secure-code-review <path>` | Default — before any merge/deploy | C-1..C-8 baseline + general secure-coding (input validation, SQL, XSS, auth, crypto, dangerous functions, path traversal). Add `--diff` to scope; `--strict` to escalate warnings. |
| `/owasp-llm-review <path>` | When the path has LLM-consumer surface (SDK calls, prompt construction, RAG, budget controls) | OWASP Top 10 for LLM Applications 2025 (LLM01-LLM10) — prompt injection, sensitive info disclosure, supply chain, data/model poisoning, improper output handling, excessive agency, system prompt leakage, vector weaknesses, misinformation, unbounded consumption |
| `/owasp-agentic-review <path>` | When the path has agentic surface (system prompts, tool dispatch, memory, sub-agents, MCP) | OWASP Agentic AI Security 2026 (ASI01-ASI10) — goal hijack, tool misuse, identity/privilege abuse, supply chain, code execution, memory poisoning, inter-agent comms, cascading failures, human-agent trust, rogue agents |
| `/fp-check <finding-or-report>` | After every 🔴 finding from any of the three review skills, before treating as block | False-positive verification — re-reads cited `file:line`, reproduces or downgrades. Forces evidence on every block-merge claim. |

**Flow for a typical deploy gate:**

1. `/secure-code-review <path>` → general baseline + secure-coding findings
2. `/owasp-llm-review <path>` → LLM01-LLM10 lens (if LLM-consumer surface present)
3. `/owasp-agentic-review <path>` → ASI01-ASI10 lens (if agentic surface present)
4. `/fp-check` on each 🔴 from any skill
5. Only un-WITHDRAWN, un-DOWNGRADED 🔴 findings block merge

The LLM and agentic lenses are complementary, not alternatives — if the code both uses an LLM AND has agentic behaviour, run both.

🔴 findings block ship. 🟡 need review (or `--strict` escalates to fail). 🟢 load-bearing passes get reported for material controls only.

## Anti-patterns (auto-flag if I'm drifting)

- **Shipping the change, planning to "add baseline next sprint."** Baseline is part of the same change, not a follow-up.
- **Hand-waving an exemption.** Exemptions are tracked in `07-References/security-baselines.md` §Exemptions. If you can't point at the exemption, it doesn't exist.
- **Free-text user input flowing into a downstream system without validation.** Always validate. Always parametrise. Always allowlist.
- **Secrets in log lines or LLM context.** Read at moment of need; never persist.

## See also

- `07-References/security-baselines.md` — full framework + your compliance state (C-1..C-8)
- `.claude/commands/secure-code-review.md` — general baseline + secure-coding skill
- `.claude/commands/owasp-llm-review.md` — LLM01-LLM10 LLM-app-security skill
- `.claude/commands/owasp-agentic-review.md` — ASI01-ASI10 agentic-security skill
- `.claude/commands/fp-check.md` — false-positive verification gate
- `.claude/rules/skill-authoring.md` — adjacent rule for harness skill/MCP/hook authoring
