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

- **LLM01 Prompt injection** — captured content can carry attacker payloads. Mitigated by `trust: untrusted` frontmatter, "UNTRUSTED CAPTURED CONTENT" wrappers, hook-side redaction of known secret patterns before sending to the LLM, and the `captures.md` rule forbidding action on captured directives. **Plus a runtime detector** (`poisoning-scan.py` on `UserPromptSubmit`, observe-only) that flags *instruction-shaped* payloads — override, role-switch, exfiltration, tool-coax, secret-solicit, hidden/encoded, model special-tokens — at the choke point where untrusted text enters, hardened against confusable-homoglyph and base64/hex-encoded evasion. Detection-only: it logs a verdict, never blocks or rewrites the prompt.
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

#### Interactive write confinement (`validate-interactive-write.py`) — ships in shadow

`validate-write-path.py` implements C-3, but only for **unattended** runs: it engages when `HARNESS_UNATTENDED_ALLOWLIST` is set. An interactive command's write path was governed by prose in its own definition and nothing else.

`/meeting-prep` shows why that matters: it derives an output filename from a person's name that **originated in a calendar event** — a string an attacker can influence by sending you an invite. Its sanitisation rule is genuinely protective *if applied*, but that is model adherence, not a control.

| Layer | Rule | Catches |
|---|---|---|
| 1 | `outside-project-root` | a write resolving outside the project root (`..` traversal) |
| 1 | `protected-zone` | `.secrets/**`, `.claude/settings*.json`, `scripts/hooks/**` (a write there could disable the gates), `.git/**`, `.gitattributes` |
| 2 | `out-of-command-scope` | a target outside the running command's declared `write-scope:` |
| 3 | `untrusted-provenance-missing` | a note from a `reads-untrusted: true` command with no provenance marker |

**How it knows which command is running.** A PreToolUse payload names no slash command, so the obvious route — grepping the prompt for `/name` — is a *guess*, and a guess that blocks a write is a false positive with teeth. Claude Code invokes a typed command through the `Skill` tool, whose input carries the name, so `skill-usage-log.py` records it (`scripts/hooks/_active_command.py`) and the gate reads it. The record is per-session and TTL-bounded, so one session's scope cannot constrain another's writes.

**Verdict is `ask`, never `deny`** — each target is something a person could legitimately mean to write; what is prevented is a path the *model* derived wrongly. **The hook fails OPEN**, deliberately the inverse of its unattended sibling: that one guards runs nobody is watching, where crashing beats an unbounded write; this one runs interactively, where a bug in the gate would block legitimate work with no route around it.

**Status:** `SHADOW = True` — it logs verdicts and blocks nothing until reviewed. **Coverage is partial and reported as such:** 5 of 24 write-capable commands declare a `write-scope:`. Guessing the rest would ship false positives into a confinement control, which is how such controls get switched off. Check D31 prints the ratio every run; an undeclared command is *unenforced*, not permitted-by-default.

#### Untrusted content crossing the trust boundary by being written down

C-7 governs captured content **in flight**. The residual is the **write**. A note assembled from a calendar event lands in `05-Meetings/` — outside the captured zone, in the part of the vault later sessions read as **authored and trusted**. Quote a crafted invite subject verbatim into it and the hostile text has crossed the boundary *by being saved*: nothing about its untrusted origin survives, so a future session sees an ordinary authored note.

Commands that read untrusted sources declare `reads-untrusted: true`. A durable markdown note from one must carry **both** `trust: derived-untrusted` in frontmatter (machine-readable, for filtering) and a body line containing `DERIVED FROM UNTRUSTED INPUT` (model-readable, at the point of reading — the one that changes behaviour). The vocabulary is defined in `.claude/rules/captures.md`.

Where the payload carries a patch rather than a whole document the marker cannot be verified, so the gate logs `provenance-unverifiable` rather than returning a clean pass — an unverifiable case recorded as verified is how a control becomes a story about a control.

#### Allowlist integrity — checking the control, not just running it

`validate-write-path.py` checks a target *against* the C-3 allowlist. Nothing checked the **allowlist itself**, so a glob widened to `**/*.md` passed every hook while confining nothing — the control reporting healthy precisely when it had stopped working. `scheduled-audit.py` now flags match-everything globs, missing directory anchors, protected-path targets, malformed JSON and `allowed_high_sensitivity` opt-ins.

#### Two-layer finding provenance (OWASP + MITRE ATLAS)

Findings from `/owasp-llm-review` and `/owasp-agentic-review` carry both an OWASP category and a MITRE ATLAS technique — `LLM01 · AML.T0051.001`. OWASP says what kind of weakness it is; ATLAS says what an adversary does with it. The mapping is `07-References/owasp-atlas-crosswalk.md`, validated against a committed snapshot of ATLAS 5.6.0 (`07-References/atlas-technique-index.json`).

Check **D32** fails if any cited ID is absent from that snapshot, if a rendered name disagrees with it, or if a reviewer stops pointing at the crosswalk. Offline by design, so it cannot pass merely because a network fetch failed. The reason: a plausible-looking technique ID is the easiest thing in a security report to invent and the hardest for a reader to falsify — **an unverifiable citation is worse than none, because it borrows authority it has not earned.**

#### Workflow scripts must stay launchable (`.gitattributes` + D30)

The `Workflow` tool refuses a script containing control characters, and CR (U+000D) is one. With no `.gitattributes`, working-tree line endings are decided by each user's `core.autocrlf` — `true` by default on Git for Windows — so a fresh clone rewrote every LF to CRLF and **all three workflows became unlaunchable** while the committed blobs stayed clean and every other check passed. `.gitattributes` pins `eol=lf`; D30 fails on a control character in any workflow script, on a missing pin, and on CR anywhere in the tracked text tree. It reads the **working tree**, not the blob — reading the blob is exactly what would have missed it.

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
