# Changelog

All notable changes to this project will be documented here. Format follows [Keep a Changelog](https://keepachangelog.com/). During private validation, releases are tagged `v0.X.Y-preview`. See [`VERSIONING.md`](VERSIONING.md) for when each number bumps (MINOR = new capability, PATCH = update / feedback fix).

## [Unreleased]

*Nothing pending — next change lands here.*

---

## [0.3.1-preview] - 2026-05-25

### Changed — sharper V3 classification in `vet-external-skill`

First real-world run of `/cerberus-vet` (against a defensive-security Go tool) surfaced a calibration gap in the V3 (filesystem access) layer. The grep returns hits in code that **reads** sensitive paths AND in code that **defends** them — both legitimate, opposite risk profiles, but the original scoring treated all hits the same way.

This release teaches V3 to classify each grep hit by intent before scoring:

- **Read** — path is an input to a file-read primitive. Score as the rubric says.
- **Defensive listing** — path appears in a deny-list, block-list, or dangerous-paths array used by a sandbox / scanner / allowlist enforcer. Variable names like `DANGEROUS_*` / `DENY_*` / `BLOCKED_*` / `SENSITIVE_*` / `PROTECTED_*` and structures like `AddDeny` / `BlockPath` / `RestrictAccess` are the signal. **Not a finding** — recorded under *What Passed Cleanly* as a positive note (the artifact defends these paths rather than reading them).
- **Test fixture** — path is in a test tree, used to exercise a deny-rule with fake secrets. Not a finding.
- **Documentation** — `.md`-only mention. Not a finding.

The intent classification step is now load-bearing; the grep alone is necessary but not sufficient.

### Changed — V3 grep extended to more languages

Original V3 grep only walked `.py` / `.js` / `.ts` / `.sh`. Added `.go` / `.rs` / `.rb` / `.java` — without these, the grep would silently miss V3 patterns in any non-script-language artifact.

### Why this is a PATCH and not a MINOR

The `/cerberus-vet` capability is unchanged in what it does — same artifact-vetting surface, same V0–V8 threat model, same scoring rubric, same output. V3 inside it is now better calibrated. The authoring test (*"could a user describe this as 'now I can do X' where X is new?"*) is no — vet still does what it did; it's just less likely to misclassify defensive-purpose artifacts as risky. Calibration fix, not new capability → PATCH.

---

## [0.3.0-preview] - 2026-05-25

### Added — Cerberus, the security capability that protects the harness itself

The reviews already in Charon (`/secure-code-review`, `/owasp-llm-review`, `/owasp-agentic-review`) protect the *code you're working on*. Cerberus protects the *Claude Code installation* the harness runs in. Two different surfaces, both now covered.

Original Cerberus was built by [Joh Leonhardt](https://github.com/JohL29/claude-security-auditor) as a Claude Code plugin. This release ports the engine into the harness directly and extends it with the V0–V8 third-party-artifact threat model, OWASP LLM crosswalk, MCP-specific coverage, and a remediation library.

**Four new slash commands:**

- **`/cerberus-setup`** — first-run hardening wizard. Audits your Claude Code configuration against the gold standard, walks you through each gap interactively, verifies the result. Designed to be the first thing you run on any new machine.
- **`/cerberus-audit`** — read-only diagnostic across a 7-layer threat model: secrets at rest, secrets in environment variables, egress channels, prompt injection in CLAUDE.md / MEMORY.md, supply chain (installed plugins / skills), bypass containment, audit trail. Produces a 0–100 score and per-finding fixes.
- **`/cerberus-vet <repo-url>`** — pre-install risk assessment of a third-party Claude Code plugin, skill, or MCP server. Clones the repo to a sandbox, walks the file tree, applies a 9-layer threat model (V0–V8) covering OWASP LLM01 / LLM02 / LLM03 / LLM06, and returns a risk level (LOW / MEDIUM / HIGH / CRITICAL) + 0–100 score. **MCP-specific coverage** includes tool-schema audit, transport-aware egress, HTTP-transport auth-scheme audit, tool-description poisoning detection, and MCP SDK typosquat checks. Per-finding mitigations cite the remediation-library template ID where available. Output is risk evidence — final tool-approval authority sits with your organization's defined policy.
- **`/cerberus-recover`** — post-leak runbook. Walks you through credential rotation, git-history cleanup, session invalidation, and enabling ongoing protection.

**Four new model-triggered skills under `.claude/skills/`** — `audit-claude-setup`, `harden-claude-setup`, `vet-external-skill`, `rotate-leaked-secret`. Each command dispatches the matching skill. This is the first set of `.claude/skills/`-style skills shipping in Charon — they're auto-triggered by the assistant when the task matches their description (separate from the slash-command invocation model).

**One new subagent** — `.claude/agents/cerberus.md` — the security specialist that orchestrates the four skills. Wires into the existing multi-agent dispatch pattern.

**Reference material under `07-References/cerberus/`** — architecture overview, 7-layer threat-model rationale, the OWASP LLM 2025 crosswalk for the vetting layers (V0–V8), and a starter remediation library (REM-001 through REM-010) with author-side fix + adopter-side acceptance for the most common findings.

**Cerberus's own hooks** (`scripts/hooks/cerberus/block-secrets.sh`, `audit-claude-md.sh`, `secret-pattern-scan.py`) ship alongside the existing hooks but are **not auto-wired**. The block-secrets and CLAUDE.md-audit hooks change harness behaviour at the write-path layer; `/cerberus-setup` walks you through enabling them deliberately rather than turning them on by default.

### Attribution

Joh Leonhardt's original Cerberus shipped as a Claude Code plugin under MIT. The Charon build preserves that licence and credits Joh in every commands file (`upstream:` frontmatter field), in `CAPABILITIES.md`, and in the README's Cerberus section. The Charon extensions (V0–V8, `/cerberus-vet`, OWASP crosswalk, remediation library) ship on top.

### Why this is a MINOR and not a PATCH

Cerberus is a new capability surface — four new slash commands, four new model-triggered skills, a new subagent, new reference material, new hook scripts. The authoring test (*"could a user describe this as 'now I can do X' where X is new?"*) is yes — "now I can audit, harden, vet, and recover my Claude Code installation from inside the harness." That's new capability, so MINOR.

---

## [0.2.0-preview] - 2026-05-19

### Added — versioning framework (your projects get the same discipline)

When you use Charon to build your own projects, you now get a consistent versioning convention applied automatically.

- **New file: [`VERSIONING.md`](VERSIONING.md)** at the repo root — the user-facing doc that explains the convention: MINOR for a new capability, PATCH for an update / fix / feedback refinement, `-preview` suffix during private validation, and a one-question authoring test to decide which number to bump (*"could a user describe this as 'now I can do X' where X is new?"*).
- **New always-helpful rule: `.claude/rules/versioning.md`** — auto-loads when you (or Claude Code) are working on a CHANGELOG, cutting a release, picking a tag name, or asking "is this a MINOR or PATCH?". The rule names the workflow steps (decide → CHANGELOG → tag → push), surfaces the anti-patterns (don't inflate PATCH to MINOR for marketing, don't use non-standard `.5 / .6` increments, never tag without updating CHANGELOG).
- **CHANGELOG header** now links readers to `VERSIONING.md` so the convention is one click away from the release log.

This applies to Charon itself AND to any project you build under the harness — it's a shared discipline that signals across all your work which kind of change happened from the version number alone.

### Why this is a MINOR and not a PATCH

`VERSIONING.md` + the new path-rule didn't exist in `v0.1.1-preview`. They're a new capability the harness now ships with — so MINOR.

---

## [0.1.1-preview] - 2026-05-19

### Added — reliable email capture (no more silent failures)

A common frustration with scheduled email capture: it runs at 7am, your sign-in has expired overnight, and the script gets stuck waiting for you to sign in again — but nobody's there. You discover the failure hours later, missing a day of mail.

This release fixes that. Three changes work together:

- **The scheduled pipeline now fails fast instead of hanging.** When your saved sign-in is no longer valid (this happens periodically because of your company's normal security policies), the capture script exits immediately with a clear message instead of waiting forever for someone to type a code.
- **You get notified the moment it happens.** A native desktop notification pops on your screen (Windows toast, macOS notification, Linux notify-send — whichever your system has) saying *"Capture pipeline: re-auth required."*
- **Your next Claude Code session reminds you too.** A small file on disk acts as a flag. Next time you start Claude Code, the first response begins with a short banner showing exactly what command to run and how long ago the failure happened. The flag clears automatically the moment you successfully sign back in.

**Recovery is one command:** `cd capture-pipeline && node fetch-mail.mjs auth` — about sixty seconds to enter the code your browser displays. The next scheduled run picks up where it left off.

If you've ever been annoyed that your capture pipeline silently lost a morning of email, this is the fix.

Technical implementation: new `setNonInteractive()` on the M365 provider, `--non-interactive` CLI flag on `fetch-mail.mjs`, distinct exit code `2` on auth failure, `state/REAUTH-NEEDED.flag` JSON marker, cross-platform notification logic in `scheduled-capture.bat` and `scheduled-capture.sh`, new `scripts/hooks/check-reauth-flag.py` SessionStart hook wired in `.claude/settings.json`.

### Why this is a PATCH and not a MINOR

The capture pipeline already existed in `v0.1.0-preview`. This release makes it more reliable but doesn't add a new capability — so PATCH.

---

## [0.1.0-preview] - 2026-05-18

Initial preview release — distributed to invited private validators on 2026-05-18. Everything below shipped as part of this preview.

### Added — capture pipeline scheduling

- **`capture-pipeline/scheduled-capture.bat`** (Windows) and **`scheduled-capture.sh`** (macOS / Linux) — thin wrapper scripts that resolve their own dir, ensure `state/`, run `node fetch-mail.mjs all`, append to `state/scheduled-run.log` with start/finish/exit markers.
- **First-run wizard schedule questions** — `pipeline_schedule_frequency` (daily / hourly / manual) and `pipeline_schedule_time` (HH:MM, default 07:00) under the workflow phase. Both `depends_on: capture_pipeline_setup: y` so they only surface when the user opted in.
- **`EMAIL-PROVIDER-SETUP.md` §Scheduling** — per-platform walk-through for Task Scheduler (Windows + PowerShell snippet), launchd (macOS plist), and cron (Linux). Cadence guidance + failure-mode awareness.
- **README capability section** — new "Bi-directional email capture" subsection under "What makes this different" explaining the why (sent-items closes the loop on commitments / threads owed replies), the provider matrix (M365 fully implemented, Gmail + IMAP skeleton), and the configurable schedule.
- Updated stale README lines ("capture pipeline ships as a pattern") to reflect the runnable reference implementation.

### Added — capture pipeline reference implementation

- **`capture-pipeline/`** — reference Node.js capture pipeline pulling inbox + sent items from a configured email provider into your vault as markdown captures.
- **Provider abstraction** — `lib/providers/base.mjs` interface; providers implement `auth() / fetchInbox() / fetchSent()` returning normalised email objects (`base.mjs` documents the shape).
- **M365 (Microsoft Graph) provider** — fully implemented. Device-code OAuth via MSAL with file-based token cache, paginated inbox + SentItems folder fetch, cursor-based incremental capture.
- **Gmail + IMAP providers** — skeleton (interface complete, `auth() / fetchInbox() / fetchSent()` throw `NOT_IMPLEMENTED`). Setup steps documented in `EMAIL-PROVIDER-SETUP.md`; PRs welcome to fill in the methods.
- **`direction: inbound|outbound` frontmatter flag** on every captured email — distinguishes inbox from sent so `/refresh-todo` and `/triage-inbox` can surface threads where you owe a reply.
- **Recipient-based classification path** — sent items route to org-unit/domain by recipient address (since sender is always the user). Mirror of inbox classifier, same downstream shape.
- **First-run wizard expansion** (`scripts/first-run-questions.yaml`):
  - Provider choice (m365 / gmail / imap), per-provider config questions (`depends_on` branches)
  - Sent-items toggle (default on)
  - New `capture_pipeline_config` template renders `<repo-root>/capture-pipeline/config.json`
  - `scripts/first-run.py` extended with `<repo-root>` placeholder resolution
- **`EMAIL-PROVIDER-SETUP.md`** — new top-level doc walking through M365 (Entra app registration + Mail.Read scope + device-code flow + public-client toggle), Gmail (Cloud Console OAuth client + Gmail API + consent screen + test users), and generic IMAP (app-password generation per major provider, secrets-file storage, sent-folder naming gotchas).
- **`capture-pipeline/README.md`** — pipeline overview, layout, schedule-it instructions, failure-mode awareness, extension guide.
- **Cross-references** added to `INSTALL.md`, `FIRST-RUN.md`, `CAPABILITIES.md`.

### Added — initial scaffolding

- **4 always-fire rules** — no-assumptions, save-on-mention, session-start-ritual, confidence-tags
- **7 path-conditioned rules** — board-reporting, ai-governance, secure-code, captures, quarterly-report, voice-content, skill-authoring
- **21 slash commands** — quarterly-report-prep, control-translate, secure-code-review, owasp-llm-review, owasp-agentic-review, fp-check, score-vault, curate-skills, weekly-checkin, eod-reflect, knowledge-consolidate, refresh-todo, triage-inbox, draft-linkedin, linkedin-metrics, capture-screenshot, save-feedback, push-fact, promote-rule, telemetry-summary, check-service
- **9 hooks** — load-rules, save-on-mention (two-stage with Haiku classifier + secret redaction), deny-destructive, validate-write-path, validate-memory-frontmatter, skill-usage-log, ssh-recovery, notification-toast, on-error
- **2 MCP servers** — vault-readonly (search_memory, get_unit_context, list_active_initiatives) and vault-ops (patch_note, frontmatter_query, manage_tags)
- **8 utility scripts** — score-vault, skill-curator, scheduled-audit, archive-captures, audit-unattended-run, recover-ssh-creds, check-capture-state, telemetry-summary
- **harness_paths.py** — env-var-first path resolution (`HARNESS_VAULT_ROOT`, `HARNESS_MEMORY_ROOT`, `HARNESS_CAPTURE_ROOT`, `HARNESS_SECRETS_DIR`)
- **Security baseline framework** — C-1 through C-8 controls referenced throughout hooks and skills
- **Documentation set** — README, INSTALL, CAPABILITIES, SECURITY, FIRST-RUN, CONFIGURATION, CONTRIBUTING, CHANGELOG, LICENSE (MIT)
- **`.gitignore`** — excludes state, captures, secrets, memory, settings.local.json, Obsidian cruft, node_modules

### Added — bootstrap + first-run wizard

- **`scripts/first-run.py`** — interactive setup wizard
  - YAML-defined question data model (`scripts/first-run-questions.yaml`): 4 phases, 24 questions, 9 templates, 2 env vars
  - State file at `~/.charon-first-run-state.json` for Ctrl+C resume
  - `--phase`, `--dry-run`, `--logo full|small|auto`, `--no-logo` flags
  - Re-run mode offers `[k]eep / [u]pdate / [w]ipe` for each previously-answered question
  - Atomic write at the end after summary + confirmation
- **`scripts/lib/banner.py`** + **`scripts/lib/charon-logo.txt`** — install banner with small + full ASCII art variants, auto-selected by terminal width
- **`install.ps1`** (Windows) — bootstrap script with `(a)uto / (m)anual / (s)kip` per prereq, uses winget for Python + Obsidian; non-interactive mode via `-AcceptDefaults`
- **`install.sh`** (macOS / Linux) — same pattern via brew / apt / dnf / pacman; non-interactive mode via `ACCEPT_DEFAULTS=1`
- **`requirements.txt`** — PyYAML, anthropic, mcp

### Added — semantic search, knowledge graph, multi-agent, voice

- **Local semantic search**: `scripts/lib/semantic.py` + `scripts/semantic_index.py`. Embeddings via `sentence-transformers` (`bge-micro-v2`, ~80MB, CPU-only), stored in `sqlite-vec` at `.charon/semantic-index.db`. Incremental + full-rebuild modes. Index excludes captured / archived zones.
- **`semantic_search` MCP tool** added to `vault-readonly`. Returns top-k matching chunks with file:line provenance. Graceful error if optional deps not installed or index not built.
- **Knowledge graph**: `scripts/lib/graph.py` + `scripts/extract_entities.py` + `scripts/mcp/vault-graph-server.py`. Kuzu-backed, single-file embedded DB. Closed entity-type (person/project/org_unit/tool/concept/event/document) and relationship-type (WORKS_ON/OWNS/AFFECTS/...) vocabulary per C-3.1. Extraction via Haiku, runs at index time only — never in the synchronous hook path.
- **`vault-graph` MCP server** registered in `.mcp.json`. Tools: `get_entity`, `query_graph` (read-only Cypher; CREATE/MERGE/DELETE rejected), `stats`. Graceful error if kuzu missing or graph not built.
- **Subagents** in `.claude/agents/`: `secure-code-reviewer`, `owasp-llm-reviewer`, `owasp-agentic-reviewer`, `knowledge-synthesizer`. Dispatched by parent skills via the `Agent` tool with `subagent_type`; each has minimum tools + isolated context. Pattern documented in `.claude/agents/README.md`.
- **Voice input**: `scripts/voice-capture.py` records from microphone, transcribes locally via Whisper (no API calls), lands transcript in `00-Inbox/_captured/voice/<date>/`. New `/voice-note` slash command at `.claude/commands/voice-note.md`. Audio kept by default for re-transcription; `--delete-audio` to remove.
- **Optional requirements files**: `requirements-semantic.txt`, `requirements-graph.txt`, `requirements-voice.txt`. Base `requirements.txt` stays lean (PyYAML / anthropic / mcp); user opts into the heavy deps.

### Added — test suite (`test-scenarios/`)

- **14 LLM-behaviour scenarios** — 10 core (foundations: dates / source-reading / asking / memory / project CLAUDE.md / save-on-mention / pickup-thread / doc-layering / sandbox / refuse-fabricate) + 4 for new features (semantic-search, knowledge-graph, multi-agent dispatch, voice-note captures-discipline). Each is self-contained with verbatim prompt + setup + pass/fail criteria + cleanup. Optional-feature scenarios include a graceful-degradation variant.
- **`run-deterministic-checks.py`** — 11 automated checks (D1-D11): YAML schema, hook wiring coverage, rule frontmatter, always-fire presence, no-personal-content scrub, first-run wizard launches, banner renders, subagent frontmatter, optional-lib graceful imports, optional-script launches, closed-vocabulary check (entity + relationship types). Human-readable + `--json` output.
- **`_results-template.md`** — per-run scoring template
- **`README.md`** — how to run, scoring, release bar

### Fixed

- **`scripts/first-run-questions.yaml:tool_exceptions`** — replaced specific EDR vendor example with `<your EDR vendor>` placeholder (caught by personal-content scrub)
- **`test-scenarios/10-refuse-fabricate-scores.md`** — replaced specific tool-name examples with generic language (caught by personal-content scrub)
- **`scripts/hooks/deny-destructive.py`** — generalised protected globs from project-specific paths (`08-Projects/LinkedIn-Agent/voice-examples/**`) to generic patterns (`**/voice-examples/**`, `**/published/*.md`)
- **`.claude/rules/quarterly-report.md`** — removed Vela-specific shorthand keyword

### Status

Private repo during initial validation. Public toggle pending:

- Internal-cohort validation on populated installs (R6)
- Git-history credential scrub before public toggle — Gate 2 (R7)

See [`ROADMAP.md`](ROADMAP.md) for what's next.

[Unreleased]: https://github.com/acunningham-ai/Charon/compare/v0.2.0-preview...HEAD
[0.2.0-preview]: https://github.com/acunningham-ai/Charon/releases/tag/v0.2.0-preview
[0.1.1-preview]: https://github.com/acunningham-ai/Charon/releases/tag/v0.1.1-preview
[0.1.0-preview]: https://github.com/acunningham-ai/Charon/releases/tag/v0.1.0-preview
