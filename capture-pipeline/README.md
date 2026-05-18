# Capture pipeline — reference implementation

Pulls email from your provider (M365 / Gmail / IMAP / generic) into your vault as markdown captures. **Both inbox AND sent items** by default — sent-items capture lets the harness learn what you've responded to, what commitments you've made, and where threads stand from your side.

Captures land under `<vault>/00-Inbox/_captured/email/<routing>/...` with a `direction: inbound|outbound` frontmatter flag so downstream skills (TODO refresh, triage, follow-up) can distinguish.

## Why both inbox + sent

Inbox-only capture leaves a one-sided view of every conversation. Sent items close the loop: when did you respond, what did you commit to, what threads do you owe a reply on. The `direction:` flag in frontmatter lets `/refresh-todo` and `/triage-inbox` surface "you sent X two days ago, no reply yet" — time-management signal that an inbox-only pipeline can't produce.

If your use case truly doesn't need sent items (privacy, legal hold, archive-only), set `capture.sent: false` in your config and the pipeline skips them.

## Status

This is a **reference implementation** shipped with Charon. It's structured to be cloned, configured, and run by `cron` / Windows Task Scheduler / launchd. The first-run wizard creates `config.json` from your answers; you can hand-edit afterwards.

| Provider | Status |
|---|---|
| **Microsoft 365 / Graph API** | Working — device-code OAuth, paginated inbox + sent, cursor-based incremental |
| **Gmail (Gmail API)** | Skeleton — interface stub. See `EMAIL-PROVIDER-SETUP.md` for OAuth setup before filling in `fetchInbox` / `fetchSent`. PRs welcome. |
| **Generic IMAP** | Skeleton — interface stub. App-password auth + TLS. PRs welcome. |

Why only one provider fully working? The harness ships the *pattern*; users supply the rest. M365 was implemented first because it covers most CISO / enterprise use cases.

## Layout

```
capture-pipeline/
├── README.md                — this file
├── package.json             — npm deps
├── config.example.json      — config template (first-run renders this to config.json)
├── .gitignore               — excludes state/, secrets, audit log
├── fetch-mail.mjs           — entry point: `node fetch-mail.mjs <auth|inbox|sent|all>`
└── lib/
    ├── providers/
    │   ├── base.mjs         — interface every provider implements
    │   ├── m365.mjs         — Microsoft Graph
    │   ├── gmail.mjs        — Gmail API (skeleton)
    │   ├── imap.mjs         — Generic IMAP (skeleton)
    │   └── index.mjs        — provider loader
    ├── capture.mjs          — process items → classify → write to vault
    ├── classify.mjs         — domain-based routing (config-driven)
    ├── format.mjs           — markdown formatter + frontmatter
    └── state.mjs            — captured-item index + cursor
```

## Quick start

```bash
cd capture-pipeline
npm install
cp config.example.json config.json   # then edit, OR have first-run.py render it for you
node fetch-mail.mjs auth              # one-time auth (device code for M365)
node fetch-mail.mjs all               # fetch both inbox + sent
```

**Provider-specific setup** (app registrations, OAuth clients, IMAP server settings, scopes): see `EMAIL-PROVIDER-SETUP.md` in the repo root.

## Schedule it

Wrapper scripts ship with the pipeline:

- `scheduled-capture.bat` (Windows) — for Task Scheduler
- `scheduled-capture.sh` (macOS / Linux) — for cron or launchd

Each is a thin wrapper that resolves its own directory, ensures `state/` exists, runs `node fetch-mail.mjs all`, and appends to `state/scheduled-run.log`. The first-run wizard captures your preferred frequency + time; registering with the platform scheduler is a one-time manual step.

Full per-platform walk-through (Task Scheduler / launchd / cron) is in `EMAIL-PROVIDER-SETUP.md` §Scheduling at the repo root.

Default cadence: **daily 07:00 local time** — pairs with `/refresh-todo` as a day-start routine.

## Trust boundary

Every captured file is written with `trust: untrusted` frontmatter + an `UNTRUSTED CAPTURED CONTENT` banner at the top of the body. This is C-7 of `07-References/security-baselines.md`. The `.claude/rules/captures.md` rule auto-injects on any read under `00-Inbox/_captured/**` so the assistant treats body text as data, never as instructions.

## Failure mode to know about

OAuth tokens expire. If the pipeline runs silently for ≥2 days with `device_code_expired` / `401` / `Token expired` errors, the harness's session-start ritual should surface that (see `feedback_pipeline_failure_surface.md` if you ported it). Without that surfacing, captures silently drift and your TODO / triage / refresh skills operate on stale data.

Heuristics for catching it early:

- `scheduled-run.log` tail at session start — look for `Fatal error` / `device_code_expired` / consecutive failure markers.
- `check-capture-state.py` script (ships in Charon) — diagnoses cursor + state-file health.
- If you build alerting, base it on N consecutive failed runs in the log, not a single error.

## Extending — add a new provider

1. Copy `lib/providers/base.mjs` interface
2. Implement `auth()`, `fetchInbox({since})`, `fetchSent({since})` returning normalised email objects (see `base.mjs` for shape)
3. Register in `lib/providers/index.mjs`
4. Add a config block to `config.example.json`
5. Add a first-run wizard branch in `scripts/first-run-questions.yaml`
6. Document the setup steps in `EMAIL-PROVIDER-SETUP.md`

Providers are kept narrow on purpose. The classifier + writer don't care which provider supplied the data — they just need the normalised shape.
