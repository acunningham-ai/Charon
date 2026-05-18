# Changelog

All notable changes to this project will be documented here. Format follows [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added — reliable email capture (no more silent failures)

A common frustration with scheduled email capture: it runs at 7am, your sign-in has expired overnight, and the script gets stuck waiting for you to sign in again — but nobody's there. You discover the failure hours later, missing a day of mail.

This release fixes that. Three changes work together:

- **The scheduled pipeline now fails fast instead of hanging.** When your saved sign-in is no longer valid (this happens periodically because of your company's normal security policies), the capture script exits immediately with a clear message instead of waiting forever for someone to type a code.
- **You get notified the moment it happens.** A native desktop notification pops on your screen (Windows toast, macOS notification, Linux notify-send — whichever your system has) saying *"Capture pipeline: re-auth required."*
- **Your next Claude Code session reminds you too.** A small file on disk acts as a flag. Next time you start Claude Code, the first response begins with a short banner showing exactly what command to run and how long ago the failure happened. The flag clears automatically the moment you successfully sign back in.

**Recovery is one command:** `cd capture-pipeline && node fetch-mail.mjs auth` — about sixty seconds to enter the code your browser displays. The next scheduled run picks up where it left off.

If you've ever been annoyed that your capture pipeline silently lost a morning of email, this is the fix.

Technical implementation: new `setNonInteractive()` on the M365 provider, `--non-interactive` CLI flag on `fetch-mail.mjs`, distinct exit code `2` on auth failure, `state/REAUTH-NEEDED.flag` JSON marker, cross-platform notification logic in `scheduled-capture.bat` and `scheduled-capture.sh`, new `scripts/hooks/check-reauth-flag.py` SessionStart hook wired in `.claude/settings.json`.

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

[Unreleased]: https://github.com/acunningham-ai/Charon/commits/main
