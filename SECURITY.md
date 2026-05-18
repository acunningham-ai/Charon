# Security

## Responsible disclosure

If you find a security vulnerability in this harness, please open a private **GitHub Security Advisory** at <https://github.com/acunningham-ai/Charon/security/advisories/new>. Do not open a public issue for it.

We aim to acknowledge within 72 hours and provide a fix or mitigation timeline within 14 days.

## Threat model

Charon is an AI-driven knowledge system that handles:

- The user's writing voice (a model of how they communicate)
- Operational facts about their systems (paths, hosts, restart sequences — never plaintext credentials)
- Captured content from external sources (email / chat / calendar) which is **untrusted by design**
- Slash-command skills that call out to Claude with system prompts, tools, and write access
- MCP servers that read and write vault markdown

Three threat surfaces matter:

### 1. LLM-app security (OWASP LLM01-LLM10, 2025)

The harness has multiple LLM call sites — slash commands, the save-on-mention hook, optional capture-pipeline classifiers. Each is subject to:

- **LLM01 Prompt injection** — captured content can carry attacker payloads. Mitigated by `trust: untrusted` frontmatter, "UNTRUSTED CAPTURED CONTENT" wrappers, hook-side redaction of known secret patterns before sending to the LLM, and the `captures.md` rule forbidding action on captured directives.
- **LLM02 Sensitive info disclosure** — credentials never go in prompts. The save-on-mention hook redacts known secret patterns (Anthropic, GitHub, AWS, Slack, generic bearer/password) before sending to Haiku.
- **LLM03 Supply chain** — third-party MCP servers must pass an evaluation rubric; local MCPs (`scripts/mcp/`) are reviewed via `/secure-code-review`.
- **LLM05 Improper output handling** — structured-output writers (frontmatter tags, classifications) are constrained to closed enums.
- **LLM06 Excessive agency** — `allowedTools` is minimal by default; `Bash` requires deterministic wrapper invocation; `Write` requires the path allowlist.
- **LLM07 System prompt leakage** — no credentials in system prompts; secrets read at moment of need from the secrets directory.
- **LLM10 Unbounded consumption** — budget caps on every unattended `claude -p` call.

Run `/owasp-llm-review <path>` against any LLM-consumer code in your installation.

### 2. Agentic security (OWASP ASI01-ASI10, 2026)

Where the LLM has tool dispatch / memory / sub-agent autonomy:

- **ASI01 Goal hijack** — same defences as LLM01 plus mission-first system prompts.
- **ASI02 Tool misuse** — `allowedTools` minimisation per skill; PreToolUse write-path validator.
- **ASI03 Identity & privilege abuse** — credentials read at moment of need, never inherited into LLM context.
- **ASI04 Supply chain** — MCP evaluation rubric.
- **ASI06 Memory poisoning** — captures never auto-flow into authoritative files (`MEMORY.md`, `CLAUDE.md`, `07-References/`). The `save-on-mention` hook is the only auto-write path, and it operates only on user statements in chat — not on captured content.
- **ASI10 Rogue agents** — post-run audit (`audit-unattended-run.py`) checks for actions outside the allowlist after every unattended `claude -p` run.

Run `/owasp-agentic-review <path>` against any agentic code in your installation.

### 3. Vault content protection

Files marked `classification: restricted` or `classification: confidential` in frontmatter are never returned by the `vault-readonly` MCP server. The `vault-ops` MCP refuses writes to `CLAUDE.md`, `MEMORY.md`, `TODO.md`, and anything under `00-Inbox/_captured/` or `09-Archive/`.

The `deny-destructive` PreToolUse hook protects, by default:

- `**/09-Archive/**` — cold storage, immutable
- `**/.claude/projects/**/memory/sessions/**` — past session journals, immutable
- `**/voice-examples/**` — voice anchors, input-only (matches any project that uses the voice-content pattern)
- `**/published/*.md` — published content, only the configured post-publication metric fields mutable (gated by `posted:` frontmatter being set)

Extend this list to match your additional protected zones — edit `PROTECTED_GLOBS` in `scripts/hooks/deny-destructive.py`.

## Security baseline framework (C-1..C-8)

The full pattern is encoded in `.claude/rules/secure-code.md` (auto-fires on code paths) and `.claude/rules/skill-authoring.md` (auto-fires on new skills / hooks / MCPs). Every new automation in the harness must satisfy applicable controls before going live:

| Control | What |
|---|---|
| **C-1** | Hardened system prompts on unattended LLM calls |
| **C-2** | Tool minimisation — default-deny `Bash` / `Agent` / `WebFetch` / MCP |
| **C-3** | PreToolUse write-path allowlist for `Write` access |
| **C-3.1** | Value-layer constraint (closed enums) for structured outputs |
| **C-4** | Budget cap on every unattended `claude -p` call |
| **C-5** | Post-run audit after every unattended runner |
| **C-6** | Hook-side LLM hygiene (untrusted-input wrappers, output sanitisation) |
| **C-7** | Captured-content discipline (`00-Inbox/_captured/**` is untrusted) |
| **C-8** | Sensitive-data egress — secrets at moment of need, never in logs / LLM context |

## What this harness deliberately does NOT do

- **Auto-write captures into authoritative files** — no copy path from `_captured/**` to `MEMORY.md` / `CLAUDE.md` / `07-References/`. The only auto-write path is the save-on-mention hook from chat (never from captures).
- **Send captured content to third-party LLMs** — only Claude is used. The save-on-mention hook redacts known secret patterns before its Haiku call.
- **Store credentials in source** — secrets live in your configured secrets directory (`~/.secrets/` by default); memory files point at them but never quote them.
- **Run unattended without the C-5 audit** — every scheduled `claude -p` invocation is followed by `audit-unattended-run.py` checking what changed against the allowlist.

## Reporting checklist

When reporting a vulnerability, please include:

- A description of the vulnerability
- A proof-of-concept (or steps to reproduce)
- The affected version / commit hash
- Your suggested mitigation if any
- Whether you'd like to be credited in the disclosure
