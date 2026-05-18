---
id: 05
slug: load-project-claude-md
category: project-claude-loading
tests: session-start-ritual project CLAUDE.md auto-load on project-name mention
setup_required: yes
---

# 05 — Project CLAUDE.md loads on project-name mention

## Setup

Create a project folder with its own CLAUDE.md carrying specific, easily-verifiable operational facts:

`08-Projects/Test-Service/CLAUDE.md`:

```markdown
# Test-Service

## Operational facts
- Host: SSH alias `test-svc-host` (Ubuntu host)
- Port: 7777
- Service unit: `test-svc.service`
- **Dual-restart required**: after any config change, restart both `test-svc.service` AND `test-svc-worker.service`.
- Log path: `/var/log/test-svc/main.log`

## Why dual-restart
The worker process caches config at boot. Restarting only the main service leaves the worker on the old config until its next restart.
```

## Prompt

> "Walk me through restarting Test-Service after a config change."

## Pass criteria

- References the **SSH alias `test-svc-host`** (or the host concept — not a generic "ssh to your host").
- Mentions **BOTH** `test-svc.service` AND `test-svc-worker.service` need restarting (the dual-service requirement).
- Either:
  - Cites the project CLAUDE.md (`08-Projects/Test-Service/CLAUDE.md`) explicitly, OR
  - Shows the load happened (mentions specific facts that only appear in that file, e.g. port 7777 or the worker-caches-config rationale).
- Confidence 🟢 (read this turn) or 🟡 (project CLAUDE.md loaded earlier in session).

## Fail criteria

- Restart command targets only one service (misses the dual-service requirement).
- Returns generic systemd restart syntax without project-specific details (port, alias, dual-service).
- Asks the user for the SSH details despite them being in the project CLAUDE.md.
- Invents alias / port / service names that aren't in the file.

## Partial credit

- Restarts one service correctly but misses the dual-service requirement: **PARTIAL**.
- Mentions both services but uses generic host language rather than the alias: **PARTIAL**.

## Why this scenario exists

The canonical session-start-ritual failure: project facts exist in a project CLAUDE.md but aren't loaded when the project is mentioned by name. Per `.claude/rules/session-start-ritual.md`: *"Project name (any active initiative the user has named) → Project's `CLAUDE.md` in `08-Projects/<project>/`"*. Tests this rail.

## Cleanup

Remove `08-Projects/Test-Service/` after the run.
