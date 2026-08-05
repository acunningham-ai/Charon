# Changelog

All notable changes to this project will be documented here. Format follows [Keep a Changelog](https://keepachangelog.com/). During private validation, releases are tagged `v0.X.Y-preview`. See [`VERSIONING.md`](VERSIONING.md) for when each number bumps (MINOR = new capability, PATCH = update / feedback fix).

## [Unreleased]

*Nothing pending — next change lands here.*

---

## [0.27.0] - 2026-08-05

### Added — stop untrusted text being laundered into the trusted zone

Captured content and calendar events were already treated as untrusted **in flight**: the source carries `trust: untrusted` and three separate files tell the model to paraphrase rather than quote. The residual was what happens when it is **written down**.

A note assembled from a calendar event lands in `05-Meetings/` — outside the captured zone, in the part of the vault later sessions read as **authored and trusted**. Quote a crafted invite subject verbatim into it and the hostile text has crossed the trust boundary *by being saved*. Nothing about its untrusted origin survives the write, so a future session sees an ordinary authored note and may act on what it says. Every layer guarding this was prose.

Now mechanical, as a third layer on `validate-interactive-write.py`:

- Commands that read untrusted sources declare **`reads-untrusted: true`** in frontmatter. Eight do, each verified by reading the command: `meeting-prep`, `draft-linkedin`, `forum-agenda`, `prometheus`, `weekly-checkin`, `eod-reflect`, `refresh-todo`, `knowledge-consolidate`. `vault-lint` and `safe-rebuild` were **excluded** — they name the captured zone only to say they never touch it — and `capture-screenshot` writes *into* the captured zone, which the captures rule already governs.
- A durable markdown note from such a command must carry **both** `trust: derived-untrusted` in frontmatter (machine-readable, so tooling can filter) **and** a body line containing `DERIVED FROM UNTRUSTED INPUT` (model-readable, at the point of reading — the one that actually changes behaviour). Missing either is an `ask`.
- The captures rule gains a *"Writing untrusted content DOWN"* section defining the vocabulary and what reading such a note obliges, and `/meeting-prep`'s output template now carries both markers with the reason attached.

Deliberate boundaries, so the gate stays usable rather than getting switched off:

- **Layer 3 runs before the scope verdict and independently of it.** A note can be perfectly in-scope and still launder text; returning early on a scope match would have skipped this check entirely.
- **Only markdown is gated.** A command may legitimately write a JSON state file, and demanding prose markers there would be noise.
- **Writes into `00-Inbox/_captured/**` and `_harness/**` are exempt** — already governed.
- **When the payload carries no full content** (an `Edit` sends a patch), the marker cannot be verified, so it logs `provenance-unverifiable` as `observe` rather than returning a clean pass. An unverifiable case recorded as verified is how a control becomes a story about a control.

Guarded by the extended **D31**, which now also fails if `meeting-prep` stops declaring `reads-untrusted`, if an unmarked note does *not* fire, or if a correctly marked note *does* (a false positive is as disqualifying as a miss). Negative-tested by stripping every declaration: D31 reports *"layer 3 is inert"*.

Still `SHADOW = True` — logs, blocks nothing, review window before enforcing.

**Honest limit:** the content check depends on the `Write` payload carrying `content`. That holds for the documented tool shape and matches how `deny-destructive.py` already reads `old_string`/`new_string` for `Edit`, but it has not been confirmed against a live payload in a Charon-configured session 🟡 — hence the explicit `provenance-unverifiable` branch rather than an assumption that content is always inspectable.

---

## [0.26.0] - 2026-08-05

### Added — write-path confinement for interactive commands (ships in shadow)

`validate-write-path.py` only engages when `HARNESS_UNATTENDED_ALLOWLIST` is set, i.e. for scheduled `claude -p` runs. So an interactive command's write path was governed by prose in its own definition and nothing else.

`/meeting-prep` makes the gap concrete: it derives an output filename from a person's name that **originated in a calendar event** — a string an attacker can influence by sending you an invite. Its stated rule (lower-case, strip to `[a-z0-9-]`, resolve under `05-Meetings/`) is genuinely protective *if applied*, and a hostile subject like `../../CLAUDE.md` does slug to something harmless. But that is **model adherence, not a control**: nothing failed closed if the model got it wrong.

New hook `scripts/hooks/validate-interactive-write.py`, with two layers that fail differently:

- **`protected-zone`** — always on, needs no knowledge of the running command. Catches writes resolving outside the project root (the `..`-traversal case) and writes to `.secrets/**`, `.claude/settings.json`, `scripts/hooks/**` (a write there could disable the gates themselves), `.git/**`, and `.gitattributes` (losing that re-breaks every workflow — see D30 in v0.25.0).
- **`command-scope`** — confines a command to the `write-scope:` declared in **its own frontmatter**, so the authority on where a command may write is the command definition, not a table inside a hook that drifts away from it.

**How it knows which command is running.** A PreToolUse payload contains no field naming the active slash command, so the obvious approach is to grep the prompt for `/name` on UserPromptSubmit. That is a guess — the word appears conversationally too — and a guess that *blocks a write* is a false positive with teeth. Claude Code invokes a typed command **through the `Skill` tool**, whose `tool_input` carries the name, so `skill-usage-log.py` records the invocation and the gate reads it. An observation, not an inference. The record is per-session and TTL-bounded (900s), so one session's scope cannot constrain another's writes, and an abandoned command stops constraining the rest of the session.

**Verdict is `ask`, never `deny`.** Every one of these targets is something a person could legitimately mean to write; what is being prevented is a path the *model* derived wrongly. `ask` blocks and explains so you can confirm and retry.

**The hook fails OPEN** — deliberately the opposite of its unattended sibling. That one guards runs nobody is watching, where crashing beats an unbounded write. This one runs interactively, where a bug in the gate itself would block a human's legitimate work with no route around it. Availability wins for the interactive layer; the unattended layer keeps failing closed.

Guarded by **D31 `check_interactive_write_gate`**, which fires real payloads through the hook as a subprocess rather than reading it — a confinement control that is never fired is a claim, not a control. Because the hook ships in shadow, exit codes are 0 either way, so correctness is asserted on the **emitted verdict**. Negative-tested twice: removing a protected glob fails it, and stripping every `write-scope:` fails it with *"layer 2 is inert"*.

**Coverage is partial, and reported as such: 5 of 24 write-capable commands declare a scope** (`meeting-prep`, `prometheus`, `draft-linkedin`, `forum-agenda`, `refresh-todo`). Those five state their output path unambiguously. Guessing the other nineteen would ship false positives into a confinement control, which is how confinement controls end up switched off. D31 prints the ratio on every run so the gap stays visible instead of reading as complete. An undeclared command is **unenforced, not permitted-by-default**, and logs `no-scope-declared`.

**Ships in `SHADOW = True`** per shadow-before-enforce: it logs and blocks nothing until the flag is flipped after a review window. A brand-new confinement gate that blocks on day one turns every unanticipated write into a broken command.

### Fixed — shadow mode was overstating enforcement in the audit log

First cut emitted `verdict="ask"` and then returned 0 during shadow, so the audit log recorded `effective: ask` for calls that were never blocked. That is worse than no log: the review window that decides whether to enforce would have been reading fiction, and `declared`/`effective` diverging is reserved for monitor mode under the verdict vocabulary. Shadow now emits `observe` with the intended verdict in `context.would_be` and `enforced: false`.

---

## [0.25.1] - 2026-08-05

Clears the content-drift queue surfaced by the parity detector. Name-level parity had reported these files as matching; the drift detector compares function inventories, and three of the four findings turned out to be real defects rather than cosmetic divergence.

### Added — write-path allowlist integrity check

`scheduled-audit.py` gains `allowlist_integrity()`, reported as section 6. `validate-write-path.py` checks a write target *against* the allowlist; nothing checked the allowlist itself. A glob widened to `**/*.md` passes every hook while confining nothing — **the control reports healthy precisely when it has stopped working.** Now flagged: match-everything globs, globs with no directory anchor, globs targeting protected paths (`CLAUDE.md`, `MEMORY.md`, `settings`, `.secrets`, `.claude/rules`), malformed JSON, empty `write_globs`, and an `allowed_high_sensitivity` opt-in.

Genericised on the way in: Charon ships no allowlists — you write your own and point `HARNESS_UNATTENDED_ALLOWLIST` at it — so this **discovers** `*.allowlist.json` across candidate roots rather than assuming one path, and stays quiet when you have none rather than claiming a pass it did not earn.

A positive control also exposed a precedence bug: `**/CLAUDE.md` reported as "no directory anchor" when the accurate reason is "targets a protected path". Still caught, but the message would send you to fix the anchor and keep the protected target. Most-specific reason now wins.

### Fixed — voice notes could silently overwrite each other

`voice-capture.py` gains `unique_path()`, applied to both output paths. The transcript name resolves only to the minute (`%H%M`), and the `.wav` name was the bare slug with **no timestamp at all** — so `--slug "decision-on-deploy"` used twice in one day overwrote the first recording outright. A voice note you cannot re-record is not a recoverable loss, so this avoids the collision rather than detecting it.

### Fixed — knowledge-graph extraction silently dropped content from large files

Three compounding defects in `extract_entities.py`, all silent:

- **`HAIKU_MAX_TOKENS` was still `1500`** — the value raised to `8000` upstream precisely because it truncated entity-rich files. Same function names, different constant: exactly the drift name-level parity cannot see.
- **Input was truncated at 30,000 characters** with no warning. Every entity past that point was never extracted, and the run reported success.
- **Output truncation was undetectable.** A cut-off response failed JSON parsing and surfaced as `"haiku returned non-JSON"` — a fixable size problem disguised as a model fault.

Now: `chunk_content()` splits on heading boundaries, `call_haiku()` reports `stop_reason == max_tokens` as `{"_truncated": True}`, and `extract_file()` resolves truncation by re-splitting. One failed chunk no longer costs the whole file, and partial extraction is **reported** as `_partial` rather than banked as a clean run.

Writing tests for the port found a further flaw in the original: `chunk_content` split only on `\n`, so a file with **no newlines** — a minified blob, an ingested one-paragraph transcript — came back as one oversized chunk and the docstring's hard-split guarantee was false. `extract_file` still recovered it via the truncation path, but only after spending a wasted API call to discover the problem. Overlong lines are now hard-split first. Fixed upstream too, so the two do not diverge again on this.

### Recorded as accepted drift — `vault_query.py`

Not every divergence is a gap, and porting churn has a cost. `_emit_explain` / `_emit_neighbours` / `_emit_path` are **refactor-only**: Charon's `main()` inlines the identical logic line-for-line (verified, not assumed). `run_saved` is harness-only — its saved-query shortcuts are hardcoded to personal names, and porting as-is would ship identity into a public repo. The generic form, user-defined saved queries read from config, is a real capability worth having and is roadmapped rather than improvised here.

---

## [0.25.0] - 2026-08-04

A minor bump rather than a fourth patch, deliberately: **every workflow was unlaunchable on Windows**, and burying that as `v0.24.4` would understate a release existing users need to take.

### Fixed — all three workflows were dead on arrival on Windows (CRLF)

`/review`, `/deep-research` and `/devils-advocate` could not launch from a fresh clone on Windows. The `Workflow` tool refuses a script containing control characters, and **CR (U+000D) is one**.

The repo was not at fault in any way a normal check would see — the committed blobs were clean LF and stayed clean. The damage happened at **checkout**: with no `.gitattributes`, working-tree line endings are decided by each user's `core.autocrlf`, which defaults to `true` on Git for Windows. A fresh clone rewrote every LF to CRLF, and every workflow script became unlaunchable. Verified by cloning the public repo with `-c core.autocrlf=true`: **3 of 3 workflow scripts came down as CRLF.**

This is the failure mode worth dwelling on. Every gate was green. The blob was right, the syntax was right, `node --check` passed, D22 confirmed the workflows were present and valid, and the capability was still broken for most users. Checking the artifact you committed says nothing about the artifact your user receives.

**The fix is two-part, because either half alone is insufficient:**

- **`.gitattributes`** pins `eol=lf` (authoritative over `core.autocrlf`), with `*.bat`/`*.cmd` kept CRLF on purpose — cmd.exe's parser can mis-handle labels and `goto` targets with bare LF.
- **D30 `check_workflow_scripts_launchable`** fails on any control character in a workflow script *and* on a missing `eol=lf` pin. Cleaning the files without the pin would let the next checkout undo it; adding the pin without cleaning would leave existing clones broken. It reads the **working tree**, not the blob — reading the blob is precisely what would have missed this. It also fails if it finds no scripts at all, so it cannot pass vacuously.

Negative-tested both ways: seeding 5 CRLF into `deep-research.js` fails it, and stripping the `eol=lf` directives fails it. The pin check ignores comments, because `.gitattributes` explains the CRLF problem at length and matching the explanation instead of the directive is the same false-positive class already fixed in `score-vault.py` and D28.

**Existing clones do not self-heal** — git only rewrites files it checks out. After pulling, run `git add --renormalize . && git checkout -- .`, or re-clone.

### The same bug reappeared in the commit that fixed it

Worth recording rather than tidying away. The first attempt at this release put **CRLF into `CHANGELOG.md`** — because Python's `write_text` translates `\n` to `os.linesep` on Windows, and the release notes are written with a script. D30 passed it, because D30 as first written only inspected `.claude/workflows/*.js`.

So the guard scoped to the three files that had already broken would have shipped a fresh instance of the same defect in the same commit. D30 now sweeps **every tracked text file** in the working tree for CR, not just the workflows. The authoring tooling reintroduces CR by default; a control that only watches the place it last went wrong is not a control.

Two follow-on notes: `git ls-files --eol` reported the index as clean while the committed blob genuinely contained 1,181 CR bytes — it reports attribute intent, so `git cat-file` is the authority. And piping `git show` into a reader can itself translate line endings, so the measurement has to go to a file first.

**How it was found:** `/review` failed to launch with *"script contains control characters."* The file had no character in any invisible Unicode category — because the scan excluded `	

` as legitimate, which whitelisted the culprit. `devils-advocate.js` launching fine while `review.js` did not isolated it to a per-file property rather than the tool; raw-byte inspection then showed `review.js` was CRLF and the other two were LF. `read_text()` had hidden it throughout: universal-newline translation silently converts CRLF to LF, so every earlier measurement of line endings was invalid.

---

## [0.24.3] - 2026-08-04

### Added — publishing is deterministic instead of hand-forced

`.github/workflows/deploy-pages.yml`: checkout → verify `docs/index.html` exists → configure-pages → upload `docs/` → deploy-pages. A push touching the site is now a deploy, and a failed deploy is a red run rather than silence. `workflow_dispatch` replaces the old habit of forcing a build through the API.

Legacy branch-based Pages (`main:/docs`) auto-published on **1 of 4** releases: v0.23.0 ✗, v0.24.0 ✗, v0.24.1 ✗, v0.24.2 ✓. Every failure looked like a success from the repo side — green push, tag on the remote, live site quietly serving an older commit. **Intermittent is worse than broken:** a consistent failure gets a step built around it; a 1-in-4 success trains you to assume it worked.

Deliberate choices:

- **Does not run `site/build.mjs`.** Generated pages are committed and `docs/index.html` is hand-maintained (`build.mjs` prints *"index.html left standalone"*), so building in CI could overwrite the homepage on every deploy. The artifact is the committed `docs/` tree exactly as reviewed.
- **Actions pinned to full commit SHAs, not tags** — a tag is mutable, a SHA is not. Version numbers were resolved from the GitHub API rather than recalled; the recalled majors were stale (`actions/checkout` is v7, not v4).
- **Refuses to publish without `docs/index.html`** — a deploy must not be able to succeed while serving an empty site.
- **`cancel-in-progress: false`** — cancelling a Pages deploy mid-flight can leave the site half-published.

Verified in both directions rather than assumed: the `on: push` trigger **fired** on a commit touching the watched paths and correctly **did not fire** on a commit that changed no site file; the `workflow_dispatch` run went green with the deployment recorded at HEAD and all 10 site pages returning 200 with the corrected counts. So the trigger is proven to fire and the job is proven to deploy. *(Closed in v0.25.0: a push touching `docs/` fired the trigger and completed the deploy at HEAD in Actions mode — the full path is now exercised.)* **Real limit:** nothing gates deploy on the check suite yet, so a push that skipped the local gates could still publish.

Requires the repo's Pages source set to **GitHub Actions** (`build_type=workflow`). Rollback if needed: set it back to `legacy` with source `main` / `/docs`; the published site stays up throughout either switch.

### Fixed — ROADMAP undercounted path-conditioned rules

Said 13; there are 14. Found by hand while editing the file — `ROADMAP.md` is deliberately outside D29's scope because it quotes other projects' inventories, so this class of drift stays manual here. Worth stating plainly rather than fixing quietly: the check does not cover everything, and pretending otherwise would be its own kind of stale claim.

---

## [0.24.2] - 2026-08-04

### Added — D29: public count claims are now checked against reality

`test-scenarios/run-deterministic-checks.py` gains **D29 `check_public_counts_match_reality`**. It counts what the repo actually ships — commands, rules, hooks, agents, workflows, MCP servers, deterministic checks, behaviour scenarios — then reads every `N <noun>` claim in the public docs (README, CAPABILITIES, SECURITY, CONFIGURATION, INSTALL) and every published page under `docs/`, and fails on any number that does not match.

Two design choices worth stating, because they are what stops it being noise:

- **Acceptable values are a set, not a number.** README legitimately states rules as *4 always-fire* + *14 path-conditioned* as well as *18* total, so the check accepts the total and the real breakdown, and rejects everything else. Sub-counts are computed (`always: true` in frontmatter), not hardcoded.
- **`CHANGELOG.md` and `ROADMAP.md` are out of scope on purpose.** A changelog *should* keep its historical numbers, and the roadmap quotes other projects' inventories — including both would guarantee false positives, and a check that cries wolf gets ignored.
- **Hooks are counted from what `settings.json` wires**, not from files in `scripts/hooks/`. An unwired script is not a hook; a wired one nobody documented is precisely the drift being hunted.

It also fails if it finds *zero* claims to inspect — a checker that silently stops matching would otherwise pass vacuously forever.

### Fixed — three surfaces were undercounting hooks

README, ROADMAP and the site all advertised **10 hooks** (ROADMAP: 11) while `.claude/settings.json` wires **12**. `poisoning-scan.py` (untrusted-capture screen) and `check-todo-freshness.py` were both live and both unlisted. Now 12 everywhere, with the two missing names spelled out.

This one undersold rather than oversold, which is why it survived several releases unnoticed — nobody audits a number that flatters them less than the truth. D29 does not care about the direction of the error, which is the point.

### Fixed — `CAPABILITIES.md` check count

Was 28; now tracks the suite (29). Found by D29 the moment `CAPABILITIES.md` came into its scope, which is a reasonable first witness for the check earning its place.

---

## [0.24.1] - 2026-08-04

### Fixed — the website was left behind by v0.24.0

The v0.24.0 release reconciled the counts in README / CAPABILITIES / ROADMAP but not in the published site, so `docs/index.html` went on telling the public **52 commands, 3 MCP servers, 27 deterministic checks** while the repo shipped 53, 4 and 28. Now corrected, and the data-layer card mentions the opt-in calendar reader alongside the three vault servers.

This is worth recording rather than quietly patching, because it is the *same* failure as the two-release site lag fixed earlier: the repo docs get updated at release time and the site is treated as a follow-up. It isn't one. If a capability count changes, the site changed — a page that states specific numbers to the public is either right or it is misleading, and being right in `README.md` does not help a reader who is looking at the homepage.

---

## [0.24.0] - 2026-08-04

### Added — a read-only calendar, and a meeting prep that pitches to the room

- **`scripts/mcp/calendar-server.py` — bundled read-only calendar MCP (new capability, OPT-IN).** Microsoft 365 or Google Calendar, so `/helios`'s morning brief and the new `/meeting-prep` can see what is actually on today. It is **off by default and does nothing until you register your own OAuth client and sign in once** — this is the only bundled server that reaches off your machine and holds a credential, so enabling it should be a decision you make, not one you inherit. Charon ships no client ID: a shared one would make every user's traffic look like the same application and let whoever owned it observe consent.

  **Zero new dependencies.** The device-code and PKCE flows are hand-rolled on the standard library rather than pulling `msal` + `cryptography` + `PyJWT` into a security tool. Nothing parses the token either — it is carried as an opaque bearer string, which is also Microsoft's own guidance for APIs you do not own.

  **No client secret is stored, for either provider.** Microsoft's device-code grant is a public-client flow and has none. Google *issues* one for Desktop clients but states that installed apps "cannot keep secrets" and lists `client_secret` as optional in the installed-app token exchange — so Charon uses PKCE and never asks for, reads, or stores it.

- **`/meeting-prep` (new command).** Resolves who the meeting is with — a name, or `next`/`today` from the calendar server if you have wired it — and builds one agenda pitched to your **reporting direction** to that person. That direction is the whole point: an upward agenda leads with the decisions and spend they own and leaves out your working; a downward one leads with blockers and development; a peer one explicitly separates *"I need your call"* from *"you should be aware"*; an external one advises rather than instructs. It also carries forward the previous meeting note's unactioned items, because a recurring 1:1 that forgets last time is theatre. Writes exactly one dated agenda to `05-Meetings/` and nothing else.

### Least privilege, deliberately narrower than the obvious scope

Worth stating as a pattern rather than a footnote, because on **both** providers the obvious scope is meaningfully wider than the necessary one:

| Provider | Obvious choice | What Charon requests | Why |
|---|---|---|---|
| Microsoft | `Calendars.Read` | **`Calendars.ReadBasic`** | Reads events *"except for properties such as body, attachments, and extensions"*. The server deliberately never returns the event body anyway — it is the largest prompt-injection surface and useless for a 30-second brief — so the narrower scope and the code's real needs coincide exactly. |
| Google | `calendar.readonly` | **`calendar.events.owned.readonly`** | `calendar.readonly` grants *"See and download **any** calendar you can access"*, including calendars merely shared with you. The narrower scope is *"See the events on Google calendars you own"*. |

Anything not on the read-only **allowlist** — `Calendars.Read`, `Calendars.Read.Shared`, `Calendars.ReadWrite`, the full Google `auth/calendar`, `calendar.events`, or a scope this server has never heard of — is **never requested, and refused if granted**: the token is discarded rather than cached and sign-in fails loudly. **A provider that reports no scope at all is also refused**, because a permission set that cannot be verified is not a permission set you should hold. A read-only tool quietly holding a write token is worse than no tool.

Tokens live in your per-host secrets directory — deliberately **outside the vault**, so one can never be swept into a synced or committed note — written `0600` where the filesystem supports it, and never printed, logged, or included in tool output. Calendar output carries an explicit untrusted-content marker: anyone who can put a meeting on your calendar can put text in its subject.

New deterministic check **D28** enforces all of the above offline: the narrow scopes must be the *defaults*, exactly one read tool may exist, no `client_secret` may appear in code, and both fail-closed paths must raise *and* leave no file behind. Negative-tested against a widened Microsoft scope, a mutating tool name, and a real `client_secret` in the token exchange — each fails the check as it should.

### Hardened by review before shipping — two fail-open bugs found and fixed

This release went through the full review pipeline (secure-code + OWASP-LLM + OWASP-agentic). Both blocking findings were the same species: **a security property the file claimed that the code did not actually deliver.**

- **The fail-closed scope check was failing open.** Granted scopes were validated against a *blacklist* of write-capable markers, and the granted string defaulted to `""` when a provider omitted the `scope` field. An empty string matches no marker, so a token whose permissions could not be verified at all was cached silently — the precise inversion of a fail-closed control. RFC 6749 §5.1 permits a compliant provider to omit that field, so this was reachable, not theoretical.

  The blacklist was also incomplete in three separate places (`Calendars.Read`, `auth/calendar.events`, `auth/calendar.events.owned` all passed), and the obvious patch would have rejected our *own* `Calendars.ReadBasic`, since one scope name is a substring of the other. Three holes in one list is a design problem, not a gap to fill.

  **Scope validation is now an allowlist** (`ALLOWED_SCOPES`): enumerate what is permitted, refuse everything else, and treat **silence as refusal**. It accepts the bare and full-URI forms of the same grant, tolerates benign identity scopes (`openid` / `profile` / `email` / `offline_access`) a provider may add unbidden, and refuses everything unrecognised.

- **Google fetched more than it needed.** The Microsoft request restricted fields with `$select`; the Google request restricted nothing, so the event `description` (the body), `attendees` with their email addresses, `conferenceData` and `attachments` all crossed the network before being discarded client-side. The body-exclusion promise was true of what reached the model but not of what left the provider — and a client-side filter only holds until the next edit to the formatter. Google now sends an explicit `fields=` parameter, matching Microsoft's provider-side enforcement.

Also fixed from the same review: the token file is now created **atomically at `0600`** via `os.open` (`write_text` followed by `chmod` left it world-readable for a few microseconds under a typical umask); the loopback listener lets `HTTPServer` bind the ephemeral port itself instead of probing for a free one and binding it afterwards, removing a race where another local process could claim the port in between; and `URLError` is caught so a network failure during `--auth` prints a clear message rather than an unhandled traceback.

**D28 now covers the regression that shipped.** The earlier version of the check only tried known-bad scope strings, so it passed while the absent-scope case cached a token — the test agreed with the bug. It now asserts that absent, empty and whitespace-only scopes are all refused, that each previously-missed broader scope is refused, and that our own scopes (both forms, plus benign extras) are still accepted. Verified by reintroducing the fail-open and confirming D28 fails.

### Honest limits

- **Two protections remain instruction-level, not enforced.** `/meeting-prep`'s output-path confinement, and the "paraphrase, don't quote" rule that stops untrusted event text being written verbatim into trusted notes, are both prose read by the model with no code gate behind them. Both are now named roadmap items rather than left implicit — see ROADMAP *Near-term*.
- **Google is implemented but unverified** — the loopback+PKCE path has not been exercised against a real Google account. Treat it as untested until you have.
- **Google's *device* flow cannot be used for calendars at all.** Its permitted scope list (`email`, `openid`, `profile`, `drive.appdata`, `drive.file`, `youtube`, `youtube.readonly`) is exhaustive and excludes Calendar, which is why the Google provider uses a different grant rather than matching Microsoft's.

Docs: commands 52 → **53**, MCP servers 3 → **4** (one opt-in), deterministic checks 27 → **28** across README / CAPABILITIES / ROADMAP, plus a new CONFIGURATION.md section (*Calendar — least privilege by default*) covering setup, the scope rationale, and why you register your own client. Suite **28/28**.

---

## [0.23.2] - 2026-08-03

### Fixed — a split memory index no longer reports its own files as orphans

`score-vault.py`'s memory-index check only ever read `MEMORY.md`, so it never followed **sub-indexes**. `MEMORY.md` is loaded every session and therefore has a real size ceiling; the way to stay under it is to split a domain out into its own `*_index.md` and link that from `MEMORY.md`. Every file reachable only through such a sub-index was being reported as *"exists on disk but not in MEMORY.md"* — a false positive that arrives precisely when your vault has finally grown enough to need the split, i.e. exactly when you least want to be told your index is broken.

Indexed now means **linked from `MEMORY.md`, or from any reachable `*_index.md` it links**. Anchored to `MEMORY.md` so only *reachable* sub-indexes count, and generic on the `_index.md` suffix so new ones work with no code change. Broken links declared directly in `MEMORY.md` still raise a finding, and a genuine orphan — reachable from nothing — is still caught; verified with a fixture covering direct links, the sub-index itself, a file reachable only via the sub-index, and a true orphan.

This also makes the "is this file indexed?" question a single named function (`indexed_memory_names`) rather than logic inlined in one check, so a future real-time enforcer and this periodic detector cannot drift apart on the definition.

---

## [0.23.1] - 2026-08-03

### Fixed — two detectors that reported a problem every day on a healthy vault

Both were false positives *by construction* rather than bugs that fire occasionally. That distinction matters: a detector which cries wolf on a fixed schedule trains you to ignore it, so it costs you the real finding later.

- **`harness-watch.py` — the TODO-freshness detector false-fired every afternoon.** It compared `TODO.md`'s **mtime** against a 6-hour threshold at the post-run check. But `TODO.md` is regenerated once each morning, so by roughly 14:00 local its mtime is *always* over threshold — the detector reported "the daily refresh may not have completed" on a vault where it had completed perfectly. It now reads the **`generated:` frontmatter date** and stays silent when that is today, consulting mtime only when no `generated:` line exists. This also brings the watch detector in line with the SessionStart `check-todo-freshness.py` hook, which already decided staleness this way — the two surfaces had disagreed. A stale `generated:` date still raises the finding, and a missing file still raises it regardless.
- **`audit-unattended-run.py` — skill-curator's own report was billed to the agent.** The C-5 audit infers authorship from mtime, so if the skill-curator runs on a schedule that overlaps an unattended run, its deterministic analyser output lands inside that run's audit window and appears as an "out-of-scope write". `00-Inbox/_reports/skill-curator/` is now excluded. It needed its own entry rather than riding on the `_captured/` rule, because curator output is analyser output, not untrusted capture.

Detector selftests were extended alongside both fixes — including negative cases asserting a stale `generated:` date and a missing file still fire, so the fix cannot silently become a blind spot. Deterministic suite **27/27** (D24 still proves 8/8 detectors fire-capable); no capability counts changed, so README/CAPABILITIES/ROADMAP and the website are unaffected.

---

## [0.23.0] - 2026-08-03

### Added — the seat tranche (front doors, not fences)

Charon has grown to 52 commands. That is a lot of surface to hold in your head, and the honest problem is not that any command is wrong — it is that you have to know *which one* to reach for. This tranche adds **three named front-door seats plus a review pipeline** that take a plain-language ask and route it to the proven verb, then add something none of the underlying verbs produce alone.

**Seats are additive. Nothing is removed, hidden, tiered, or demoted.** Every verb a seat routes to keeps working exactly as before and stays documented as a first-class capability. If you prefer the verbs, use the verbs.

- **`/athena` — the knowledge seat (new capability).** One door to your own vault: *find* a note you half-remember (`/recall`), see how things *relate* (`/vault-query`), catch where your notes *contradict* each other (`/find-tensions`), *gather* a topic into a framework (`/knowledge-consolidate`), materialise graph *links* (`/graph-backfill`), or *remember* something (`/save-feedback` · `/push-fact` · `/promote-rule`). Defaults to the cheapest move (`find`) and escalates only if the hits warrant it; cites the note path behind every answer. **Memory writes are proposed, never silent** — you see the target file, the frontmatter, and the index line, and nothing lands without your yes. Retrieved content is treated as data, never as instructions.
- **`/helios` — the daily-cadence seat (new capability).** A morning **brief** rather than three commands run in a row: what changed since the last brief, what's on today, what's owed and still open, then *"today in a sentence"* plus the single first thing to do. Evening and weekly delegate to `/eod-reflect` and `/weekly-checkin`. Read + surface: it **offers** `/refresh-todo`, it never silently rewrites `TODO.md`. **Calendar is optional and user-configured** — Charon ships no calendar integration, so the brief works without one and gets better if you wire your own *read-scoped* calendar MCP tool into the command and agent (instructions in the command). Both captured content **and** any fetched calendar data are treated as untrusted — anyone can put text in your inbox or on your calendar, so a crafted subject is something to report, never to act on.
- **`/hephaestus` — the tune-up seat (new capability).** One prioritised maintenance report instead of six separate chores: runs the health and hygiene detectors (`/harness-doctor`, `/score-vault`, `/vault-lint`), names the headline improvement and curation opportunities, and returns a single **broken / messy / could-improve** list — most-impactful first, with the exact command to fix each, ending on the one highest-value fix. **Surfaces and proposes; never auto-fixes**, never archives, never rewrites. There is no auto-apply path: every fix is your deliberate step.
- **`/review` — the security-review pipeline (new workflow).** Folds five verbs into one door and adds what running them by hand cannot: it scopes the target and auto-detects whether LLM and agentic surface are present, fans out **only the applicable lenses in parallel** (`secure-code-reviewer` always, plus `owasp-llm-reviewer` and `owasp-agentic-reviewer` as warranted), merges and dedupes by `file:line:category`, then **adversarially false-positive-checks every non-passing finding** — two independent skeptics re-read the cited line and are instructed to *refute*; 2/2 "does not reproduce" withdraws the finding. Returns a verified, severity-ranked list with withdrawn false positives shown separately, and flags `/safe-rebuild` candidates **for you to run** — it never edits code.
- **Prometheus reaches past search (enhancement).** The research seat is now taught when to use the deep-read utilities: `/docs` before any library/API/version claim (so a version fact comes from live official docs, not training data), `/ingest` for a rich PDF/DOCX advisory that `WebFetch` cannot read, and `/webfetch` for a full clean read of a JS-heavy page. Prompt-only — **no tool grant changed**; Prometheus stays no-Bash by design, and the persona is explicit that these run in the command path and that it must say what it couldn't read rather than fabricate a document's contents.
- **`clean-signal-gate` (new rule).** The governance rule behind every self-\* capability, keyword-gated: **no loop runs on an unverified signal.** Self-healing requires idempotent, reversible actions confirmed by a *deterministic* post-check; self-improving may learn only from verified ground truth, never from its own output (model collapse / data autophagy). Includes a clean-vs-dirty signal table — if the signal isn't verified, the work in front of you is "fix the signal", not "build the loop".

### Fixed — two detectors that cried wolf

Both of these made a control *less* trustworthy by generating findings that were never real. A tool that opens with a wall of phantom problems teaches you to skim past it, which costs you the genuine finding later — so these are correctness fixes, not polish.

- **`score-vault.py` — three false-positive classes in the vault-hygiene scorer.**
  1. **Nested frontmatter `type:` was read as missing.** The check matched only a flat top-level `type:`, but the graph-aware nested form (`metadata:` → `node_type` + `type`) is what Claude Code's own memory-writing format produces. Every nested-convention memory file was flagged "missing field: type". Both shapes are now accepted.
  2. **Filenames merely *mentioned* in prose were reported as broken cross-references.** The old pattern matched any bare `reference_*.md` / `feedback_*.md` / `project_*.md` / `user_*.md` token anywhere in a file, so a note that *discussed* another note by name was treated as linking to it. Only real markdown-link targets (`](name.md)`) are checked now, and pathed links are skipped.
  3. **A note documenting link syntax flagged its own examples.** A `](name.md)` written inside inline code or a fenced block is documentation of a link, not a link. Fenced blocks and inline-code spans are now stripped before matching (fences first, so a fence containing backticks can't leave stray inline pairs).
  Dangling `[[wikilinks]]` remain deliberately unflagged — an unresolved wikilink to a real-but-unwritten idea is a legitimate authoring pattern, not drift. The now-unused `MEMORY_REF_RE` and `REQUIRED_FRONTMATTER` constants were removed rather than left as dead code.

- **`audit-unattended-run.py` (C-5 post-run audit) — stopped blaming the agent for other processes' writes.** The audit infers authorship from file mtime alone, so *anything* writing inside the run window was attributed to the unattended agent. It now excludes machinery churn (verdict/telemetry/skill-usage state, snapshots, `.log` files, harness notes) and the captured-content zone — the agent is separately blocked from writing there, so files under it belong to the capture pipeline. Without this, every run reported the same fixed block of "out-of-scope writes"; verified on a fixture where 6 such files were correctly excluded while a genuine out-of-scope write and a high-sensitivity `MEMORY.md` change were both still caught. The docstring states the residual limitation plainly: the exclusion assumes your preventive write-path hook actually fires, so verify that wiring rather than assuming it.

### Hardened by the review pass before shipping

This tranche was put through `/review` itself (all three lenses fired). Verdict: **0 blocking.** Three findings survived adversarial verification and were fixed rather than annotated:

- **Seat personas now declare no `Bash` at all.** Athena originally carried a bare `Bash` grant with a comment explaining that agent frontmatter cannot express the `Bash(python scripts/recall.py:*)` scope its command declares. The comment was accurate and still wasn't a control: the effective grant widened to whatever `settings.json` permits (`Bash(python scripts/*)` — every script in `scripts/`, including mutating ones), and no PreToolUse hook gates `Bash`. Three independent lenses flagged it. **An unscopeable grant is now removed rather than documented** — all three seats are `Read, Grep, Glob, Skill`, `find` mode's retrieval backend runs in the `/athena` command path, and the persona defers honestly if it cannot execute. Least privilege is now enforced by the grant, not by prose.
- **`/review` no longer truncates silently.** Findings beyond the `MAX_VERIFY` cap were absent from every output array with no signal to the caller, so a truncated review was indistinguishable from a clean one. The cap now reports what it dropped in the log, in a new `unverifiedDropped` array, and in the summary line.
- **`/review`'s verify prompt now fences untrusted input.** Finding fields are produced by a lens agent that read the target code, so they can carry attacker-influenced text. They are now wrapped in explicit `BEGIN/END UNTRUSTED FINDING` markers with an instruction to treat the contents as a claim to test and never as a directive.

Two of these were pre-existing in the author's own harness rather than port defects, and were fixed in both trees.

The review's *withdrawn* findings are worth noting as evidence the verify stage earns its cost: a flagged calendar-injection risk was withdrawn because the ported Helios ships **no calendar tool at all** — the finding described the private harness, not this code; a demanded credential-redaction was withdrawn as a provable no-op; and a token-budget finding was withdrawn for invoking a control that governs a different execution path.

### Honest notes on the seat pattern

- **Where the tools actually run.** Each seat is a command (which has the shell) paired with an agent persona (which reasons and prioritises). A sub-agent whose `tools:` exclude `Bash` **cannot** execute a Bash-needing verb it dispatches via `Skill` — `Skill` loads a command's instructions, it does not grant tools. Rather than widening the grants (which would let a read-only seat run *action* verbs' shell steps), each persona is instructed to report plainly that a detector couldn't run and defer to the command path. **No persona may present inferred or hand-simulated output as detector output.**
- **Not validated on cold users.** The seat pattern is intended to reduce "which command do I reach for" friction. That claim is reasoned, not measured against new users — treat the seats as an additive convenience, not a proven onboarding fix.

New deterministic check **D27** (`check_seat_routing_integrity`) asserts each seat exists as a command plus paired agent, declares its tool grant **in frontmatter** (not merely mentioning `tools:` in prose), and — the real drift risk when porting from a richer private harness — that **every slash-verb a seat routes to actually exists in this repo** as a command or workflow. Proven discriminating against three distinct regressions: a dangling verb reference, a missing frontmatter tool grant, and a deleted seat file.

Docs: command count 49 → **52**, agents 7 → **10**, workflows 2 → **3**, path-conditioned rules 13 → **14**, deterministic checks 26 → **27** across README / CAPABILITIES / ROADMAP (this pass also corrected pre-existing drift where two README rows and one CAPABILITIES row still read 25). Deterministic suite **27/27** green; personal-content scrub (D5) clean. *Ported from the author's harness, proven there first, then genericised — per the local-first-then-Charon rule.*

---

## [0.22.0] - 2026-07-29

### Added — retrieval + hygiene tranche
- **Local retrieval that fits the vault — `/recall` (new capability).** A dependency-free hybrid ranker over your authored notes: an Okapi BM25 body arm and a title arm fused by Reciprocal Rank Fusion (`scripts/recall.py` + `scripts/lib/fusion.py`), **no embeddings, no vector database, no network** (Claude Code only, by design). Finds the note you half-remember and prints path + which arm matched + a snippet; complements the vault-graph (*how things connect*) and `search_memory` (the harness memory dir). New deterministic check **D26** builds a tiny corpus and asserts the matching note ranks top (suite → 26).
- **Catch where the vault disagrees with itself — `/find-tensions` (new capability).** Surfaces two notes asserting incompatible facts (a date, a number, a verdict, an owner) on a topic and writes one `type: tension` note per contradiction citing both sources side by side. It **surfaces, never resolves** — never averages, never picks a winner, never edits the sources; you adjudicate.
- **Pressure-test a plan against your own record — `/grill` (new capability).** Interrogates a plan one question at a time, first grounding it against what the vault has already decided (`06-Decisions/`, memory, `TODO.md`) so you don't re-litigate settled ground or contradict a prior call. Read-only; the consistency-with-the-record sibling to `/devils-advocate` (adversarial) and `/brainstorm` (divergent).
- **Cross-session baton — `/handoff` (new capability).** Writes a dated handoff note plus a paste-ready "next-session kickoff prompt" and proposes a one-line `MEMORY.md` Pickups update (shown for confirmation, never silent-written), so a thread resumes after `/clear` or days away without re-deriving.
- **Clean-room port discipline + verifier (new rule + tool).** New path/keyword rule `.claude/rules/clean-room-port.md` — how to bring a third-party skill/agent/hook in safely (recon-as-data in an isolated sub-agent → red-flag gate → re-author from spec → verify → record provenance), plus `scripts/verify_no_copy.py`, which asserts a re-authored artifact shares no verbatim run ≥ N chars with its source (whitespace-normalised; import/comment boilerplate filtered). Protects against both prompt-injection contamination and verbatim-copy / licence exposure.
- **`thoroughness-over-false-efficiency` (new rule).** Keyword-gated behavioural discipline: completeness and reliability come before token/step "efficiency"; a saving is acceptable only if provably lossless (no directive, trigger, or check removed).

Docs: command count 45 → **49**, path-conditioned rules 11 → **13**, deterministic checks 25 → **26** across README / CAPABILITIES / ROADMAP. Deterministic suite **26/26** green. *Ported from the author's harness, proven there first, then genericised (no personal/Vela/BU content) — per the local-first-then-Charon rule.*

---

## [0.21.0] - 2026-07-20

### Added
- **Self-improving harness gains a deterministic learning loop on the vault-hygiene signal (new capability).** Until now `/harness-improve` only *unified* existing human-gated primitives and explicitly disclaimed being a learning loop. Its hygiene-drift arm is now a genuine — but deliberately *narrow* — **deterministic learning loop**, four scripts wiring `score-vault` into a closed cycle: `scripts/vault-hygiene-ledger.py` appends a daily deterministic hygiene snapshot to an append-only ledger; `scripts/vault-hygiene-recurrence.py` derives, purely from that ledger, which finding-classes PERSIST / RISE / REAPPEAR (digit-normalised finding identity, so a drifting embedded count doesn't read as a new finding); `scripts/vault-hygiene-proposal.py` turns a recurring class into a tracked **structural-prevention proposal** (observe/propose-only — it never edits anything; the human supplies the change + benefit text and captures the class's baseline; `--apply` timestamps the fix with a `YYYY-MM-DD` guard); and the keystone `scripts/vault-hygiene-postcheck.py` asks the only question that matters — *did the recurrence actually fall after the fix?* — and answers it **deterministically from the ledger's own counts, with zero model self-assessment** (`--record` appends the verdict to an append-only outcome history, fenced to the state dir so a mistyped path can't clobber an authoritative file). *Why this dodges model collapse:* the loop is only ever allowed to conclude a change helped because a deterministic signal says recurrence dropped — never because a model graded its own work. A fix that didn't hold returns `no_change` / `worse`, surfaced honestly rather than buried. New deterministic check **D25** (`check_self_improving_postcheck`) writes a synthetic ledger + applied proposals and asserts the post-check discriminates resolved / no_change / worse correctly (suite → 25). *Honest ceiling, stated plainly:* it ships **propose-only / human-final-say** — nothing is auto-applied; it learns **only** from the deterministic ledger, never from its own output; it is proven on fixtures + the author's own harness, not at scale; and the broader "watches its own operation across the whole harness and learns which changes raised outcome quality" loop remains roadmapped behind its own clean-signal gate + shadow window + adversarial review. `/harness-improve`'s hygiene-drift arm and its roadmap note were rewritten to match this reality; the other three arms (promote-rule / skill-eval / curate-skills) are unchanged and still unify existing primitives.

Docs: README + CAPABILITIES self-improving descriptions updated from "unifies existing primitives, not a learning loop" to "the deterministic learning loop now exists (recurrence → propose → apply → post-check)" at the honest ceiling above; deterministic checks 24 → **25** everywhere the count appears. Deterministic suite **25/25** green; personal-content scrub (D5) clean.

---

## [0.20.0] - 2026-07-16

### Added
- **Design references — brand-contract layer, motion presets, and design dials (new + expanded references).** New `07-References/design-contract-template.md`: a per-surface `DESIGN.md`-style **brand contract** — one file that *commits* to a single coherent look (colour roles, typography, components, layout, elevation, motion, do's-and-don'ts, plus an **agent prompt guide**) so a coding agent renders in-brand without re-choosing every build. This **commitment layer** complements the existing `design-system-reference.md` **selection layer** (*how to choose* + the a11y floor) — flow: choose using the reference/CSVs → pin in a contract → hand the contract to `frontend-design`/`artifact-design`. The 9-section schema is adapted from **nexu-io/open-design** (Apache-2.0, attribution in `NOTICE`); the WCAG AA floor, the design-dials intake, and the CSV cross-references are additions. Also brings two design references to full parity: new `07-References/motion-presets.md` (zero-dependency, copy-ready CSS transitions keyed by interaction — modal/dropdown/toast/… — with `prefers-reduced-motion` baked in; the plain-CSS counterpart to `motion.csv`, re-derived from transitions.dev, no code copied), and a **Design dials** intake section (DESIGN_VARIANCE / MOTION_INTENSITY / VISUAL_DENSITY) added to `design-system-reference.md`. All static/advisory, no execution surface. *Why:* a reference tells you how to *choose* a look but doesn't *pin* one, so multi-build surfaces drift; a committed contract keeps every build on-brand and makes the look agent-operable, and the motion/dials references remove the two remaining hand-waves in the design flow.

---

## [0.19.0] - 2026-07-16

### Added
- **Self-healing harness watch + `/harness-doctor` — the harness watches its own operational surface and names the limits of its own vision (new capability).** New `scripts/harness-watch.py` walks the harness by *discovery* (never a hand-maintained list, so a new file of a known class is covered automatically) and runs health detectors: workflow `meta.name`↔filename + every harness `.py` compiles (static validity), command/agent/rule frontmatter validity, and — when a capture pipeline is configured / on Windows — auth-token age, capture freshness, TODO refresh, recent automation failures, and hung scheduled-task / process checks. `/harness-doctor` runs the whole set on demand and prints a **coverage self-report**: what it inventoried, what it has *no detector for* (blind spots), and a per-detector **selftest** proving each can still fire — so a detector can't silently go dead and read as "all healthy". Ships **observe-only**: nothing is enforced, nothing is auto-fixed; it surfaces each issue with ranked fix options and a human decides. `PROMOTED_RULES` is empty by default — each user runs their own shadow window and promotes a signal observe→enforcing via `/harness-watch-review`. New deterministic check **D24** runs the watch's selftests (suite → 24). *Why:* a harness that reads your files and fires tools accumulates its own failure surface; the honest move is a read-only observer that can name where it's blind, not a green light on a dead sensor.
- **Self-improving survey `/harness-improve` — where the harness could do what it already does *better* (new capability).** Unifies existing, already-shipped, human-gated primitives (`/promote-rule`, `/skill-eval`, `/curate-skills`, `score-vault` drift) into one survey that presents each opportunity as a **plain-English change + the concrete benefit**, ranked by benefit ÷ effort, with the exact command to act — and you decide. Same governance as self-healing: clean/verified signals only, human-final-say, nothing auto-applied. *Honest ceiling:* this unifies primitives that already exist — it is **not** a learning loop. The deeper capability (a loop that watches its own operation and learns which changes raised outcome quality) is roadmapped with its own clean-signal gate + shadow + adversarial review, not shipped.
- **Design references — brand-contract layer, motion presets, and design dials (new + expanded references).** New `07-References/design-contract-template.md`: a per-surface `DESIGN.md`-style **brand contract** — one file that *commits* to a single coherent look (colour roles, typography, components, layout, elevation, motion, do's-and-don'ts, plus an **agent prompt guide**) so a coding agent renders in-brand without re-choosing every build. This **commitment layer** complements the existing `design-system-reference.md` **selection layer** (*how to choose* + the a11y floor) — flow: choose using the reference/CSVs → pin in a contract → hand the contract to `frontend-design`/`artifact-design`. The 9-section schema is adapted from **nexu-io/open-design** (Apache-2.0, attribution in `NOTICE`); the WCAG AA floor, the design-dials intake, and the CSV cross-references are additions. Also brings two design references to full parity: new `07-References/motion-presets.md` (zero-dependency, copy-ready CSS transitions keyed by interaction — modal/dropdown/toast/… — with `prefers-reduced-motion` baked in; the plain-CSS counterpart to `motion.csv`, re-derived from transitions.dev, no code copied), and a **Design dials** intake section (DESIGN_VARIANCE / MOTION_INTENSITY / VISUAL_DENSITY) added to `design-system-reference.md`. All static/advisory, no execution surface. *Why:* a reference tells you how to *choose* a look but doesn't *pin* one, so multi-build surfaces drift; a committed contract keeps every build on-brand and makes the look agent-operable, and the motion/dials references remove the two remaining hand-waves in the design flow.
- **Doc + web ingestion utilities — `/ingest`, `/webfetch`, `/docs`, `/skill-eval` (new capabilities).** `/ingest` converts rich documents (PDF/DOCX/PPTX/XLSX/.msg/EPUB) to clean Markdown **locally, zero API calls / egress** (Microsoft markitdown, plugins disabled). `/webfetch` fetches a URL as full clean Markdown through an own thin wrapper — **SSRF-guarded** (rejects localhost / private / loopback / link-local / reserved / CGNAT, including names that *resolve* to them, with per-redirect re-validation), honest User-Agent, no stealth/evasion tooling, output treated as untrusted. `/docs` resolves a package to its current official docs URL + version via the **public npm / PyPI registry JSON** (no third-party service, no key, no pre-crawled corpus) then fetches it. `/skill-eval` measures a skill's trigger accuracy + benefit before you ship it (proposes description tweaks, never auto-edits). Optional deps (`markitdown`, `requests`) live in a new `requirements-ingest.txt` extra — core install doesn't need them, and `/ingest` / `/webfetch` degrade with a clear install pointer when absent. Ships with an **opt-in** PreToolUse(Read) router (`route-binary-doc-read.py`) that is unwired by default (on the `STANDALONE_HOOKS` allowlist).

### Changed
- **`scripts/hooks/_verdict.py` gained an optional `enforce=` per-rule promotion override (existing capability).** Default `False` — every existing caller is unchanged. When `True`, a rule that has cleared its own shadow window fires at full strength even while the rest of its automation stays in monitor mode; the audit line records an `enforced` field. This is the mechanism `/harness-watch-review` promotion uses.
- **`.claude/rules/captures.md` now also covers `00-Inbox/_harness/**`** as a *machine-generated* (not authored) trust zone: harness-watch notes are observations to treat as data, never loaded as trusted planning input — mirroring the captured-content discipline.

Docs: README / CAPABILITIES / ROADMAP reconciled — deterministic checks 22 → **24**, command count → **45**, path-rule count 10 → **11** (consistency fix), self-* + utilities documented at their honest ceiling. Deterministic suite **24/24** green; gitleaks clean; `/secure-code-review` + `/owasp-agentic-review` over the new watch both **0 blocking**.

---

## [0.18.0] - 2026-07-15

### Added
- **Backlink authoring discipline — new notes earn a place in the graph instead of landing as orphans (new capability).** New path-conditioned rule `.claude/rules/backlink-discipline.md` fires when you author in any `NN-Name` vault folder (or use authoring keywords like "write a note" / "synthesis") and asks every *substantive* new note to carry **≥3 `[[backlinks]]` to existing notes, at least one of them into the oldest ~20% of the vault** — the "anti-recency link". *Why:* a second brain decays into a warehouse when new notes only link to this month's notes; forcing one link back across time resurfaces dormant thinking and keeps link-density climbing, which is the truest signal that the vault is alive rather than merely accumulating. The relative "oldest ~20%" threshold works at any vault age (three months or ten years) and auto-ages with no re-tuning. `/graph-backfill`'s `## Related` footer links count toward the ≥3, so the generative discipline and the reflection tool compose; `/vault-lint`'s orphan hunt is the audit backstop. Scope is a **denylist, not an allowlist** — any authored top-level folder is in scope the moment it is created (`00-Inbox/_captured/**`, templates, `09-Archive`, `.obsidian`, `CLAUDE.md` excluded), so the rule grows with the vault and needs no folder list to maintain. Provenance: adapted from a viral "self-writing vault" post (rule 5), stress-tested and reshaped (relative age threshold, denylist scope) before adoption.

### Changed
- **`scripts/load-rules.py` now recognises numbered folders past `09-`.** The path-extraction pattern was capped at `0\d-` (matched only `00-`–`09-`); broadened to `\d\d-` so a reference to a future `10-…` / `12-…` folder still triggers its path-conditioned rules. Strict superset — no existing match changes. This is what lets backlink-discipline's grows-with-the-vault scope actually fire on new numbered folders, and it benefits every path-rule.

Docs: README + ROADMAP path-conditioned-rule counts 10 → 11; CAPABILITIES rules table and the marketing site's skills page updated to match. Deterministic suite: 23/23 green.

---

## [0.17.0] - 2026-07-10

### Added
- **Failure-surfacing net for TODO.md — a stale front-of-mind list can no longer fail silently (new capability).** New SessionStart hook `scripts/hooks/check-todo-freshness.py` computes TODO staleness **live** from the `generated:` frontmatter date and, when stale, surfaces a banner at the top of the session — how many days behind, roughly how many captured items may be un-triaged, and (when known) the specific failure reason. Fresh TODO → completely silent. `scripts/hooks/on-error.py` now drops a `TODO-REGEN-FAILED.flag` (in the capture-pipeline `state/` dir) when a runner whose name mentions "todo" exits non-zero, so the banner can name the cause; the freshness hook self-cleans that flag once TODO regenerates. *Why:* a scheduled TODO-regeneration step can fail quietly (budget cap, wall-clock timeout, a hung headless run) and stop updating TODO.md with no signal — new captures then never reach your front-of-mind list. on-error's log + desktop toast are easy to miss; a session-start banner isn't. Freshness is computed live (not flag-dependent) so the net fires even if the failing process died before writing a flag. Bounded, fail-silent, and the (larger) un-triaged-capture scan runs only on the already-stale path so fresh mornings stay near-zero-cost. New deterministic check **D23** (suite now 23) verifies wiring + behaviour (stale→banner, fresh→silent). No new tools, egress, or write-paths beyond its own flag; captured content is counted by mtime only and never read into output.

---

## [0.16.1] - 2026-07-08

### Changed
- **`/devils-advocate` — three adversarial-council techniques folded in (existing capability improved).** Additive to the proven 3-vote survival math; nothing about the verify pass changed. (1) **Problem-restatement gate** — the frame step now judges whether the decision is well-enough framed to red-team; a genuinely misframed *and* costly-to-reverse decision returns early asking to be sharpened, instead of burning a full hostile fan-out on a fuzzy target (easily-reversible decisions proceed regardless). (2) **Counterweight steelman** — one defender voice runs concurrently with the hostile lenses, making the strongest honest case *for* the decision; it feeds the synthesis only (never the refuters, whose independence is load-bearing), so the verdict weighs the defense rather than being one-sidedly negative. (3) **Dissent-quota / false-consensus watch** — a load-bearing risk killed *unanimously* (3-0, no dissenting vote) is flagged for a sanity re-read and can be resurrected into the verdict, guarding against a monoculture of skeptics discarding a real risk. *Why:* borrowed from the `0xNyk/council-of-high-intelligence` pattern (evaluated, not vendored) — they close real gaps in a single-pass red-team without weakening the adversarial-verify core. The workflow now has a fourth return shape (`verdict: "needs_sharpening"`); a programmatic consumer must switch on `verdict` (documented inline).
- **`/prometheus` — cross-source dedupe + signal-ranked digest (existing capability improved).** New protocol step (5b): the same story often arrives via more than one input (a worked research thread, the newsletter email beat, the optional KEV shortlist). Prometheus now **merges duplicates into one item** — with a **Corroboration** line naming every input it surfaced across, instead of listing it two or three times — and **ranks the digest by signal** (research signal-strength: corroboration + actionability for the user's remit + velocity + beat priority) so the highest-signal item leads. *Why:* borrowed from the `mvanhorn/last30days-skill` scoring+dedupe idea (pattern only — its cookie-reading and multi-vendor egress were explicitly not taken). "Signal" here is research signal-strength, **not** social-engagement metrics: Prometheus reads no browser cookies and calls no engagement APIs. Prompt-only change — no new tools, egress, or write-paths; security posture unchanged.

---

## [0.16.0] - 2026-07-03

### Added
- **Design System Reference — a design-knowledge layer for building visual surfaces** (`07-References/design-system-reference.md` + `07-References/design-system-data/*.csv` + `.claude/rules/design.md`). When you build a dashboard, landing/marketing page, chart, or Claude Artifact, `load-rules.py` now auto-injects a design rule that carries an always-apply accessibility/UX floor (contrast ≥ 4.5:1, never colour-alone for meaning, visible focus rings, restrained motion, no layout shift) and a chart-selection rule of thumb, then points at the full interface. The interface distils a borrowed dataset into (a) a **universal UX Do/Don't checklist** grouped by area with severity, and (b) a **chart-selection quick-reference** that picks the chart by the question *and surfaces the accessibility grade* — several common chart types (pie, treemap, network, 3D) grade C–D and must ship a table fallback or not be the primary view. The reference feeds the `frontend-design` and `artifact-design` skills; it does not replace them. Data adapted from [ui-ux-pro-max-skill](https://github.com/nextlevelbuilder/ui-ux-pro-max-skill) v2.6.2 (MIT © 2024 Next Level Builder) — data only, no upstream code vendored or run; attribution in `NOTICE`. *Why:* the harness could research and write well but had no owned, always-loaded design floor, so visual builds leaned on model defaults with no accessibility guardrail.

---

## [0.15.3] - 2026-07-02

### Fixed
- **Capture concurrency lock in `fetch-mail.mjs`** — capture can be triggered from more than one place (a scheduled task, a login-catchup run, a manual invocation), and two runs writing the shared state file at the same time could race: one reads it mid-write by the other → a fatal JSON parse error (`Unterminated string in JSON` / `Expected double-quoted property name`) that aborts the loser. Added an exclusive lockfile (`state/fetch-mail.lock`, atomic `wx` create): a second concurrent run now yields gracefully (exit 0) instead of corrupting the shared capture state. A lock older than 30 min (a crashed/hung holder) is stolen; the lock is released on any exit path; `auth` and `--dry-run` take no lock. *Why:* observed intermittent capture crashes traced to overlapping runs writing the same state file.

---

## [0.15.2] - 2026-07-01

### Added
- **`/deep-research` fetch-fallback (opt-in, off by default)** — the Fetch/Verify/Re-research agents called `WebFetch` with no fallback, so a JavaScript-rendered SPA, paywall, or anti-bot wall returned an app-shell / empty body and a recoverable source was silently lost as `sourceQuality:"unreliable"`. Added the minimal form of an ordered-backend list: ONE fallback backend (Jina Reader `r.jina.ai`, reached through the *same* `WebFetch` tool — no new dependency, no new capability grant, no key) that server-renders a page a direct fetch dropped. Gated behind `const ENABLE_JINA = false`: **off by default so the harness stays 100% local** with no external service in the fetch path — when false, every fetch prompt is byte-for-byte the prior WebFetch-only behaviour. Set it true to opt into external source-recovery. The proxied content is still untrusted web data (the `<untrusted>` / trust-boundary handling is unchanged), and the fallback is used *only* when a direct fetch is inadequate, so the proxy only ever sees URLs that already failed. *Why:* research resilience — recover otherwise-lost sources — without weakening the local-first posture or the injection trust boundary.

---

## [0.15.1] - 2026-07-01

### Changed
- **README hero repositioned — category-led.** The opening now leads with a plain what-it-is line ("Charon is a second-brain harness for Claude Code — durable memory, confidence-tagged answers, and a security baseline built by a CISO") followed by concrete capability bullets, rather than a claim/pain-first tagline. *Why:* the recruitment doc's first ~10 seconds should let a skeptical reader self-identify via category + concrete capability, not an emotive hook. Grounded in a self-verifying research pass over how high-star dev-tool + security OSS repos (ripgrep, Trivy, Semgrep, Falco) and comparable governance tooling open their READMEs — they lead with category, keep pain below the fold, and avoid saturated tropes. Security wording kept honest to shipped posture ("documented, and enforced where they run"). The pain narrative remains in "Why you'd want this".

### Added
- **Pronunciation guide** under the title — *"KAIR-ən" (/ˈkɛərən/)*, the anglicised ferryman, with the Ancient Greek Χάρων *"KHAH-rawn"* (/ˈkʰarɔːn/) noted. Readers were unsure how to say it.

---

## [0.15.0] - 2026-07-01

### Added
- **Workflows — a new capability class (`.claude/workflows/*.js`)** — multi-agent orchestration scripts run by the Claude Code `Workflow` tool: they fan work out across many subagents, then converge, with control flow (loops, fan-out, verify gates) in code rather than model discretion. Discovered by the runtime at session start and invoked by name; `.claude/workflows/README.md` documents the class, discovery/invocation, and safety posture. *Why:* review skills and standing seats cover single-worker routines; genuinely hard questions and high-stakes decisions want a *harness* that decomposes, runs independent verifiers, and only keeps findings that survive challenge.
- **`/deep-research`** — self-verifying deep research: decompose → parallel web search → fetch + extract falsifiable claims → 3-vote adversarial verify with a re-queue-until-zero loop (evidence-handling rejects are re-researched against a live source) → cited synthesis. Borrows the loop-not-line self-verification pattern (independent refuters; majority-refute kills a claim).
- **`/devils-advocate`** — adversarial pre-mortem for hard-to-reverse **non-code** decisions. Fans out hostile lenses (Key Assumptions Check · Pre-Mortem · adapted-adversary · disappointed-counterparty · conditional Analysis of Competing Hypotheses), consolidates, 3-vote adversarially verifies every surfaced risk, and runs a **grounding gate** that tags each survivor grounded / plausible / invented (checking memory + the authored vault) — so an invented premise can't ride into the verdict dressed as a finding. Ends on a kill / proceed-with-fixes / proceed verdict. Draft-only; writes nothing. *Origin:* the Tradecraft Primer red-team techniques, with the adversarial-verify + grounding gate added to fix the "vivid but ungrounded" failure mode of a single-pass critique.
- **Deterministic check D22** — verifies every `.claude/workflows/*.js` declares `export const meta` with a `name` matching its filename, and that the expected workflows are present. Suite is now **22 deterministic checks**.

### Fixed
- **Personal-content scrub now covers `.js`** — D5's `text_extensions` omitted `.js`, so the new workflow class would have shipped un-scrubbed. Added `.js` to the scan set; both workflows verified clean.

---

## [0.14.1] - 2026-07-01

### Added
- **Full 00-09 base-folder skeleton at first-run** — `scaffold_vault_structure()` now creates the complete base skeleton in every install mode, including an empty `02-BUs/` org-unit layer and `03-Domains/` (previously `02-BUs` was never scaffolded and `03-Domains` was full-mode-only). Each folder ships with an explainer README; no org-specific content is generated. *Why:* a capability the user hasn't set up yet still has a home to grow into — captures, meetings, projects, or the org-unit layer can be adopted later with zero folder setup.
- **`first-run.py --scaffold-only`** — idempotent, non-interactive entrypoint that ensures the base skeleton under the configured vault root and exits. Useful standalone; also the hook the updater calls.
- **One-touch base folders on update** — after a `github-self` fast-forward pull, `/charon-update` runs the scaffold-ensure so **existing** users pick up any newly-added base folders automatically (best-effort; never fails the update). New commands/scripts/rules/docs already arrived one-touch via the pull; this closes the folder gap.
- **Deterministic check D21** — verifies `--scaffold-only` creates the nine base folders and is idempotent. Suite is now **21 deterministic checks**.

### Fixed
- Corrected stale first-run summary prose that told users to create `02-BUs/` themselves — it now scaffolds as an empty base folder with a README.

---

## [0.14.0] - 2026-07-01

### Added
- **Content-graph hygiene lint (`/vault-lint`)** — `scripts/vault-lint.py`, a deterministic, read-only worklist over the authored vault body. Two checks: **broken markdown file-links** across `01-Daily`/`02-BUs`/`03-Domains`/`04-People`/`05-Meetings`/`08-Projects` (06-/07- are `/score-vault`'s turf), and **tag-taxonomy drift** — frontmatter `tags:` linted against a faceted taxonomy. *Why:* classic PKM rots two ways — structural (dead links) and taxonomic (tag sprawl); this surfaces both as a worklist without touching prose. Complements `/score-vault` (which audits harness surfaces, not the knowledge body). No LLM call; exit 0 always (findings are a worklist, not a failure).
- **Faceted-tag migrator (`scripts/migrate-tags.py`)** — companion to `/vault-lint`: rewrites bare/legacy tags to the faceted form. Resolves via a static migration map, then folder-derived context for `unit`/`portfolio`/`domain` (validated against the taxonomy's closed lists — underivable values are left alone, never guessed). Batchable (`--batch <facet>`), **dry-run by default**, `--apply` to write; only touches authored dirs, never captured content.
- **User-owned tag taxonomy (`07-References/tag-taxonomy.md`)** — ships as a template with the faceting schema + illustrative values. The engine hardcodes no facet or value; it reads whatever you declare. Closed facets (`type`/`unit`/`portfolio`/`domain`) are auto-seedable from your first-run org-unit list; open facets (`topic`/`vendor`) accept any kebab value. *Why:* the structure is generic, the vocabulary is yours (per "rules teach structure, the user supplies content").
- **`/brainstorm`** — structured divergent→convergent idea generation for non-code work (frame → diverge 5–8 → converge → evaluate → recommend). Inline-first; writes nothing without a yes. Pattern borrowed from obra/superpowers (inspiration, not vendored).
- **`/systematic-debug`** — hypothesis→test→eliminate debugging (pin the symptom → ranked hypotheses → one variable at a time → confirm by reproduction → minimal fix → verify). Pattern borrowed from obra/superpowers (inspiration, not vendored).
- **Deterministic check D20** — runs `/vault-lint` + the migrator against the shipped taxonomy template (lint executes, taxonomy parses, migrator dry-runs clean), so the new capability is release-gated. Suite is now **20 deterministic checks**.

### Fixed
- **Latent D2 hook-wiring failure** — `_poisoning.py` (the injection-detector module imported by `poisoning-scan.py`, added in v0.12.0) was neither wired in `settings.json` nor on the `STANDALONE_HOOKS` allowlist, so the hook-wiring check had been failing since v0.12.0. Added it to the allowlist alongside the other imported-module hooks (`_verdict.py`, `_telemetry.py`, `_jsonl_append.py`). *Why it matters:* the release gate is only meaningful when it's green for the right reasons — a stale FAIL trains you to ignore it.

---

## [0.13.0] - 2026-06-30

### Added
- **KEV/CVE triage beat** — `scripts/kev-fetch.py`, an optional Prometheus pre-step. Fetches the CISA Known-Exploited-Vulnerabilities catalogue and writes a prioritised shortlist to `00-Inbox/_research/` for the digest's bulletin-worthy line. *Why:* actively-exploited vulnerabilities in widely-run software are the ones worth a heads-up, and trawling feeds by hand doesn't scale — this surfaces them ranked, so a research seat can flag "worth a bulletin?" without the manual sift. Scores on KEV-available signals only — **recency × ransomware-campaign flag × due-date urgency × a broadly-deployed-vendor lens** (no CVSS; KEV carries none — CVSS enrichment would need NVD, deferred by design). The vendor lens ships with a sensible default and is tunable with `--vendors <file>` to match the software you or your customers run. Dependency-free stdlib; one documented outbound GET to cisa.gov; writes only to `_research/`; sanitises external fields before embedding them. Pattern borrowed from hoodinformatik/OpenThreat (AGPL **not** vendored — reimplemented native). Layer 1 = digest-only; bulletin drafting (Layer 2) stays human-gated. Unattended/scheduled runs gated behind `/owasp-agentic-review` + `/secure-code-review` + a shadow window.

---

## [0.12.0] - 2026-06-29

### Added
- **Prompt-injection / poisoning detection** — `scripts/hooks/_poisoning.py` (dependency-free detector) + `poisoning-scan.py` (UserPromptSubmit wiring). Flags instruction-shaped attacks the secret scanners miss: instruction-override, role-switch, exfiltration, tool-coax, secret-solicitation, hidden/encoded payloads, model **special-token injection**, and **confusable-evasion**. Three evasion-hardening passes baked in — Unicode confusable + invisible folding on a detection-only copy (a Cyrillic-homoglyph "ignore previous instructions" can't slip past ASCII patterns), chat-template special-token detection (ChatML / Llama / Mistral / Gemma), and base64/hex **decode-then-rescan** (catches payloads hidden below the long-blob heuristic). **Ships in shadow (observe-only): logs a verdict to `state/verdict/`, never blocks or alters the prompt.** Privacy: logs categories + score only, never the matched text. Patterns borrowed from microsoft/agent-governance-toolkit and sharma-open-source/opensentry (both MIT), reimplemented native. `python scripts/hooks/_poisoning.py --selftest` covers 13 cases.

---

## [0.11.0] - 2026-06-26

### Added — Graph link-backfill (`/graph-backfill`): write the derived graph back into your notes

Charon builds a rich derived knowledge graph (`extract_entities.py`) and can browse it (`vault-graph` MCP, the HTML viewer, `/vault-query`) — but Obsidian's own graph view only ever drew the `[[wikilinks]]` physically present in note bodies, which authored notes rarely have. The two graphs never converged: the web existed, but you couldn't see it in Obsidian.

- **New capability `scripts/graph_link_backfill.py` + `/graph-backfill` command.** For each note, it appends a marker-delimited `## Related` footer of `[[wikilinks]]` to the entities that note connects to in the derived graph. Now the final stage of the graph-build sequence: `extract_entities → cluster_vault → vault_graph_html → graph_link_backfill`, so a freshly built/refreshed graph leaves the notes link-rich out of the box.
- **Footer-only and idempotent.** Prose is never touched — only the block between `<!-- graph-backfill:start/end -->`. Re-runs replace the block (verified idempotent); a note whose edges are gone has its stale block removed.
- **Generic scope, no folder taxonomy assumed.** Every note with edges is in scope, except untrusted captured content (frontmatter `trust: untrusted`), templates, dotfile dirs, and any `CLAUDE.md`. Capture exclusion keys off the `trust` marker (content, not path) so it works on any vault shape.
- **Two quality guards baked in:** drops file-artifact targets (`*.py`, `*.json`, path-like names) that pollute the graph as faded nodes (`--keep-fileish` to override), and merges duplicate `source_file` keys that resolve to the same physical note (case variants on case-insensitive filesystems, stale paths from a note moving folder) so the richer link set wins instead of being clobbered.
- **Dry-run by default;** `--apply` writes. *Why it matters:* the graph's value was locked inside an MCP/HTML surface most users won't open daily — backfilling into the notes surfaces it in the tool they already live in, and "from install" means it's wired into the standard graph build rather than a thing you have to discover.

### Changed — Knowledge-graph backend: embedded graph DB → networkx (pure-Python)

The knowledge graph previously stored data in an embedded graph database (kuzu). That package ships **no wheel for newer Python versions** — on Python 3.14 it can't install at all, which silently disabled the *entire* graph capability (extraction, MCP, HTML viewer, `/vault-query`, and the new backfill) for any user on a current interpreter.

- **`scripts/lib/graph.py` is now networkx-backed**, persisting the graph as plain JSON at `.charon/knowledge-graph.json`. networkx is pure-Python (MIT) with no compiled extensions, so the graph installs and runs on any platform / Python version. networkx was already a dependency (it powered clustering + traversal), so this *removes* a dependency rather than adding one.
- **All consumers migrated off raw Cypher** to the shared graph API: `extract_entities.py` (writes, now persists via `conn.save()`), `vault_query.py`, `lib/communities.py`, `vault_graph_html.py`, `graph_link_backfill.py`, and the `vault-graph` MCP server.
- **The MCP server is now read-only by construction.** The free-form `query_graph` Cypher passthrough is removed (no query engine under networkx); `get_entity` + `stats` now open the graph through a frozen, `.save()`-raising read-only connection, so no mutation surface is exposed via MCP at all.
- *Why it matters:* the graph stack was non-functional on Python 3.14 and carried a native dependency that had to be sourced per platform. It is now verified working end-to-end (build → cluster → HTML → query → backfill) on Python 3.14 with a single pure-Python dependency, and the 19/19 deterministic checks still pass.

### Security — Hardened the no-personal-content scrub (D5)

A pre-release sweep found the D5 personal-content scrub had two blind spots that let author/organisation references slip into shipped files: it matched the author's *full* name but not the bare first name in prose, and several patterns were case-sensitive (so "Vela" slipped past a lowercase `vela` rule).

- **Added a bare author-first-name pattern**, allowlisted to the copyright/attribution files and the immutable CHANGELOG.
- **Matching is now case-insensitive**, with the genuinely ambiguous common-word patterns (portfolio names, EDR-vendor name) pinned case-sensitive via `(?-i:…)` so they don't false-positive on legitimate security signatures or English prose.
- Caught and removed real prose leaks across six files in the process. *Why it matters:* the scrub is the automated gate that keeps author/organisation specifics out of a public repo; the blind spots meant it could pass while leaks shipped.

---

## [0.10.2] - 2026-06-11

### Fixed — Documentation accuracy sweep + scaffold the framework-reference folder

An end-to-end review found the docs had drifted from ground truth on several counts, and a second dangling-folder reference (same class as the v0.10.1 baseline-doc gap). The harness itself is healthy — 19/19 deterministic checks pass, all Python compiles, all configs valid; these were documentation/scaffolding fixes, not code fixes.

- **Counts corrected to verified ground truth** across README / ROADMAP / CAPABILITIES / FIRST-RUN / INSTALL / the results template:
  - First-run wizard: **39 questions** across 5 phases (~25 always-asked + conditional), not 27. Quick path is **4–6 questions** (3 identity + email-capture y/n, +2 M365 credential questions if capture is enabled), not 3 — the 2026-06 Quick-mode capture extension was never reflected in the docs.
  - **Path-conditioned rules: 9** (added `verdict-vocabulary`, `versioning`), not 7.
  - **Hooks: 10** wired across lifecycle events (the list now correctly includes `voice-anchor-ralph-loop` + `check-reauth-flag` and notes `on-error` as runner-invoked), not 9 with a stale membership list.
  - **Test suite: 16 LLM scenarios + 19 deterministic checks**, not 10 + 7.
  - *Why it matters:* the docs are part of the product surface. Stale counts erode trust and hide capabilities a user would otherwise adopt; an undercounted wizard ("3 questions") also misleads on setup effort.
- **`07-References/frameworks/README.md` scaffolded.** `/control-translate`'s framework mode reads `07-References/frameworks/` (described as "central, not optional"), but the folder didn't ship and wasn't seeded — a dead reference. It now ships with a README explaining what goes there (curated framework reference material — user-supplied, since framework content is licence/org-specific), consistent with "rules teach structure, the user supplies content."
  - *Why it matters:* framework-mode `/control-translate` had nothing to read out of the box; the folder + guidance make the dependency real and tell the user how to populate it.

---

## [0.10.1] - 2026-06-11

### Fixed — Ship the C-1..C-8 security-baseline reference doc (was a dangling cross-reference)

The security-baseline framework was advertised as shipping (README, and inline in the review skills), but its canonical reference doc — `07-References/security-baselines.md` — was never actually in the repo. 24 files pointed at it: `fp-check`, `secure-code-review`, `owasp-llm-review`, `owasp-agentic-review`, the `secure-code` + `skill-authoring` rules, the OWASP reviewer agents, and now `safe-rebuild`. A user following any of those cross-references hit a dead link.

- **`07-References/security-baselines.md`** now ships — the full C-1..C-9 control set (hardened prompts, tool minimisation, write-path validation, budget caps, post-run audit, hook-side LLM hygiene, captured-content discipline, egress controls, human-in-loop approval) plus the sub-rules and a **§Exemptions register**.
  - *Why it matters:* this is the doc every security skill treats as the authority for "what secure means". In particular, `/fp-check`'s exemption logic ("WITHDRAW citing exemption ID") had nothing to read — the register now exists, so that path works. Remediation (`/safe-rebuild`) and review (`/secure-code-review`) now rebuild/check against a real, present baseline rather than a phantom one.
  - *Genericised:* org-specific calibrations, personnel, and a fixed compliance table were stripped; the compliance table is now a **template the user populates** (rules teach structure, the user supplies content), and the §Exemptions register ships with the universal exemptions + room for the user's own.

---

## [0.10.0] - 2026-06-11

### Added — `/safe-rebuild`: finding-driven safe remediation

A new capability that closes the loop the security reviewers leave open. Until now `/cerberus-vet` and the OWASP review skills could **detect** risk in a skill/agent/hook/command/MCP artifact and report it — but fixing it was ad-hoc, with no structure, no re-verify, and a real chance of breaking the artifact's function or losing the audit trail.

- **`/safe-rebuild <artifact> [+ findings]`** (`.claude/commands/safe-rebuild.md`).
  - *Capability:* takes a flagged artifact through a disciplined **re-spec → rebuild → re-verify** loop. Inception runs a silent analysis, gates the input findings through `/fp-check` (so you never rebuild against a false positive), writes a stored re-spec report, and blocks on your confirm. Construction rebuilds in a `.safe-rebuild/` scratch dir against the C-1..C-8 baseline + skill-authoring standard — the original is untouched until the gate passes. A **blocking verification gate** re-runs the reviewers + `/fp-check`; the artifact can't be marked done until every original finding is cleared and no new 🔴 is introduced. The swap-in happens only after the gate is green AND you confirm; the original is archived (reversible).
  - *Intent:* turn "Cerberus found a problem" into a structured fix you can trust, without silently rewriting a skill, weakening a control to pass, or breaking what the skill was for. The agent proposes; you approve.
  - *Why it matters:* detection without disciplined remediation is half a control. An ad-hoc fix can introduce a worse finding than the one it closed, or quietly reduce capability to make a checker happy. A gated loop with human-confirmed swap-in and a preserved audit trail makes remediation as rigorous as detection. `/fp-check` gating *both* the input and the output means effort is never spent on phantom findings, and a "clean" rebuild is actually verified. Tool surface is minimal by design — `Read/Write/Edit/Glob/Grep/Skill`, no `Bash` (all writes route through `validate-write-path.py`).
  - *Provenance:* the phase-spine + blocking-gate pattern is borrowed from AIDLC (`awslabs/aidlc-workflows`, MIT-0) and reimplemented natively — none of AIDLC's tooling is installed. The greenfield counterpart `/build-safely` is a planned follow-on.

---

## [0.9.1] - 2026-06-10

### Changed — Documentation freshness + a patch-notes standard

A documentation-hygiene patch: brings every doc current with the v0.9.0 pipeline, and encodes a standard so the docs (including this changelog) stay fresh on every future change.

- **New-agent capability + intent docs.** `.claude/agents/README.md`, `CAPABILITIES.md`, and `README.md` now document the two standing seats (Prometheus, Calliope) with capability *and* intent, as a category distinct from the review subagents; the persona anti-pattern is clarified (functional seats are fine — roleplaying *your* identity is not). *Why it matters:* a reader couldn't tell what the new agents were for, or how they differ from the parallel review subagents — now the docs say so plainly.
- **Counts reconciled to ground truth.** Command (→34), agent (→7), and wizard (→5 phases / 27 questions) figures were stale across README / CAPABILITIES / ROADMAP / INSTALL / FIRST-RUN / the wizard's own help text. All corrected. *Why it matters:* stale counts erode trust in the docs and hide capabilities a user would otherwise discover and adopt.
- **Patch-notes content standard** (`.claude/rules/versioning.md`). Every CHANGELOG entry must now cover **capability + intent + why-it-matters**, and docs update in the *same change* as the capability they describe. *Why it matters:* a terse "added X" tells a reader nothing about value or purpose — this keeps the changelog a real part of the documentation surface, not an afterthought. (This entry follows the standard it introduces.)
- **FIRST-RUN `engines` phase documented.** The new research-beats / newsletter-senders / forums seeding questions now appear in the wizard walkthrough + the `--phase engines` refinement path.

---

## [0.9.0] - 2026-06-10

### Added — Research → compose pipeline (Prometheus, Calliope) + forum feed

A new capability tier: a **research → compose → deliver** pipeline of standing agent "seats". Until now the harness remembered and reviewed, but you still drove research and drafting by hand. These seats carry that work across sessions — surfacing what matters, then drafting it in your voice — while keeping every outward action human-gated.

- **Prometheus — the research seat** (`.claude/agents/prometheus.md` + `/prometheus`).
  - *Capability:* a standing research analyst. Keeps a persistent ledger (`00-Inbox/_research/_ledger.md`) of your standing beats, scans an allowlist of newsletter/digest senders from captured email as an input beat (matched on `sender:` frontmatter only; untrusted-data discipline), researches the top-K active threads, and writes a prioritised daily digest with framed content angles. Read + write-note only — writes solely to `00-Inbox/_research/`.
  - *Intent:* triage and surface so you stop sifting raw research and stop losing threads between days. You steer (ledger steer column); it never self-promotes or acts.
  - *Why it matters:* research that isn't captured and prioritised gets re-done or missed. A standing analyst with cross-day memory turns scattered reading into a daily "so what" you can act on.
- **Calliope — the writing seat** (`.claude/agents/calliope.md` + `/calliope`).
  - *Capability:* composes outbound writing **in your voice** across modes — `post` (delegates to the tuned `/draft-linkedin`), `bulletin` (stakeholder advisory + a co-located responses tracker), `tweet`, `email`. Loads the `voice-content` rule + your voice profile first. **Drafts only — never sends, posts, or emails;** bulletins are draft-to-approval.
  - *Intent:* turn a researched angle or raw topic into a draft that sounds like you, not a generic LLM, without ever taking the outward action for you.
  - *Why it matters:* drafting is the bottleneck, and an AI that can *send* is a liability. A voice-faithful writer with a hard human-gated send gives you the speed without the blast-radius risk.
- **Forum feed** (`/forum-agenda`).
  - *Capability:* scans captured email / chat / meetings / sessions over a window for signal relevant to a user-defined forum remit (`reference_forums.md`) and surfaces candidate agenda items. Read-and-surface only — never writes the live agenda.
  - *Intent:* let a recurring forum be driven by what actually happened since it last met, not just what you remember on the day.
  - *Why it matters:* the most consequential agenda items are the ones that slipped your mind. Mining a month of your own signal catches them while the decision still has time to land.
- **First-run `engines` phase** — three new questions (standing research beats, newsletter sender allowlist, recurring forums) seed the research ledger and `reference_forums.md`.
  - *Why it matters:* an empty engine is useless on day one. Seeding beats + senders + forums at setup means a new user's Prometheus and forum feed produce value on first run, not after weeks of manual configuration.

---

## [0.8.1] - 2026-06-09

### Security — Cerberus hardening (ported from the vault security-update 2026-06-08)

A PATCH-level security update: no new user-facing capability, sharper detection and two new audit checks against threats seen in the wild in June 2026.

- **`scripts/hooks/cerberus/secret-pattern-scan.py`** — scope-aware scanning. Path-patterns no longer scan Write *content*, so documentation that merely *describes* a secret path is no longer false-blocked; value-patterns (keys / tokens / PEM / JWT) are still flagged wherever they appear. Adds an override hatch and self-exemption. Now wired directly as a PreToolUse hook.
- **`.claude/skills/audit-claude-setup/SKILL.md`** — two new threat checks:
  - *Step 3 — lifecycle-hook injection:* enumerate ALL hook events (incl. `SessionStart` / `UserPromptSubmit` / `SessionEnd` / `PreCompact`) and flag any project-level hook running an interpreter against a project-local script — a self-propagating-worm persistence vector that survives `npm uninstall`. Also checks `.vscode/tasks.json` `folderOpen` and `.cursor/`.
  - *Step 5 — client-redirection / MitM:* flag a non-default `ANTHROPIC_BASE_URL` (can leak the `Authorization: Bearer` key), MCP server endpoints rewritten to `localhost`/`127.0.0.1` (token-harvest MitM), and `~/.claude.json` (plaintext OAuth tokens at rest) living inside a git tree or cloud-synced folder.
- **`.claude/agents/cerberus.md`** — matching threat-model additions.
- **`07-References/dependency-pinning-discipline.md`** — June Miasma / Red Hat supply-chain wave + successor waves (CVE-2026-45321).
- Deterministic suite **19/19 PASS**.

---

## [0.8.0] - 2026-06-07

### Added — Vault graph improvements (the graphify-derived borrows)

`/cerberus-vet` shipped in v0.7.0 made Cerberus query-rule-driven. v0.8.0 does the same kind of step-up for the **vault knowledge graph** — five operations borrowed from the [safishamsi/graphify](https://github.com/safishamsi/graphify) evaluation (`reference_graphify.md`, cerberus-vet MEDIUM/78). Don't vendor the package per `feedback_charon_dep_aversion`; the patterns get re-implemented natively against Charon's existing Kuzu-backed graph.

**Five new capabilities, all stacked on the existing graph layer:**

1. **Louvain community detection** — `scripts/lib/communities.py` + `scripts/cluster_vault.py`. Reads the Kuzu graph, builds an in-memory networkx graph, runs Louvain, writes node→community labels to `<vault>/.charon/graph-communities.json`. Surfaces non-obvious clusters across people / projects / domains / BUs — themes that no manual tag captures.
2. **Interactive HTML graph viewer** — `scripts/vault_graph_html.py`. Single self-contained `<vault>/.charon/graph.html` you open in any browser. Nodes coloured by community, sized for visibility, filterable by entity type / community / name search. Click a node → side panel with its connections + click-through navigation. Vis-network loaded from CDN at view time (first open needs internet; offline-vendor noted as future work).
3. **`/vault-query` — natural-language graph queries** — `scripts/vault_query.py` + `.claude/skills/vault-query/SKILL.md` + `.claude/commands/vault-query.md`. Four subcommands: `search`, `explain`, `neighbours` (BFS/DFS), `path` (shortest path). The skill parses plain-English questions into the right subcommand + entity-name arguments. Read-only — never modifies the graph.
4. **Community-based wiki generation** — `scripts/vault_wiki.py`. For each detected community, writes a summary markdown doc to `07-References/communities/community-NN.md`. Anthropic Haiku writes the theme paragraph; a structural placeholder is used when the key isn't configured. Idempotent — each doc carries a `community_signature` hash so re-runs skip unchanged communities. Cost: ~$0.01–0.05 per community.
5. **Multimodal corpus extraction** — `scripts/extract_pdf.py` (pypdf) + `scripts/extract_audio.py` (faster-whisper, Python 3.11+). Each writes a sibling `.txt` so PDFs / audio recordings join the searchable + graph-extractable corpus instead of sitting as opaque files. Gated behind the new `requirements-multimodal.txt` opt-in.

**Architecture: dep-averse where the engineering was tractable, network-x where it wasn't.**

| Capability | Approach | Why |
|---|---|---|
| Louvain detection | `networkx` (added to `requirements-graph.txt`) | Hand-rolled Louvain is ~100 LOC of math + edge cases. networkx ships well-tested Louvain in pure Python. Pairs with kuzu at the same opt-in tier. |
| HTML viewer | Pure Python HTML generation, vis-network via CDN | No Jinja, no templating dep. Vis-network is a JS browser dep, not a Python dep — different layer. |
| Natural-language query | Pure Python (networkx for traversal) | BFS/DFS via networkx; NL parsing happens in the SKILL.md, not in Python. |
| Wiki generation | Anthropic (already a base dep) | LLM call already in the harness. New behaviour, no new dep. |
| PDF / audio extraction | `pypdf` + `faster-whisper` via opt-in `requirements-multimodal.txt` | Heavy domain-specific libraries. Hand-rolling PDF parsing or local speech-to-text is firmly out of dep-aversion scope. |

**New deterministic checks D15–D19** verify each chunk against synthetic inputs (no kuzu / no LLM / no real fixtures needed): community detection on networkx's Karate Club graph, HTML rendering structure, query traversal, wiki doc rendering + signature hashing, multimodal-extractor availability + help-text. Suite is now **19 PASS / 0 WARN / 0 FAIL**.

**New behavioural scenario `test-scenarios/16-vault-graph-pipeline.md`** chains cluster → HTML viewer → `/vault-query` for an end-to-end test of the user-facing flow.

**`CONFIGURATION.md`** gains a "Vault graph operations (v0.8.0+)" section documenting all five operations with their CLI, output paths, and recommended cadence.

### Why this is a MINOR and not a PATCH

Five new operations the harness can perform that it could not before v0.8.0:

- *"now I can run community detection over my vault graph and see the clusters"*
- *"now I can browse the graph visually in a browser"*
- *"now I can ask my vault natural-language graph questions"*
- *"now my vault auto-generates per-community summary docs"*
- *"now PDFs and audio recordings can join my searchable corpus"*

Each is a new capability surface. The collective lifts the vault graph from a passive store (queryable but not browsable, not summarised, not auto-clustered) into an active synthesis layer. **MINOR → v0.8.0.**

### Roadmap reset

The v0.8.0 roadmap mentioned in the v0.7.0 entry is now shipped. Future releases land in `[Unreleased]` until the next tag.

---

## [0.7.1] - 2026-06-07

### Changed — Smarter `/charon-update` + user-facing maintenance docs

User-facing refinement of the v0.7.0 update mechanism. `/charon-update` now distinguishes three kinds of update at the report layer, and there's a documented process for users to keep their harness current.

**`/charon-update` output now classifies updates:**

| Output | Meaning |
|---|---|
| `🆙 NEW RELEASE available — v0.7.0 → v0.8.0` | **Capability update**. Upstream tagged a new release. Brings new commands / engine layers / docs. |
| `⏫ N unreleased commit(s) past v0.7.0 on upstream/main` | **In-flight fixes**. Commits past the latest tag — bug fixes, small refinements. |
| `⏫ rule updates available` (pinned vs upstream SHA) | **Detection-rule refresh** for the vendored Cisco corpus. New / updated YARA, signatures, policies. |
| `✅ up to date — currently on v0.7.0` | Source is at the latest. |

How it works: `_get_local_nearest_tag()` runs `git describe --tags --abbrev=0 --match 'v*.*.*'` to find the nearest semver tag reachable from local HEAD; `_get_latest_remote_release_tag()` does `git ls-remote --tags origin`, filters to strict `vX.Y.Z`, semver-sorts, picks the highest. If those tags differ AND there are upstream commits, the update is classified as **capability**; if same tag but commits past it, **in-flight**. The script doesn't require GitHub Releases (the UI-level Release object) — works on annotated tags alone.

**New `CONFIGURATION.md` § "Updating — keeping Charon current"** — rewrites the existing tiny "Updating" section with a process-oriented guide:

- ONE-command path: `/charon-update` (in Claude Code) or `python -m scripts.update.charon_update` (shell)
- Three-cadence recommendation: **weekly** for rule updates, **monthly (or on notification)** for capability releases, **after any apply** the smoke test runs automatically — review the diff before committing
- Explicit "does NOT do" list — no auto-commit, no auto-push, no auto-manifest-edit
- Manual fallback (`git pull --ff-only`) for when the API is unreachable
- How to add a new updateable source (manifest YAML entry, no code change)

**SKILL.md updated** in `.claude/skills/update-charon/SKILL.md` — the `github-self` row in the source-type table now describes the capability-vs-in-flight classification; the `github-vendored` row names the result as a "detection-rule refresh".

### Why this is a PATCH and not a MINOR

The `/charon-update` capability existed in v0.7.0. v0.7.1 refines the output classification and adds user-facing documentation. Same capability, sharper UX. Authoring test (*"could a user describe this as 'now I can do X' where X is new?"*) → no: they're still updating, just with clearer reporting and a documented cadence. PATCH.

---

## [0.7.0] - 2026-06-07

### Added — Cerberus rule-pack-driven detection (the big swing)

`/cerberus-vet` now runs a layered detection engine over the cloned sandbox alongside the narrative V0–V8 analysis. **402 detection rules** active out of the box, all loaded from a vendored upstream rule corpus that ships with Charon and that the user can update on demand with a single command. Zero new PyPI runtime deps — the engine, the YARA interpreter, the file-type detector, the homoglyph checker, and the SARIF writer are all Charon-native MIT code. The rule corpus is Apache-2.0 vendored content from [cisco-ai-defense/skill-scanner](https://github.com/cisco-ai-defense/skill-scanner) (cerberus-vet MEDIUM/95).

**What's now possible:**

```bash
# Run the engine over any directory and emit text / JSON / SARIF
python -m scripts.cerberus.scan ./suspicious-skill --format sarif --out scan.sarif

# Update Charon + the vendored rule corpus + any other registered source
/charon-update          # interactive
python -m scripts.update.charon_update --check   # CI-friendly check-only

# Run the engine smoke test (14 checks, asserts the corpus loads cleanly)
python -m cerberus.engine.smoke_test
```

**Detection layers (each Charon-native, no PyPI dep):**

| Layer | Rules | Source |
|---|---|---|
| Signature engine — YAML pattern rules (`cerberus/engine/signatures.py`) | 384 | Vendored Cisco corpus (ATR 313 + core 45 + promptguard 26) |
| YARA-lite interpreter — pure Python (`cerberus/engine/yara_lite.py`) | 16 | Vendored Cisco corpus (1 file skipped — hex alternation outside subset) |
| Magic-byte file-type check (`cerberus/engine/file_type.py`) | 1 | Charon-native rule: `FILE_MAGIC_MISMATCH` (in the `charon` pack) |
| Unicode homoglyph check (`cerberus/engine/homoglyph.py`) | 1 | Charon-native rule: `HOMOGLYPH_DETECTED` (in the `charon` pack) |
| **Total live rules** | **402** | Signature 384 + YARA 16 + Charon-native 2 |

**Output formats:** human-readable text, Cerberus-native JSON, **SARIF 2.1.0** (GitHub Code Scanning + SonarQube + any SARIF-aware ASOC platform).

**Update mechanism — `/charon-update`:** single-entry-point command that checks every updateable source declared in `scripts/update/sources.yaml` (the Charon harness itself + any vendored corpus) and applies available updates with smoke verification. Manifest-driven — adding a new updateable source is a YAML entry, not a code change. Two source types in v0.7.0: `github-self` (compares HEAD vs origin/branch, offers `git pull --ff-only` if working tree clean + local is strict ancestor) and `github-vendored` (reads pinned SHA, clones shallow at upstream HEAD, copies configured paths, re-pins SHAs, runs post-update smoke). Idempotent. Does NOT auto-commit — user reviews `git diff` and commits manually.

**Chunk-by-chunk build trail:**

1. **Chunks 1+2 — Apache-2.0 attribution scaffolding + vendor of the cisco-ai-defense/skill-scanner rule corpus** (66 files: signatures, YARA, policies, prompt templates) into `cerberus/rules/`. `LICENSE-cisco-apache-2.0` + `NOTICE` + `.gitleaksignore` set up the licence boundary. Vendor-only — no runtime behaviour change.
2. **Chunk 3 — YAML signature matcher engine.** `cerberus/engine/{__init__,models,signatures,smoke_test}.py` loads 384 signature rules from the vendored corpus (1 rule gracefully skipped due to uncompilable backreference). Engine handles both top-level YAML shapes (bare list + `{signatures: [...]}` ATR wrap), translates PCRE-style `\u{HEX}` Unicode escapes to Python `re` syntax, and supports an exclude-pattern false-positive suppression layer.
3. **Chunk 4 — YARA-lite interpreter in pure Python (no `yara-x` dep).** Per `feedback_charon_dep_aversion`, the proposed PyPI dep was wrong-shape — 13/14 YARA files were just regex + boolean conditions, and the binary-detection file is ~30 LOC of header reading. `cerberus/engine/yara_lite.py` (~470 LOC) = tokenizer + recursive-descent parser + AST + condition evaluator. Supports literal/regex/hex string patterns, `and`/`or`/`not`, parens, `$name at N`, `@name OP N`, bare `@` in for-loop bodies, `for any of ($prefix_*) : (expr)`, comments. Out-of-scope features (hex wildcards `??`, hex jumps `[N-M]`, imports, `filesize`, `uintN`, hex alternation `|`) trigger graceful skip-with-warning. 16 YARA rules now live.
4. **Chunk 4b — `/charon-update` command — single-entry-point update mechanism.** Manifest-driven via `scripts/update/sources.yaml`. New `feedback_charon_ease_of_use` memory rule captured: ONE entry point for users, not one command per source. Designed for future Charon users who don't have the prototype-author's context.
5. **Chunk 5 — Magic-byte file-type detection in pure Python (no `magika` dep).** `cerberus/engine/file_type.py` (~180 LOC) covers ~30 common file types via signature matching. New Charon-authored rule `FILE_MAGIC_MISMATCH` lives in the new `charon` pack.
6. **Chunk 6 — Unicode homoglyph detection in pure Python (no `confusable-homoglyphs` dep).** `cerberus/engine/homoglyph.py` (~150 LOC) confusables table covering Cyrillic, Greek, Armenian, Latin-Extended, and Fullwidth attack chars. Strategy: fire only on words that MIX ASCII Latin with confusables from another script — pure-script words stay silent. Finding includes the canonical Latin form (e.g. `pаypal` with Cyrillic а → `paypal`) so a reviewer sees the typosquat target. New Charon-authored rule `HOMOGLYPH_DETECTED`.
7. **Chunk 7 — SARIF 2.1.0 output format.** `cerberus/engine/sarif.py` (~140 LOC) converts Cerberus findings into OASIS SARIF 2.1.0. Severity mapping: CRITICAL/HIGH → `error`, MEDIUM → `warning`, LOW/INFO → `note`. Rule definitions deduped under `tool.driver.rules`; results reference by `ruleId` + `ruleIndex`. Supports `originalUriBaseIds` (SRCROOT) so consumers resolve scan-target-relative paths.
8. **Chunk 8 — Engine wired into `vet-external-skill`.** New driver `scripts/cerberus/scan.py` (~200 LOC) runs all four engine layers against a target and outputs text / JSON / SARIF. The `vet-external-skill` SKILL.md gets a new "Step — Rule-pack engine scan (v0.7.0+)" section with an explicit rule-ID → V-layer mapping table. Engine corroborates the narrative verdict; doesn't replace it (validation_status stays `theoretical`).
9. **Chunk 9 — Test scenarios + deterministic checks.** New behavioural scenario `test-scenarios/15-cerberus-engine-end-to-end.md` exercises the engine through the assistant. Three new deterministic checks added: D12 (engine smoke), D13 (scan text format), D14 (SARIF output validates). Deterministic suite now: 14 PASS, 0 WARN, 0 FAIL.
10. **Chunk 10 — Release.** This entry.

**Two memory rules captured during the build that shape future Charon work:**

- **`feedback_charon_dep_aversion`** — default to in-house implementations over PyPI deps for the harness itself, even at 2-3× LOC cost. Existing base deps grandfathered; new ones must clear the bar. Provenance: chunk 4 (yara-x → yara_lite.py).
- **`feedback_charon_ease_of_use`** — Charon user-facing commands honour the ease-of-use principle: ONE entry point per user intent, sensible defaults, generalise from day one when the abstraction matches user mental model. Provenance: chunk 4b (single update command across all sources).

Together: **dep-averse inside, ease-of-use outside.**

### Why this is a MINOR and not a PATCH

`/cerberus-vet` previously did narrative V0–V8 analysis only. After v0.7.0 it ALSO runs 402 detection rules across four engine layers and can emit SARIF for CI integration. Authoring test (*"could a user describe this as 'now I can do X' where X is new?"*) — yes, multiply:

- *"now I can run Cisco-class signature + YARA + magic-byte + homoglyph detection against any third-party skill from inside Cerberus"*
- *"now I can emit SARIF output that GitHub Code Scanning / SonarQube / any SARIF-aware tool can consume"*
- *"now I can update the entire Charon harness and all its vendored content with one command"*

New capability surface. MINOR → **v0.7.0**.

### Roadmap — v0.8.0 (planned)

Vault graph improvements borrowed from the `safishamsi/graphify` evaluation (`reference_graphify.md`, cerberus-vet MEDIUM/78). Don't vendor the package per `feedback_charon_dep_aversion`; borrow patterns into Charon's existing Kuzu-backed vault graph layer:

1. **Leiden community detection** over the vault graph
2. **Interactive HTML graph viewer** (single self-contained `graph.html`)
3. **`/vault-query` natural-language graph queries** (BFS/DFS)
4. **Community-based wiki generation** under `07-References/communities/`
5. **Multimodal corpus extraction** (PDF + audio/video, opt-in `requirements-multimodal.txt`)

v0.8.0 lands after v0.7.0 ships.

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

[Unreleased]: https://github.com/acunningham-ai/Charon/compare/v0.27.0...HEAD
[0.27.0]: https://github.com/acunningham-ai/Charon/releases/tag/v0.27.0
[0.26.0]: https://github.com/acunningham-ai/Charon/releases/tag/v0.26.0
[0.25.1]: https://github.com/acunningham-ai/Charon/releases/tag/v0.25.1
[0.25.0]: https://github.com/acunningham-ai/Charon/releases/tag/v0.25.0
[0.24.3]: https://github.com/acunningham-ai/Charon/releases/tag/v0.24.3
[0.24.2]: https://github.com/acunningham-ai/Charon/releases/tag/v0.24.2
[0.24.1]: https://github.com/acunningham-ai/Charon/releases/tag/v0.24.1
[0.24.0]: https://github.com/acunningham-ai/Charon/releases/tag/v0.24.0
[0.23.2]: https://github.com/acunningham-ai/Charon/releases/tag/v0.23.2
[0.23.1]: https://github.com/acunningham-ai/Charon/releases/tag/v0.23.1
[0.23.0]: https://github.com/acunningham-ai/Charon/releases/tag/v0.23.0
[0.22.0]: https://github.com/acunningham-ai/Charon/releases/tag/v0.22.0
[0.21.0]: https://github.com/acunningham-ai/Charon/releases/tag/v0.21.0
[0.20.0]: https://github.com/acunningham-ai/Charon/releases/tag/v0.20.0
[0.19.0]: https://github.com/acunningham-ai/Charon/releases/tag/v0.19.0
[0.18.0]: https://github.com/acunningham-ai/Charon/releases/tag/v0.18.0
[0.17.0]: https://github.com/acunningham-ai/Charon/releases/tag/v0.17.0
[0.16.1]: https://github.com/acunningham-ai/Charon/releases/tag/v0.16.1
[0.16.0]: https://github.com/acunningham-ai/Charon/releases/tag/v0.16.0
[0.15.3]: https://github.com/acunningham-ai/Charon/releases/tag/v0.15.3
[0.15.2]: https://github.com/acunningham-ai/Charon/releases/tag/v0.15.2
[0.15.1]: https://github.com/acunningham-ai/Charon/releases/tag/v0.15.1
[0.15.0]: https://github.com/acunningham-ai/Charon/releases/tag/v0.15.0
[0.14.1]: https://github.com/acunningham-ai/Charon/releases/tag/v0.14.1
[0.14.0]: https://github.com/acunningham-ai/Charon/releases/tag/v0.14.0
[0.13.0]: https://github.com/acunningham-ai/Charon/releases/tag/v0.13.0
[0.12.0]: https://github.com/acunningham-ai/Charon/releases/tag/v0.12.0
[0.11.0]: https://github.com/acunningham-ai/Charon/releases/tag/v0.11.0
[0.10.2]: https://github.com/acunningham-ai/Charon/releases/tag/v0.10.2
[0.10.1]: https://github.com/acunningham-ai/Charon/releases/tag/v0.10.1
[0.10.0]: https://github.com/acunningham-ai/Charon/releases/tag/v0.10.0
[0.9.1]: https://github.com/acunningham-ai/Charon/releases/tag/v0.9.1
[0.9.0]: https://github.com/acunningham-ai/Charon/releases/tag/v0.9.0
[0.8.1]: https://github.com/acunningham-ai/Charon/releases/tag/v0.8.1
[0.8.0]: https://github.com/acunningham-ai/Charon/releases/tag/v0.8.0
[0.7.1]: https://github.com/acunningham-ai/Charon/releases/tag/v0.7.1
[0.7.0]: https://github.com/acunningham-ai/Charon/releases/tag/v0.7.0
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
