---
type: reference
title: Runbook template — per-project operations
created: 2026-10-12
scope: "One per project with a live runtime — a deployed service, a scheduled job, a hosted web app, a recurring automation. Read-only projects (research notes, talk drafts, reference docs) don't need one."
applies_to: 08-Projects/<name>/runbook.md
tags: [reference/operations, convention/runbook]
---

# Project runbook template

Drop this into `08-Projects/<name>/runbook.md` for any project with a live runtime.

**Why:** a project's `CLAUDE.md` usually holds some operational content — deploy steps, restart order,
degraded modes, the last incident — but buried inline at varying depth. This template surfaces it in the
same place every time, so any session can answer "how do I restart this safely?" without re-reading the
whole project history.

**Pair with CLAUDE.md:** `CLAUDE.md` = what the assistant should know about the project.
`runbook.md` = what the operator does when something breaks.

---

```markdown
---
project: <project name>
runtime_host: <hostname / "local" / "scheduled task" / etc>
last_reviewed: YYYY-MM-DD
review_cadence: <quarterly / on-incident / pre-deploy>
classification: internal
---

# <project> — runbook

## At-a-glance

| Field | Value |
|---|---|
| **Status** | LIVE / DEGRADED / TEST MODE / PAUSED — with date |
| **Owner** | <name, role> |
| **Runtime** | <where it runs — laptop scheduled task / a named server / a serverless worker / etc.> |
| **Trigger** | <user-invoked / cron schedule / event-driven> |
| **Last deploy** | YYYY-MM-DD — <one-line summary of what changed> |
| **Last incident** | YYYY-MM-DD — <one-line — or "none on record"> |

## Deploy

Step-by-step. Each step verifiable.

1. `<command>` — what to expect on success.
2. `<command>` — what to expect on success.
3. Verify: `<command or URL>` returns `<expected output>`.

**Pre-flight** — anything that must be true before step 1 (lock files cleared, dependencies installed,
branch synced, etc.):
- ...

**Rollback** — if step N fails, do this:
- ...

## Restart sequence

If the runtime is a service: name every service that must be restarted and in what order. If the runtime
is a script: state whether it's idempotent and what to clean up before re-running.

```
<exact restart commands>
```

**Co-restart couplings:** if restarting X also requires restarting Y, name it here (e.g. a web app whose
`.env` changes: restart the app AND the worker that reads the same file).

## Health check

How to confirm the runtime is healthy *right now*. One paragraph, ideally one command.

```
<health-check command or URL>
```

Expected output / state when healthy. Threshold for "degraded".

## Known degraded modes

Time-bound or vendor-bound conditions where the runtime is intentionally running below full capability.
Each entry: condition, since-date, expected-resolution-date, impact, monitoring.

- **<degraded mode>** — since YYYY-MM-DD, ETA <when restored>. Impact: <what doesn't work>. Monitoring: <where to check>.

## Named bugs / gotchas

Bugs that have a label and a workaround. Distinct from "things that just don't work" — these are things
someone (you, a vendor, a contributor) has named and is tracking.

- **<bug name>** — symptom, workaround, where it's tracked (issue ID / project memory / vendor ticket).

## Secret inventory (names + locations, never values)

Secret names, where each lives, and when it was rotated. **No values in this file.** Secrets live in the
per-host secrets directory — `$HOME/.secrets/` by default, or whatever `HARNESS_SECRETS_DIR` points at
(`scripts/lib/harness_paths.py` → `secrets_dir()`), outside the vault so they never sync or get committed.

| Secret name | Used for | Location | Last rotated | Next rotation |
|---|---|---|---|---|
| ... | ... | `<secrets dir>/<name>.json` | YYYY-MM-DD | YYYY-MM-DD |

## Backup story

- **What gets backed up:** <data sources>
- **Where:** <destination>
- **Cadence:** <how often>
- **Restore tested:** YYYY-MM-DD (or "never — tracked as a gap")
- **Restore procedure:** <link to procedure or inline steps>

## Last-incident log

Reverse-chronological. Each entry: date, one-line summary, root cause, fix, link to fuller writeup.

- **YYYY-MM-DD** — <one-line>. Root cause: <one-line>. Fix: <one-line>. Detail: `<path or link>`.

## Provenance / cross-refs

- `CLAUDE.md` — operational facts (point to the project's CLAUDE.md)
- `architecture.md` — design, if separate from CLAUDE.md
- `07-References/security-baselines.md` — the C-1..C-9 controls this runtime should comply with
```

---

## How to roll this out (no urgency — do it as you touch each project)

1. Next time you're working in `08-Projects/<name>/`, drop a copy of the template above into `runbook.md`.
2. Fill in what you know; leave gaps explicit ("never — tracked as a gap") rather than blank. A blank reads
   as "nothing to say"; an explicit gap reads as "known unknown".
3. Don't migrate everything from `CLAUDE.md` — keep `CLAUDE.md` for "what the assistant should know"; the
   runbook is for "what the operator does". Cross-reference instead of duplicating.

**Which projects first:** the ones whose operational facts are scattered across several files — a service
with a two-part restart, a scheduled job with a vendor-imposed degraded mode, anything holding secrets. A
project that is mostly authoring (notes, reports, drafts) needs at most a thin runbook for the scripts it
contains.
