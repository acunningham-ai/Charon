# Charon

**A second-brain harness for [Claude Code](https://claude.com/claude-code) — built for executives, security leaders, and knowledge workers whose AI assistant has to remember context, hold a voice, refuse to fabricate, and operate under security controls that match the work.**

> *Charon, in Greek myth, is the ferryman who carries souls across the river Styx. This harness carries context across sessions.*

---

## The problem this solves

Chat-style LLMs forget between sessions. Agents act without rails. Personal-AI projects rarely take security seriously — and the few that do treat it as configuration, not behaviour. The result: every session starts cold, the agent makes confident-sounding guesses, and there's no audit trail when something goes wrong.

Charon turns Claude Code into a system that:

- **Loads relevant context before responding** — not on demand, by reflex. Session-start ritual fires on every prompt; project CLAUDE.md auto-loads when a project is mentioned.
- **Refuses to assume** — when a fact required to answer isn't in memory or source, the agent asks rather than extrapolates. *"I don't know"* beats a confident wrong answer.
- **Saves operational facts the same turn they're stated** — a fact mentioned in chat lands in structured memory before the response ends. No "I'll remember that" gaps.
- **Tags confidence on substantive claims** — 🟢 verified this turn / 🟡 in memory / 🔴 extrapolated. You see what's grounded vs guessed.
- **Holds path-conditioned discipline** — board-reporting rule fires on board paths; AI-governance rule fires on governance work; secure-code rule fires on code paths. The right doctrine loads at the right time.
- **Runs under a security baseline** — eight controls (C-1..C-8) cover the agentic surface: hardened prompts, tool minimisation, write-path allowlists, value-layer enum constraints, budget caps, post-run audit, captured-content as untrusted data, secrets at the moment of need.

---

## What makes this different

Most personal-AI projects ship one or two of the patterns below. Charon ships all of them — and tests that they fire.

### Quality controls (behavioural discipline)

| Control | What it does | Where it lives |
|---|---|---|
| **Confidence tags** | Every substantive claim carries 🟢 / 🟡 / 🔴 — the reader sees provenance, not just the answer | `.claude/rules/confidence-tags.md` (always-fire) |
| **No assumptions** | Uncertain facts trigger an ask, not an extrapolation; filename-trap, prior/current-conflict, undocumented design — all named must-ask triggers | `.claude/rules/no-assumptions.md` (always-fire) |
| **Save on mention** | Operational facts spoken in chat are written to the right memory file in the same turn, with one-clause acknowledgement | `.claude/rules/save-on-mention.md` (always-fire) + Haiku Stage 2 classifier hook |
| **Session-start ritual** | Project name, person name, date question, deploy task — each triggers loading the relevant memory content before the first response | `.claude/rules/session-start-ritual.md` (always-fire) |
| **Path-conditioned rules** | 7 path-rules auto-inject doctrine when the path/keyword fires (board-reporting, ai-governance, secure-code, captures, quarterly-report, voice-content, skill-authoring) | `.claude/rules/*.md` + `scripts/load-rules.py` (UserPromptSubmit hook) |
| **Open-thread surfacing** | Pickup notes from prior sessions surface their open questions at the start of the next response — no silent inheritance of stale plans | `.claude/rules/session-start-ritual.md` |
| **Refuse-to-fabricate** | Reporting skills refuse to compute scores / fabricate vendor names / invent framework numbers — they ask for source-of-truth input | `.claude/rules/quarterly-report.md` + `board-reporting.md` |

### Security controls (the C-1..C-8 baseline)

Built into the harness, not bolted on. Each is enforced by a specific mechanism, not just documented:

| ID | Control | Mechanism |
|---|---|---|
| **C-1** | Hardened system prompts for unattended LLM calls | Documented in `SECURITY.md`; enforced per skill |
| **C-2** | Tool minimisation — default-deny on Bash/Agent/WebFetch/MCP for unattended runs | Skill frontmatter `allowed-tools:` with minimum sets |
| **C-3** | PreToolUse write-path allowlist for unattended automation | `scripts/hooks/validate-write-path.py` reads per-runner allowlist JSON |
| **C-3.1** | Value-layer enum constraint on structured-output writers | TYPE_ALLOWLIST / TAG_ALLOWLIST in save-on-mention.py (and equivalents) |
| **C-4** | Budget cap per LLM invocation | `--max-budget-usd` / per-call ceiling on each runner |
| **C-5** | Post-run audit on unattended runners — deterministic checks compare changes to allowlist | `scripts/audit-unattended-run.py` |
| **C-6** | Hook-side LLM hygiene — secret redaction before sending user content to a sidecar model | `redact_secrets()` in save-on-mention.py — Anthropic / GitHub / AWS / Slack / generic patterns |
| **C-7** | Captured-content discipline — `00-Inbox/_captured/**` is `trust: untrusted`; never auto-writes to authoritative files | `.claude/rules/captures.md` + write-path allowlists |
| **C-8** | Sensitive-data egress — secrets read from the configured secrets directory at the moment of need, never embedded in prompts / logs / context | `harness_paths.secrets_dir()` pattern |

### Independent security review built in

- **`/secure-code-review`** — baseline secure-coding lens (input validation, auth, crypto, dangerous functions, path traversal) plus C-1..C-8 coverage
- **`/owasp-llm-review`** — OWASP Top 10 for LLM Applications 2025 (LLM01-LLM10): prompt injection, sensitive info disclosure, supply chain, data/model poisoning, improper output handling, excessive agency, system prompt leakage, vector weaknesses, misinformation, unbounded consumption
- **`/owasp-agentic-review`** — OWASP Agentic AI Security 2026 (ASI01-ASI10): goal hijack, tool misuse, identity/privilege abuse, supply chain, code execution, memory poisoning, inter-agent comms, cascading failures, human-agent trust, rogue agents
- **`/fp-check`** — false-positive verification gate that re-reads cited file:line, reproduces or withdraws each 🔴 finding. Forces evidence before any block-merge claim.

### Bi-directional email capture (inbox + sent items)

A working capture pipeline ships in `capture-pipeline/` — not a pattern, a runnable Node.js reference implementation. Pulls **both inbox and sent items** from your email provider into your vault as markdown captures, with a `direction: inbound|outbound` frontmatter flag that downstream skills read.

| Provider | Status |
|---|---|
| **Microsoft 365 (Graph API)** | Fully implemented — device-code OAuth, paginated inbox + SentItems, cursor-based incremental |
| **Gmail (Gmail API)** | Skeleton — interface complete, implementation stubbed with NOT_IMPLEMENTED + full setup walk-through in `EMAIL-PROVIDER-SETUP.md` |
| **Generic IMAP** | Skeleton — same as Gmail |

**Why sent items.** Inbox-only capture leaves a one-sided view of every conversation. You see what *they* sent; you don't see what you committed to in reply, what threads you owe a follow-up on, or what you said two weeks ago. Sent-items capture closes the loop: `/refresh-todo` and `/triage-inbox` can surface *"you sent X two days ago, no reply yet"* — time-management signal that an inbox-only pipeline can't produce. The default is on; if your use case is privacy-constrained, set `capture.sent: false` and the pipeline skips the sent path.

**Why a reference implementation, not just a pattern.** Pattern docs are easy to write and hard to verify. The capture-pipeline ships fully working for M365 so a new user can verify the end-to-end flow (auth → fetch → classify → write → dedup) on day one, then either use it as-is or fork it for their provider. Gmail + IMAP skeletons document the interface and setup steps; filling in the methods is a contained ~half-day job.

**User-configurable schedule.** The first-run wizard captures your preferred run frequency (daily / hourly / manual) and run time. `capture-pipeline/scheduled-capture.bat` (Windows) and `capture-pipeline/scheduled-capture.sh` (macOS / Linux) wrap the runner; you register them with Task Scheduler / cron / launchd. Full walk-through per platform in `EMAIL-PROVIDER-SETUP.md`.

### Tested, not just documented

`test-scenarios/` ships with the harness — 10 LLM-behaviour scenarios + 7 automated deterministic checks. The same suite runs before any release and after any material change to rules / hooks / wizard. Pass-rate threshold is published; releases with a failing scenario must document it in known-limitations.

```bash
python test-scenarios/run-deterministic-checks.py    # PASS in ~3 seconds, CI-ready
```

### Why this matters

The shape of personal AI is converging on agentic systems that read your files, take actions, fire tools, and accumulate context. **The patterns that protected enterprise software** — input validation, allowlist enforcement, secret hygiene, audit trails, deterministic test coverage — **apply to personal AI too, but they're rarely shipped by default.** Charon ships them by default. You get the productivity of an LLM personal assistant with the discipline of a hardened engineering system.

---

## Setup that doesn't fight you

One command on Windows, macOS, or Linux. The bootstrap installer (`install.ps1` / `install.sh`) detects what you have, offers to install what you don't via your platform's package manager, then hands off to the first-run wizard.

For each prerequisite (Python 3.10+, Obsidian if you want it), you get:

```
(a)uto-install / (m)anual install (open URL, then re-run) / (s)kip
```

- **Auto** runs `winget` / `brew` / `apt|dnf|pacman` for you. No admin elevation on macOS; Linux prompts for sudo when the package manager needs it; Windows `winget` runs per-user.
- **Manual** opens the install URL in your browser. You install, then re-run.
- **Skip** continues without the prereq — useful when you already have a custom Python (pyenv / asdf / mise) the script doesn't detect.

The first-run wizard takes ~20 minutes — identity, vault path, voice profile, org structure, framework calibration, dashboard tool, tool exceptions, workflow rules. State persists at `~/.charon-first-run-state.json`, so Ctrl+C any time and resume later. Re-run any phase independently to refresh that section without redoing the rest.

Full walkthrough: [`INSTALL.md`](INSTALL.md).

---

## Who it's for

- **CISOs and security leaders** — quarterly reporting, board commentary, governance docs, secure-code review
- **AI-governance practitioners** — policy/guidelines layering discipline, framework-informed commentary, doctrine encoded as rules
- **Agentic-AI engineers** — a worked example of hardened hooks, write-path allowlists, MCP servers, post-run audit
- **Knowledge workers who write seriously** — voice-content rule + anchor reading, capture pipeline pattern, knowledge-consolidate synthesis
- **Anyone building on Claude Code** — the rule/hook/MCP/skill scaffolding generalises beyond second-brain use

---

## What ships

| Layer | What |
|---|---|
| **Always-fire rules** | 4 rules — no-assumptions, save-on-mention, session-start-ritual, confidence-tags |
| **Path-conditioned rules** | 7 rules — auto-injected on path/keyword match: board-reporting, ai-governance, secure-code, captures, quarterly-report, voice-content, skill-authoring |
| **Slash commands** | 21 skills — quarterly-report-prep, control-translate, secure-code-review, owasp-llm-review, owasp-agentic-review, fp-check, score-vault, weekly-checkin, eod-reflect, knowledge-consolidate, refresh-todo, triage-inbox, draft-linkedin, linkedin-metrics, capture-screenshot, curate-skills, promote-rule, save-feedback, push-fact, check-service, telemetry-summary |
| **Hooks** | 9 hooks — load-rules (rule injection), save-on-mention (two-stage Haiku-classified), deny-destructive, validate-write-path, validate-memory-frontmatter, skill-usage-log, ssh-recovery, notification-toast, on-error |
| **MCP servers** | 3 local stdio servers — `vault-readonly` (keyword + semantic search, unit context, initiatives), `vault-ops` (patch_note, frontmatter_query, manage_tags), and `vault-graph` (entity / relationship queries, optional kuzu-backed) |
| **Subagents** | 4 specs in `.claude/agents/` — secure-code-reviewer, owasp-llm-reviewer, owasp-agentic-reviewer, knowledge-synthesizer — dispatched in parallel by parent skills for context isolation + bounded permissions |
| **Semantic search** | Local embeddings via `sentence-transformers` + `bge-micro-v2` (~80MB) → `sqlite-vec` vector store. Indexer at `scripts/semantic_index.py`. Optional install via `requirements-semantic.txt`. |
| **Knowledge graph** | Kuzu-backed entity + relationship graph extracted via Haiku at `scripts/extract_entities.py`. Optional install via `requirements-graph.txt`. |
| **Voice capture** | Local Whisper transcription via `scripts/voice-capture.py` + `/voice-note` slash command. Audio never leaves the machine. Optional install via `requirements-voice.txt`. |
| **Capture pipeline** | Runnable Node.js reference impl — inbox + sent items via M365 (fully implemented), Gmail + IMAP (skeletons). `direction: inbound\|outbound` frontmatter, user-configurable schedule, prompt-injection wrapper on every capture, dedup by provider ID. See `EMAIL-PROVIDER-SETUP.md`. |
| **First-run wizard** | YAML-defined questions (4 phases / 24 questions), state file resume on Ctrl+C, atomic write at the end, ANSI banner with optional ASCII trademark logo |
| **Test suite** | 10 LLM-behaviour scenarios + 7 deterministic checks (YAML schema, hook wiring, rule frontmatter, always-fire presence, personal-content scrub, wizard launch, banner render) |
| **Utility scripts** | score-vault, skill-curator, scheduled-audit, archive-captures, audit-unattended-run, recover-ssh-creds, check-capture-state, telemetry-summary |

See [`CAPABILITIES.md`](CAPABILITIES.md) for the full catalogue with descriptions, fire conditions, and outputs.

---

## What it doesn't do (yet)

Honest about the gaps. Charon's current bet is opinionated discipline + security depth, not full coverage of every capability the personal-AI space has converged on. If any of these are deal-breakers for your use case, check [`ROADMAP.md`](ROADMAP.md) to see where each item sits.

- **No mobile / remote bridge.** Desktop-only today. Anthropic Remote Control + community projects (Happy, AgentsRoom) exist but Charon hasn't integrated.
- **No vision capture beyond opaque VLM input.** `/capture-screenshot` exists but doesn't structure-extract (no OCR / table / chart parsing yet — VLM-based extraction patterns like DeepSeek-OCR are on the roadmap).
- **No observability + replay layer.** `skill-usage-log.py` writes events but there's no tamper-evident ledger, session trace, or replay capability (Langfuse-style self-hosted observability is on the roadmap; relevant to EU AI Act Article 19 audit-trail retention).
- **Not in a plugin marketplace yet.** Installable via clone + bootstrap, not via a single `claude install` command. Marketplace packaging is near-term.
- **Test suite is single-shot, not adversarial.** 10 LLM-behaviour scenarios + 7 deterministic checks; no automated red-team probing (DeepTeam / PyRIT / Garak) yet.
- **Gmail and IMAP capture-pipeline providers are skeleton-only.** M365 ships fully working (device-code OAuth, inbox + sent, cursor-based incremental). Gmail and IMAP have the interface defined and setup docs written, but the `auth() / fetchInbox() / fetchSent()` methods throw `NOT_IMPLEMENTED` until a contributor (you, or an upstream PR) fills them in. Estimated half-day per provider.

See [`ROADMAP.md`](ROADMAP.md) for what's coming next and what won't ship.

---

## Quick start

```bash
# Clone the repo (anywhere — outside cloud-synced folders is faster)
git clone https://github.com/acunningham-ai/Charon.git ~/second-brain
cd ~/second-brain
```

**Inspect the installer before running it.** Charon is a CISO tool; modelling the discipline it teaches starts here. Open `install.ps1` / `install.sh` in your editor and skim — it's short, it tells you what package managers it'll invoke and where it'll write.

```powershell
# Windows — least-permissive policy that works for a locally-cloned script
powershell -ExecutionPolicy RemoteSigned -File install.ps1
```

```bash
# macOS / Linux
bash install.sh
```

> **Optional integrity check:** every tagged release publishes a SHA-256 of `install.ps1` in the release notes. To verify before running:
> ```powershell
> Get-FileHash install.ps1 -Algorithm SHA256
> ```
> Compare the output to the hash on the release page. Mismatch → don't run; open an issue.

If your machine policy is locked to `AllSigned` and `RemoteSigned` rejects the script, fall back to `-ExecutionPolicy Bypass -Scope Process -File install.ps1` (scoped to one process, not machine-wide) AFTER you've read the file. See [`INSTALL.md`](INSTALL.md) troubleshooting for the full ladder.

The bootstrap installer detects Python 3.10+ and Obsidian, offers auto-install via `winget` / `brew` / `apt|dnf|pacman` OR shows install instructions, installs Python dependencies, creates `~/.secrets/` with restricted permissions, then hands off to the first-run wizard.

For each prerequisite that's missing you get `(a)uto / (m)anual / (s)kip` — auto runs your platform's package manager; manual opens the install URL; skip is for users who already have a custom install.

Full setup walkthrough: [`INSTALL.md`](INSTALL.md) → [`FIRST-RUN.md`](FIRST-RUN.md) → [`CONFIGURATION.md`](CONFIGURATION.md).

---

## Documentation map

| Doc | Read when |
|---|---|
| [`INSTALL.md`](INSTALL.md) | Setting up on a new machine |
| [`FIRST-RUN.md`](FIRST-RUN.md) | Walking through the interactive setup wizard |
| [`CONFIGURATION.md`](CONFIGURATION.md) | Tuning paths, secrets, scheduled tasks, optional integrations |
| [`CAPABILITIES.md`](CAPABILITIES.md) | Discovering what skills / rules / hooks ship + when each fires |
| [`SECURITY.md`](SECURITY.md) | Threat model (LLM01-LLM10 + ASI01-ASI10 applied to the harness itself) + responsible-disclosure |
| [`ROADMAP.md`](ROADMAP.md) | What's coming next + what won't ship |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | License, PR process, skill-authoring standard |
| [`CHANGELOG.md`](CHANGELOG.md) | Version history |
| `test-scenarios/` | Pre-release reliability checks — 10 LLM scenarios + 7 automated checks |

---

## Project status

| Phase | State |
|---|---|
| Initial scaffold | ✓ |
| File-level credential scrub (Gate 1) | ✓ |
| First-run wizard | ✓ |
| Test suite | ✓ |
| Internal-cohort validation | in progress |
| Git-history credential scrub (Gate 2) | pending — before public toggle |
| Public release | pending |

Currently a **private repo during the validation window**. Public toggle happens after trusted internal validators have run the test suite on their own machines. Track progress in [`ROADMAP.md`](ROADMAP.md).

---

## License

MIT — see [`LICENSE`](LICENSE). Use it commercially, fork it, modify it, ship it.

## Security

Found a vulnerability? Please see [`SECURITY.md`](SECURITY.md) for responsible-disclosure details. Don't open a public issue for security findings.

## Origin

Charon emerged from a working CISO harness that's been in active daily use through 2025-26 — built and refined while doing the actual work it was designed to support. The public release strips all organisation-specific content (frameworks, personnel, business-unit structure, vendor relationships) and ships the universal patterns. Users populate their own foundations through the first-run wizard.
