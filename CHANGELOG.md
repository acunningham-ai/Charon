# Changelog

All notable changes to this project will be documented here. Format follows [Keep a Changelog](https://keepachangelog.com/). During private validation, releases are tagged `v0.X.Y-preview`. See [`VERSIONING.md`](VERSIONING.md) for when each number bumps (MINOR = new capability, PATCH = update / feedback fix).

## [Unreleased]

### v0.7.0 — Cerberus rule-pack-driven detection (in flight)

Work in progress across multiple incremental commits. See [`cerberus/README.md`](cerberus/README.md) for the layout, the licence boundary, and the chunk-by-chunk roadmap.

**Chunks landed:**

- ✅ Chunks 1+2 — Apache-2.0 attribution scaffolding + vendor of the cisco-ai-defense/skill-scanner rule corpus (66 files: signatures, YARA, policies, prompt templates) into `cerberus/rules/`. Vendor-only — no runtime behaviour change until the engine lands.
- ✅ Chunk 3 — YAML signature matcher engine. `cerberus/engine/{__init__,models,signatures,smoke_test}.py` loads **384 signature rules** from the vendored corpus (ATR 313 + core 45 + promptguard 26), 1 rule gracefully skipped due to uncompilable backreference. Engine handles both top-level YAML shapes (bare list + `{signatures: [...]}` ATR wrap), translates PCRE-style `\u{HEX}` Unicode escapes to Python `re` syntax, and supports an exclude-pattern false-positive suppression layer. Smoke test 4/4 PASS. Run via `python -m cerberus.engine.smoke_test`.
- ✅ Chunk 4 — **YARA-lite interpreter in pure Python (no `yara-x` dep).** Per `feedback_charon_dep_aversion` rule, Adam pushed back on the proposed PyPI dep; reading the corpus showed 13/14 YARA files were really just regex + boolean conditions, and the binary-detection file is ~30 LOC of header-reading. Built `cerberus/engine/yara_lite.py` (~470 LOC) — tokenizer + parser + AST + condition evaluator. Supports literal/regex/hex patterns, `and`/`or`/`not`, parens, `$name at N`, `@name OP N`, bare `@` in for-loop bodies, `for any of ($prefix_*) : (expr)` and `for any of ($a, $b) : (expr)` quantifiers, comments. Out-of-scope YARA features (hex wildcards `??`, hex jumps `[N-M]`, imports, `filesize`, `uintN`, hex alternation `|`) trigger graceful skip-with-warning. 16 YARA rules now live (1 file skipped — unicode-steganography hex alternation). **Cumulative v0.7.0 coverage: 400 detection rules** (384 signatures + 16 YARA). Smoke test 6/6 PASS.
- ✅ Chunk 4b — **`/charon-update` command — single-entry-point update mechanism.** User-facing maintenance command: one slash command updates both the Charon harness itself AND any vendored content (currently the Cisco rule corpus, but designed for arbitrary future sources). Manifest-driven via `scripts/update/sources.yaml` — adding a new updateable source is a YAML entry, not a code change. Two source types in v0.7.0: `github-self` (harness repo: detect upstream commits, offer `git pull --ff-only` if working tree clean + local is strict ancestor) and `github-vendored` (vendored upstream: read pinned SHA, clone shallow at upstream HEAD, copy configured paths, re-pin SHAs, run post-update smoke). Idempotent (no-op when up to date). UTF-8 stdio reconfigured on Windows. Does NOT auto-commit — user reviews `git diff` and commits manually. New files: `scripts/update/charon_update.py` (~440 LOC), `scripts/update/sources.yaml` (manifest), `.claude/commands/charon-update.md`, `.claude/skills/update-charon/SKILL.md`. Per `feedback_charon_ease_of_use`: ONE entry point for users, not one command per source. Designed for future Charon users who don't have the prototype-author's context.
- ✅ Chunk 5 — **Magic-byte file-type detection in pure Python (no `magika` dep).** Per `feedback_charon_dep_aversion`, the proposed `magika` dep (Google's deep-learning file-type detector, ~30MB neural model) was wrong-shape for Charon's needs. Reading what `FILE_MAGIC_MISMATCH` actually has to do — compare a file's first 256 bytes to known magic signatures and flag when content disagrees with extension — showed signature-based detection covers the ~30 common types relevant to skill scanning (ELF/PE/Mach-O, ZIP/GZIP/XZ/7z/RAR, PDF/Office OLE, PNG/JPEG/GIF/BMP/TIFF, shebang scripts, XML/HTML/YAML markers). Trade-off: ~99% accuracy across 200+ types via Magika vs ~95% across ~30 types via in-house. For Cerberus's scope the in-house path is right. New module `cerberus/engine/file_type.py` (~180 LOC). New Charon-authored rule `FILE_MAGIC_MISMATCH` lives in the new `charon` pack (sibling to vendored Cisco packs). Smoke test 9/9 PASS. **Cumulative v0.7.0 coverage: 401 detection rules** (384 signatures + 16 YARA + 1 charon-native).

**Chunks remaining:**
- ⏳ Chunk 6 — V8 sub-check: Unicode homoglyph detection
- ⏳ Chunk 7 — SARIF output format on `/cerberus-vet`
- ⏳ Chunk 8 — Wire engine into the `vet-external-skill` skill
- ⏳ Chunk 9 — Test scenarios + deterministic checks
- ⏳ Chunk 10 — Docs + CHANGELOG release entry + tag

### v0.8.0 — Vault graph improvements (graphify-derived) (planned)

Five capabilities borrowed from the `safishamsi/graphify` evaluation (`reference_graphify.md`, cerberus-vet MEDIUM/78). Don't vendor the package per `feedback_charon_dep_aversion`; borrow patterns into Charon's existing Kuzu-backed vault graph layer (`scripts/lib/graph.py` + `scripts/extract_entities.py` + `scripts/mcp/vault-graph-server.py`):

1. **Leiden community detection** over the existing Charon vault graph — surfaces non-obvious clusters across people / projects / domains / BUs
2. **Interactive HTML graph viewer** — single self-contained `graph.html` (vis-network or D3)
3. **`/vault-query` natural-language graph queries** — BFS/DFS over the vault graph; slash command + skill + helper
4. **Community-based wiki generation** — auto-summary docs per detected community in `07-References/communities/`
5. **Multimodal corpus extraction** — PDF text extraction (modest dep) and audio/video transcription (opt-in `requirements-multimodal.txt`)

v0.8.0 lands after v0.7.0 ships — keeps the release theme coherent (Cerberus rule engine in v0.7.0; vault-graph improvements in v0.8.0).

---

## [0.6.2] - 2026-06-03

**First release without the `-preview` suffix.** The repo flipped public sometime between v0.1.0-preview (2026-05-18) and now, so the versioning convention's *"drop `-preview` at first public release"* clause kicks in. Past tags (`v0.1.0-preview` through `v0.6.1-preview`) stay as historical artefacts — no retagging, no rewriting of past CHANGELOG headers.

### Added — Vault folder scaffolding with per-folder `README.md`

Tester report (same Quick-install path): after `v0.6.1` the wizard wrote `capture-pipeline/config.json` and the memory templates correctly — but the vault folder structure the scripts and hooks reference (`00-Inbox/`, `08-Projects/`, `04-People/`, etc.) didn't exist. Captures would land in folders that hadn't been created; `08-Projects/**` globs in hooks silently no-op'd; the user saw a near-empty vault and had to infer the convention from the docs.

This release scaffolds the standard vault structure during install, with two principled exceptions:

| Folder | Quick install | Full install | Rationale |
|---|---|---|---|
| `00-Inbox/` | ✅ | ✅ | Capture pipeline target |
| `01-Daily/` | ✅ | ✅ | Daily notes |
| `02-BUs/` | ❌ **NEVER** | ❌ **NEVER** | User-defined org layer (departments / business units / clients) — the user creates this with names that match their org. The installer must not pre-create it. |
| `03-Domains/` | ❌ skip | ✅ | Domain organisation lands once Full-mode questions have given the term context; Quick-mode users without that context find the empty folder confusing. |
| `04-People/` | ✅ | ✅ | Per-person context files |
| `05-Meetings/` | ✅ | ✅ | Meeting notes (captured + authored) |
| `06-Decisions/` | ✅ | ✅ | Decision records |
| `07-References/` | (ships in repo) | (ships in repo) | Reference content (Cerberus docs, framework refs) is in the repo already |
| `08-Projects/` | ✅ | ✅ | Active projects; many hooks glob `08-Projects/**` |
| `09-Archive/` | ✅ | ✅ | Cold storage; `scripts/archive-captures.py` writes here |

Each scaffolded folder gets a short `README.md` explaining its purpose, common subfolders, and naming convention. Content stays generic — no Vela / CISO-specific examples that would lock in an opinionated structure.

**Idempotency.** Folders and READMEs that already exist are skipped — re-running the wizard, switching from Quick to Full later, or running `--phase <name>` on an existing install all behave correctly. Re-runs that find everything already in place print *"vault folder structure: already scaffolded (no changes)"*.

**Why scaffold instead of leaving empty.** The harness ships ~50 references across hooks, scripts, and skills to paths like `00-Inbox/_captured/**`, `08-Projects/**`, `09-Archive/_captured/<YYYY>/`. On a fresh install with no scaffolding, these are all silent no-ops — the user sees the rules and skills "working" but the vault never accumulates anything they'd expect to see. Scaffolding fixes the mismatch between marketed convention and on-disk reality.

**Why not scaffold `02-BUs/`.** This is the deliberate user-defined layer. A 47-BU software group uses business-unit names; a traditional company uses departments (HR, IT, Finance, etc.); a solo consultant might use client names. Pre-creating an empty `02-BUs/` implies an opinion the harness doesn't have. The user creates this folder themselves once they know what shape it should take. Documented in the `08-Projects/README.md` and the wizard's summary line.

### Why this is a PATCH and not a MINOR

The install capability has existed since v0.1.0-preview. This release makes the post-install vault state match what the rest of the harness already references — refinement of an existing capability, not a new one. Authoring test (*"could a user describe this as 'now I can do X' where X is new?"*) is no: the user is still installing; the installer just produces a more useful starter state. Consistent with the v0.4.2 (Quick mode added) and v0.6.1 (M365 wired into Quick mode) precedents — both PATCHes that refined install reach.

---

## [0.6.1-preview] - 2026-06-03

Two tester-reported install bugs, both fixed and verified end-to-end on Windows. Mirror-applied to the macOS / Linux installer in the same release per the cross-platform-parity rule (installer drift is a recurring class of bug; close it at source).

### Fixed — Windows install docs: `~/second-brain` doesn't expand for `git`

Tester ran the documented quick-start in PowerShell and ended up with a literal `~` directory in the current working directory, with `second-brain` nested inside it. Subsequent commands broke because most Windows tooling doesn't treat `~` as a home-dir shortcut consistently.

**Why this happens.** `git` is a native binary. Neither PowerShell nor `cmd.exe` expands `~` before passing arguments to native commands — only PowerShell *cmdlets* expand `~` via the path-provider. The docs were written from a bash-first mindset and assumed `~` expansion that doesn't apply on Windows.

**Fix.** `INSTALL.md`, `README.md`, and `CONFIGURATION.md` now split the quick-start / updating blocks into two platform-specific code fences:

- macOS / Linux: `git clone ... "$HOME/second-brain"`
- Windows (PowerShell): `git clone ... "$env:USERPROFILE\second-brain"` with an inline warning against using `~/...`.

Verified via sandbox repro: the broken instruction reproduces the bug (git emits `Cloning into '~/second-brain'...` and creates a literal `~` dir); the fixed instruction lands the clone at the expected path. Backslash vs forward-slash variants of `~` both fail the same way — git is the bottleneck, not the path separator.

### Added — Quick mode now offers M365 capture-pipeline setup

A second tester report — *"the installer doesn't add M365"* — surfaced a deeper gap in the Quick install path introduced in v0.4.2-preview. Quick mode previously asked only 3 identity questions and skipped the entire `workflow` phase, where every capture-pipeline question lives. Users picking the default option finished the wizard with a wizard summary saying "Quick install complete" but no `capture-pipeline/config.json` written and no email capture configured.

**Why this matters.** The README sells M365 capture as *"Working — device-code OAuth, paginated inbox + sent, cursor-based incremental"*. A tester reasonably expects the installer to wire it up when they pick the default install path. The gap between marketed and delivered was real.

**Fix.** Quick mode now asks one additional question — *"Set up an automated email capture pipeline? (y/n)"*. On `y`, it walks two M365 questions inline (tenant ID + client ID) and auto-populates sensible defaults for provider (m365), sent items (on), schedule frequency (daily), and schedule time (07:00) via a new `apply_implicit_propagations()` helper. Quick mode stays M365-only by design — Gmail / IMAP users still run `python scripts/first-run.py --phase workflow` for the full flow.

After the wizard's write step, `bootstrap_capture_pipeline()` automatically runs `npm install` in `capture-pipeline/`. Fail-soft if Node isn't present — the wizard does not abort; it prints clear manual recovery steps.

Two things explicitly stay manual:

1. **Device-code OAuth flow** (`node fetch-mail.mjs auth`) — interactive (user copies a code into a browser), so the wizard prints it as next-step #1 rather than driving it.
2. **Scheduled task registration** — platform-specific (Windows Task Scheduler / cron / launchd), printed as next-step #3 with the Charon-supplied wrapper-script path. See `EMAIL-PROVIDER-SETUP.md` §Scheduling for the per-platform walk-through.

### Added — Node.js 18+ as a detected prerequisite in `install.ps1` / `install.sh`

Capture-pipeline is Node.js. Before this release, neither installer detected or installed Node — users following the wizard could end up with a written `capture-pipeline/config.json` and no Node runtime to execute it. Inserted as new Step 3 between Obsidian (Step 2) and Python dependencies (now Step 4). Same auto / manual / skip ladder as Python, mirrored across the two installers:

- **Windows (`install.ps1`)** — `winget install OpenJS.NodeJS.LTS`. New `-SkipNode` switch.
- **macOS / Linux (`install.sh`)** — `brew install node` / `sudo apt-get install nodejs npm` / `sudo dnf install nodejs npm` / `sudo pacman -S nodejs npm`. New `SKIP_NODE=1` env var. Distro Node versions on older Debian/Ubuntu may be <18; the installer prints a NodeSource / nvm pointer in that case rather than silently installing an unusable version.

Skipping Node is supported (the harness's other capabilities — rules, hooks, MCP, skills — don't depend on Node) and prints a clear warning that the capture pipeline cannot run without it.

### Fixed — `UnicodeEncodeError` in the wizard on Windows (pre-existing latent bug)

While verifying the Quick-mode M365 path in a sandbox, the wizard crashed with `UnicodeEncodeError: 'charmap' codec can't encode character '→'`. Root cause: Python on Windows defaults `sys.stdout` to cp1252 in piped / non-TTY contexts, and several question descriptions in `first-run-questions.yaml` contain Unicode characters (`→` in the M365 tenant-ID hint *"Find this in Entra ID → Overview → Tenant ID"*, em-dashes in many descriptions, `§` in cross-references).

**Latent because** none of the affected questions were reachable in Quick mode before this release. Full-mode users in TTY contexts didn't hit it because Python uses the console's encoding (typically UTF-8) when stdout is a real terminal. Quick mode reaching `m365_tenant_id` for the first time exposed the bug immediately.

**Fix.** `configure_stdio_for_unicode()` runs at wizard start and reconfigures `sys.stdout` / `sys.stderr` to UTF-8 on Windows. No-op on macOS / Linux. Python 3.7+ supports the `.reconfigure()` method; Charon's minimum is 3.10, so safe.

### Fixed — Mixed-slash path in env-var output

`$env:HARNESS_SECRETS_DIR = "C:\Users\Adam/.secrets"` — backslash for the home portion, forward slash from the YAML default's join. Cosmetic, but ugly and risks tripping native commands that parse env-var paths. Fixed by normalising path-type env-var values through `Path()` in `env_var_hints()` before formatting. Surfaced during the Quick-mode dry-run investigation; bundled into this release rather than carried as a separate ticket.

### Why this is a PATCH and not a MINOR

The capture-pipeline capability shipped in v0.1.0-preview. Quick mode shipped in v0.4.2-preview. M365 setup has always been reachable via Full mode. This release wires the existing pieces together so a Quick-mode user can reach M365 end-to-end, and adds the Node prerequisite so the bootstrap actually works after the wizard writes config.

Authoring test (*"could a user describe this as 'now I can do X' where X is new?"*) — borderline, same shape as v0.4.2-preview. Yes for the Quick-mode UX (Quick mode users can now set up M365 in ~60 seconds without dropping to Full mode). No for the underlying capability surface (M365 wiring, capture pipeline, Quick mode all existed). Conservative read per the v0.4.2 precedent → **PATCH**.

---

## [0.6.0-preview] - 2026-06-02

### Added — Verdict vocabulary + monitor-mode shadow-testing for hooks

Introduces a structured verdict layer (`allow` / `deny` / `ask` / `observe`) for hooks that gate tool calls, plus a `HARNESS_MODE=monitor` env var that downgrades every `ask`/`deny` to `observe` for shadow-testing new rules before they enforce. Every verdict is appended to a daily JSONL audit log at `state/verdict/{YYYY-MM-DD}.jsonl` so promotion decisions are evidence-based, not vibes-based.

**New files (`scripts/hooks/`):**

- **`_verdict.py`** — the verdict-emit module. `emit_verdict(hook, rule, verdict, reason, context, session_id)` writes a structured line and returns the *effective* verdict (after monitor-mode downgrade). `verdict_to_exit_code()` and `write_ask_stderr()` round out the surface. Fail-silent on audit-log error; fail-closed on unknown verdict (typo'd verdicts become `deny`, surfaced via rule tag). Concurrent-safe append via `_jsonl_append.safe_append_line`.
- **`_jsonl_append.py`** — cross-platform safe-append helper. Windows uses `msvcrt.locking` with retry; POSIX uses `fcntl.flock LOCK_EX`. Falls through to unlocked write on lock-acquisition timeout rather than dropping the line.

**New rule:** `.claude/rules/verdict-vocabulary.md` — auto-loads under `scripts/hooks/**` and for prompts about hook authoring. Documents the four verdicts, monitor mode, the module surface, conventions for hook authors (including the secret-redaction obligation on `context`), and the audit-log shape.

**Hook upgrade:** `validate-write-path.py` is the first adopter of the verdict layer. Emits a verdict on every decision (`config-error`, `config-empty`, `allowlist-match`, `allowlist-miss`). Exit codes unchanged — the verdict log is purely additive observability. Fail-silent import-guard means the hook keeps working if `_verdict.py` is missing.

### Added — `/harness-watch-review` skill (end-of-shadow promotion call)

Companion to the verdict layer. Reads the verdict audit log over a window (default: last 14 days), surfaces per-rule monitor-mode fire counts, asks the user to classify each fire (TP / FP / borderline), and recommends — per rule — **promote to enforcing**, **kill**, or **extend monitor period** against the trust-build threshold (≥2 false positives in a fortnight → kill until reviewed). Decision-grade, not daily — run end-of-shadow-window for each new rule.

### Added — `/linkedin-reply` skill (interactive reply drafter)

Sibling to `/draft-linkedin` (new posts) and `/linkedin-metrics` (engagement). Takes a pasted inbound LinkedIn message (DM, comment, or thread reply), classifies the reply context, picks an intent (acknowledge / engage / decline / handoff), drafts **two short candidates** with different angles, and inlines them for fast copy. Optional save to `08-Projects/LinkedIn-Agent/replies/{YYYY-MM-DD}-{slug}.md` with `trust: untrusted` frontmatter on the source excerpt. Loads `voice-content.md` for voice anchors; never auto-saves; never auto-promotes to memory.

### Added — `voice-anchor-ralph-loop.py` (PostToolUse verbatim-lift detector)

Deterministic hook that catches verbatim lifts from voice-anchor files into drafts. When Claude writes a draft under `08-Projects/LinkedIn-Agent/drafts/**`, the hook scans for 10+ word runs that appear in any sibling `voice-examples/` file. **Talk anchors** (frontmatter `type: speaker-talk|talk`) trigger a HARD violation (per the voice-content rule, source content is PREMISE not COPY). Other voice-examples trigger a soft violation (don't republish your own past prose). Exit 2 with stderr listing the lifted phrase + source file, so Claude rewrites before showing the user. Wired into PostToolUse for Edit|Write|MultiEdit.

### Test-scenarios — STANDALONE_HOOKS extended

`run-deterministic-checks.py` STANDALONE_HOOKS allowlist now includes `_verdict.py` and `_jsonl_append.py` (imported by hooks, not invoked directly by Claude Code). D2 (Hook wiring coverage) continues to PASS. Full suite remains **11 PASS, 0 WARN, 0 FAIL** after the v0.6.0 additions.

---

## [0.5.0-preview] - 2026-05-27

### Added — Missed-run catchup (logon + unlock) for scheduled harness tasks

Reliability enhancement. The harness's daily scheduled tasks are deliberately interactive-only (never wake-from-sleep, never run-when-logged-off, per the security baseline). The tradeoff: if the machine is asleep / off / on battery at the scheduled time, that day's run is silently skipped and TODO / triage / digest go stale until the next day.

This release ships an optional catchup that closes that gap **without** breaking the interactive-only rule — it fires at logon and on workstation unlock (both moments the user is present), so nothing becomes unattended.

**New files (`capture-pipeline/`):**

- **`login-catchup.ps1`** — gated, parameterised catchup. Gates: (1) before the scheduled hour → defer; (2) freshness file (default `<vault>/TODO.md`) already today's → no-op; (3) a target task already running → don't pile on; (4) otherwise → trigger the configured task(s) **sequentially** (concurrent runs can corrupt shared capture-cursor / dedup state). Parameters: `-Tasks`, `-FreshnessFile`, `-VaultRoot`, `-NotBeforeHour`, `-DryRun`.
- **`register-login-catchup.ps1`** — one-time elevated registration. Creates a task with logon + workstation-unlock triggers, RunLevel Limited (non-admin), `AllowStartIfOnBatteries` (runs when a laptop lid opens unplugged — the case the daily task skips), `WakeToRun=False` (compliant — never wakes the machine). Idempotent (`-Force`).

**Docs:** `CONFIGURATION.md` §Scheduled tasks gains a "Reliability enhancement — missed-run catchup" subsection covering the gates, the elevated-registration step, the `-DryRun` test path, the PS 5.1 ASCII-only gotcha, and the macOS/Linux `anacron` / systemd-`Persistent=true` equivalent.

**Why this matters.** The interactive-only rule is the right security posture, but on a laptop that sleeps it means the morning automation frequently just doesn't run. Catchup makes the *attended* path self-heal: open your machine any time after the scheduled hour and the missed run completes, gated so it never double-runs or runs stale. The rule's security guarantee is preserved; only the reliability gap is closed.

---

## [0.4.2-preview] - 2026-05-25

### Added — Quick install path (`--quick`): 3 questions, ~60 seconds

Tester feedback flagged the 24-question first-run wizard as too tech-heavy and clunky for non-developer audiences. This release adds an **Express path** that gets a user productive in ~60 seconds with sensible defaults for everything that isn't load-bearing on day one.

**New behaviour:**

- **Interactive prompt at the top of the wizard** — first time you run `python scripts/first-run.py`, you're asked:
  ```
  How configured do you want to start?
    1. Quick — 3 questions, ~60 seconds. Sensible defaults for everything else.
              Get productive immediately; refine any phase later with --phase.
    2. Full  — 24 questions across 4 phases, ~20 minutes. Voice, org structure,
              framework, integrations all captured up front.
  Choice [1/2, default 1]:
  ```
- **`--quick` and `--full` flags** for non-interactive use.
- **Quick mode asks 3 questions only** — name, role, organisation. Auto-defaults: vault path = `$cwd`, secrets dir = `~/.secrets`, Anthropic key setup deferred, voice / org structure / framework / integrations skipped.
- **Tail message after Quick completes** explicitly names the four `--phase <name>` commands to refine any deferred phase later. Users see the path forward, not a dead end.
- **`--phase`-targeted runs and resume-from-state runs bypass the mode prompt** — they're always full-breadth within the requested scope.

**Why this matters.** Charon's stated audience is "tech people a great resource, non-tech people a place to start with full capability". Tester feedback (May 2026) showed the previous install undershot on the non-tech side — too many concepts upfront (audience tiers, org-units, framework specifics, voice exercise). Quick mode is the answer: meet non-technical users where they are, get them functional in a minute, let the rules do their universal work, and let users refine over weeks.

The harness's discipline layer (always-fire rules, save-on-mention, confidence tags, session-start ritual) all still fire from day one — those don't depend on the deferred phases. What Quick mode defers is the *tailoring* layer, not the *enforcement* layer.

### Changed — INSTALL.md and FIRST-RUN.md updated

- **`FIRST-RUN.md`** — new "Quick path" section at the top with the three-question summary, list of defaults, and refinement commands. Existing Full path documentation preserved.
- **`INSTALL.md`** — bootstrap handoff section now mentions the Quick / Full choice and points at `FIRST-RUN.md` for details.

### Why this is a PATCH and not a MINOR

Same wizard capability, new mode option. The first-run wizard has been present since v0.1.0-preview; Quick mode is a feedback-driven refinement that makes the existing capability friendlier. Authoring test (*"could a user describe this as 'now I can do X' where X is new?"*) is borderline — the user-experience IS materially different in Quick mode — but the underlying capability set is unchanged. Calling it PATCH per the conservative read of the versioning rule. If validator response confirms this opens a significantly broader audience, the next semver MINOR bump can re-classify retroactively in narrative.

---

## [0.4.1-preview] - 2026-05-25

### Added — Cerberus documentation at the level the capability deserves

Two doc improvements landed together — `CAPABILITIES.md` and `README.md` now describe Cerberus at the level its industry-first positioning earns.

- **`CAPABILITIES.md` Cerberus section** — expanded from a brief intro + 5-row table to a multi-paragraph writeup that names the gap (defensive AI-installation security is under-tooled while offensive tooling proliferates), the three load-bearing properties that earn the industry-first frame (defensive shape, secure construction, standards grounding), and an inline V0–V8 → OWASP Top 10 for LLM Applications (2025) crosswalk table. Each command row now carries an italic *Example:* tail with a concrete use case.
- **`README.md` Cerberus section** — same positioning, written for the broader audience. Adds `/cerberus-deps` to the command list (was 4 commands; now 5). Names the validation-honest framing and the compromise registry explicitly.
- **`CAPABILITIES.md` all-command example tails** — every command in the catalogue (26 total, across Reporting / Security review / Workflow / Hygiene / Cerberus) now carries an italic *Example:* tail with a concrete scenario.

### Why this is a PATCH and not a MINOR

Documentation only — no capability changes, no new commands, no skill or hook surface added. The Cerberus capabilities have been there since v0.3.0-preview / v0.4.0-preview; the docs now match what's already shipped. Authoring test (*"could a user describe this as 'now I can do X' where X is new?"*) is no — same capability, sharper writeup.

---

## [0.4.0-preview] - 2026-05-25

### Added — `/cerberus-deps` — audit your own project's deps against the compromise registry

A new slash command + backing skill that walks your project for dependency manifests (Python `requirements*.txt` / `pyproject.toml` / `setup.py`, Node `package.json`, Go `go.mod`, Rust `Cargo.toml`, Ruby `Gemfile`), parses every declared package + version-spec, and cross-references each against the **compromise registry** maintained in `07-References/dependency-pinning-discipline.md` (v0.3.2-preview).

This is the **recurring sibling** of `/cerberus-vet`. Where `/cerberus-vet` evaluates a third-party artifact pre-install, `/cerberus-deps` audits your *own* project's deps on demand — every install, every PR, every quarterly review.

**What it produces:**

- **Verdict** — `CLEAN`, `FINDINGS-PRESENT`, or `TYPOSQUAT-PRESENT` (the last escalates to incident-response posture)
- **Compromise hits** with package, ecosystem, declared spec, excluded versions, suggested pin, source citation
- **Load-bearing pins** — packages where the spec already correctly excludes the compromise window (positive notes; don't drop the pin)
- **What passed cleanly** — count of deps confirmed not in the registry (note: this is registry-cross-reference only, NOT a full SCA / CVE audit)
- **Recommended next step** keyed to the verdict

**Usage:**

```bash
/cerberus-deps              # audit current directory
/cerberus-deps ./my-project # audit a specific project path
```

**Why it matters.** A manifest is a security artefact. The compromise registry pattern was established in v0.3.2-preview as a forward-looking discipline; `/cerberus-deps` makes it **runnable** instead of paper-only. Run it after any dep addition or version bump to confirm the pin held.

### Changed — `/cerberus-vet` V8 layer extended with registry cross-reference

The V8 (dependency footprint) step in the `vet-external-skill` skill now also cross-references each declared dep of the *vetted* artifact against the same compromise registry. Same registry, two surfaces:

- `/cerberus-vet <repo-url>` catches typosquats / compromise-window versions in the **artifact's** deps before you adopt
- `/cerberus-deps [path]` catches the same patterns in your **own** project on a recurring basis

Both fail gracefully ("compromise-registry cross-reference skipped — discipline doc not in scope") if the discipline doc isn't reachable.

### Changed — `run-deterministic-checks.py` allowlist

`cerberus-deps.md` added to the Joh Leonhardt attribution allowlist for the No-personal-content scrub check. Mechanical addition to keep D5 green now that the new command exists.

### Why this is a MINOR and not a PATCH

`/cerberus-deps` is a new invokable capability — new slash command, new skill, new audit surface. Authoring test (*"could a user describe this as 'now I can do X' where X is new?"*) — yes: "now I can audit my own project's dependencies for known supply-chain compromises". That's MINOR.

---

## [0.3.2-preview] - 2026-05-25

### Added — `validation_status` field on Cerberus vet findings

Every Cerberus vet finding now carries a `validation_status` field with three possible values:

- **`theoretical`** — pattern matched against the artifact's source / structure / metadata via the static V0–V8 model. The default for everything the current Cerberus produces.
- **`partial`** — pattern matched AND a secondary signal corroborates (README confirms, a non-invasive probe confirmed behaviour, etc.). For cases where evidence is stronger than static-only but a full PoC was not reproduced.
- **`validated`** — the finding was reproduced via dynamic exercise of the artifact in a sandbox. Reserved for the future dynamic-eval layer.

**Why it matters.** Without this field, every finding reads as if the risk is confirmed. The static-vs-dynamic distinction is invisible to the consumer of the report. Adding `validation_status` makes it visible AND future-proofs the report shape — when a dynamic-eval layer eventually ships, older outputs don't need a migration. Borrowed from the `usestrix/strix` framing where they ship "validated PoCs" vs "theoretical findings".

### Added — `07-References/dependency-pinning-discipline.md`

A new reference doc establishing the practice for adding or bumping any dependency in this harness or in projects built with it:

- **Compromise registry** — known-bad package versions across PyPI and npm (LiteLLM 1.82.7/8, telnyx 4.87.2, tiledesk-server 2.18.6–12, pino-sdk-v2 typosquat, Mini Shai-Hulud cascade). Each entry cites a source and names the action.
- **The practice** — five steps (check registry → read release history → pin with intent → comment the why → audit before deploy) with examples of the three pinning patterns (compatibility-release, upper-bound exclusion, exact pin) and what to avoid.
- **Audit state** — manifest-by-manifest cross-reference against the registry. As of 2026-05-25 no known-compromised versions are present in any current manifest. Discipline is forward-looking.

**Why it matters.** A dependency manifest is a security artefact, not just a build artefact. The pinning posture should be the default, not the exception — and it should be documented somewhere reviewers can read instead of folklore.

### Why this is a PATCH and not a MINOR

Both additions sit inside existing capabilities. `validation_status` adds a field to `/cerberus-vet`'s existing report template — same skill, sharper output. The dependency-pinning doc is a reference, not a new capability. Authoring test (*"could a user describe this as 'now I can do X' where X is new?"*) is no — the user is still vetting artifacts and managing dependencies; both just got more disciplined.

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

[Unreleased]: https://github.com/acunningham-ai/Charon/compare/v0.6.2...HEAD
[0.6.2]: https://github.com/acunningham-ai/Charon/releases/tag/v0.6.2
[0.6.1-preview]: https://github.com/acunningham-ai/Charon/releases/tag/v0.6.1-preview
[0.6.0-preview]: https://github.com/acunningham-ai/Charon/releases/tag/v0.6.0-preview
[0.5.0-preview]: https://github.com/acunningham-ai/Charon/releases/tag/v0.5.0-preview
[0.4.2-preview]: https://github.com/acunningham-ai/Charon/releases/tag/v0.4.2-preview
[0.4.1-preview]: https://github.com/acunningham-ai/Charon/releases/tag/v0.4.1-preview
[0.4.0-preview]: https://github.com/acunningham-ai/Charon/releases/tag/v0.4.0-preview
[0.3.2-preview]: https://github.com/acunningham-ai/Charon/releases/tag/v0.3.2-preview
[0.3.1-preview]: https://github.com/acunningham-ai/Charon/releases/tag/v0.3.1-preview
[0.3.0-preview]: https://github.com/acunningham-ai/Charon/releases/tag/v0.3.0-preview
[0.2.0-preview]: https://github.com/acunningham-ai/Charon/releases/tag/v0.2.0-preview
[0.1.1-preview]: https://github.com/acunningham-ai/Charon/releases/tag/v0.1.1-preview
[0.1.0-preview]: https://github.com/acunningham-ai/Charon/releases/tag/v0.1.0-preview
