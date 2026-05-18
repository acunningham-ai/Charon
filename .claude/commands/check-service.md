---
description: Service health check — service status, recent log, error scan over an SSH-reachable host
argument-hint: "<service-name> [optional: 'verbose' for full log dump, 'errors' for error scan only]"
allowed-tools: Bash, Read
---

# /check-service — quick health check on a deployed service

Quick triage of a deployed service over SSH. Configure your service profile during first-run (or per-service in `08-Projects/<service>/CLAUDE.md`): SSH alias, service unit names, log path, known degraded modes.

## Mode
$ARGUMENTS

- empty / `default` → run all checks below (you'll need a service-name to know which profile to apply)
- `verbose` → also tail 200 lines of the service log
- `errors` → only the error scan (step 4)

If `$ARGUMENTS` is empty, stop and ask which service. Examples surface from `08-Projects/*/CLAUDE.md` (services you've configured).

## Checks (run in order, against the service profile from `08-Projects/<service>/CLAUDE.md`)

### 1. Service status — ALL units in the profile

Most service deployments have multiple systemd units that should be checked together (e.g. main service + dashboard / web frontend). The profile lists which units to check.

```
ssh <alias> 'sudo systemctl status <unit1> --no-pager | head -10; echo ---; sudo systemctl status <unit2> --no-pager | head -10'
```

All listed units must be `active (running)`. If one is down and another isn't, that's already a signal — many service profiles require restarting units together (e.g. after `.env` changes).

### 2. Recent log tail (default 50 lines)

```
ssh <alias> 'sudo tail -50 <log-path>'
```
For `verbose` mode, use `-200` instead.

### 3. Last successful run

Look in the log for the most recent message indicating a normal cycle completion. Note the timestamp — if stale relative to expected cadence (configurable per service), flag it.

### 4. Error scan

```
ssh <alias> 'sudo grep -iE "error|exception|traceback|failed" <log-path> | tail -20'
```
Only flag NEW errors. Known degraded modes (configured in the service profile — e.g. "vendor data feed missing → degraded identity mode, vendor ETA ~N months") are expected.

### 5. Disk + log size sanity

```
ssh <alias> 'df -h / | tail -1; du -sh <log-dir>'
```
Flag if `/` is >85% full or logs >2GB.

## SSH failure handling

If any `ssh <alias>` command fails with auth error:
1. Run the project's documented SSH credential recovery (typically `python scripts/recover-ssh-creds.py <user>`)
2. Falls back to the configured secrets file (typically `~/.secrets/<service>.json`)
3. Only escalate to the user if BOTH paths fail — don't ask for credentials before trying recovery

## Output format

Compact summary, not raw dumps:

```markdown
## <Service> status: {🟢 healthy | 🟡 degraded-but-known | 🔴 needs attention}

- <unit1>: {active|stopped|failed}
- <unit2>: {active|stopped|failed}
- Last run: {timestamp}, {N min ago}
- Errors (24h): {count} — {category breakdown}
- Disk: {%}, Logs: {size}

### New errors (if any)
{paste relevant log lines, redact any PII}

### Action needed
{e.g. "Restart all units" / "None — known degraded mode is expected" / "Investigate {error}"}
```

Don't paste raw log dumps unless asked. The verdict is the value, not the data.
