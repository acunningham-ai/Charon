<#
.SYNOPSIS
  Login/unlock-triggered catchup for missed scheduled harness runs (Windows).

.DESCRIPTION
  The harness's daily scheduled tasks (capture pipeline, TODO refresh) fire at a
  fixed time but are deliberately Interactive-only with no missed-run catch-up,
  per the harness security baseline (never wake-from-sleep, never run-when-
  logged-off, never stored credentials). The tradeoff: if the machine is asleep,
  off, or on battery at the scheduled time, that day's run is skipped and your
  TODO / triage / refresh skills operate on stale data until the next day.

  This script restores reliability WITHOUT breaking the interactive-only rule.
  It runs at logon AND on workstation unlock - both moments when you are present
  at the machine, so nothing becomes unattended. If today's run was missed, it
  triggers the configured scheduled task(s) in order; if the day already ran, it
  no-ops immediately.

  Freshness signal: by default it checks whether your TODO.md was last written
  today. TODO.md is the natural heartbeat because the TODO-refresh step is the
  tail of the morning routine - if it stamped today, the morning run happened.

  Tasks are run SEQUENTIALLY (wait for each to finish before starting the next).
  If your capture and refresh are separate tasks that both touch shared state
  (e.g. a capture cursor / dedup index), running them concurrently can corrupt
  that state - sequential execution avoids it.

  ASCII-only on purpose: PowerShell 5.1 reads BOM-less files as the ANSI
  codepage and mangles non-ASCII punctuation into parse errors. Keep it ASCII.

.PARAMETER Tasks
  Ordered list of Windows scheduled-task names to run (sequentially) when a
  catchup is needed. Default: "Harness Daily" (matches CONFIGURATION.md example).
  If your TODO refresh is a separate task, list both: e.g.
  -Tasks "Harness Daily","Harness TODO Refresh".

.PARAMETER FreshnessFile
  File whose LastWriteTime date indicates the last successful run. Default:
  <VaultRoot>\TODO.md. If today's date == its mtime date, the script no-ops.

.PARAMETER VaultRoot
  Vault root. Default: $env:HARNESS_VAULT_ROOT, else the script's grandparent
  (capture-pipeline lives under the vault in the reference layout; adjust if
  your capture pipeline lives elsewhere via $env:HARNESS_CAPTURE_ROOT).

.PARAMETER NotBeforeHour
  Do not catch up before this local hour - lets the scheduled task own the
  normal window. Default: 7 (matches the documented 07:00 cadence).

.PARAMETER DryRun
  Evaluate the gates and log the decision, but trigger nothing. For testing.
#>
param(
    [string[]]$Tasks         = @("Harness Daily"),
    [string]  $FreshnessFile = "",
    [string]  $VaultRoot     = "",
    [int]     $NotBeforeHour = 7,
    [switch]  $DryRun
)

$ErrorActionPreference = 'Stop'
$maxWaitMin = 90

# Resolve roots. capture-pipeline/ is this script's directory.
$captureDir = $PSScriptRoot
if (-not $VaultRoot) {
    if ($env:HARNESS_VAULT_ROOT) { $VaultRoot = $env:HARNESS_VAULT_ROOT }
    else { $VaultRoot = Split-Path $captureDir -Parent }
}
if (-not $FreshnessFile) { $FreshnessFile = Join-Path $VaultRoot 'TODO.md' }

$stateDir = Join-Path $captureDir 'state'
if (-not (Test-Path $stateDir)) { New-Item -ItemType Directory -Path $stateDir -Force | Out-Null }
$log = Join-Path $stateDir 'login-catchup.log'

function Log($m) {
    "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')  $m" | Out-File -FilePath $log -Append -Encoding utf8
}

function Wait-Task($name) {
    $deadline = (Get-Date).AddMinutes($maxWaitMin)
    do {
        Start-Sleep -Seconds 10
        $state = (Get-ScheduledTask -TaskName $name -ErrorAction Stop).State
        if ((Get-Date) -gt $deadline) {
            Log "  WARNING: '$name' still '$state' after $maxWaitMin min - abandoning wait."
            return $false
        }
    } while ($state -eq 'Running')
    $rc = (Get-ScheduledTask -TaskName $name | Get-ScheduledTaskInfo).LastTaskResult
    Log "  '$name' finished (result $rc)."
    return $true
}

try {
    $tag = if ($DryRun) { ' [DRY RUN]' } else { '' }
    Log "=== Login/unlock catchup invoked$tag (tasks: $($Tasks -join ', ')) ==="
    $now = Get-Date

    # Gate 1: before the scheduled hour, let the scheduled task own the run.
    if ($now.Hour -lt $NotBeforeHour) {
        Log "Before ${NotBeforeHour}:00 - deferring to scheduled task. Exit."
        return
    }

    # Gate 2: did today's run already happen?
    if (Test-Path $FreshnessFile) {
        $fDate = (Get-Item $FreshnessFile).LastWriteTime.Date
        if ($fDate -eq $now.Date) {
            Log "Freshness file current ($FreshnessFile, last write $fDate). Nothing to do. Exit."
            return
        }
        Log "Freshness file stale (last write $fDate, today $($now.Date.ToShortDateString()))."
    } else {
        Log "Freshness file not found ($FreshnessFile) - treating as stale."
    }

    # Gate 3: don't pile on if any target task is already running.
    foreach ($t in $Tasks) {
        $task = Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue
        if ($null -eq $task) { Log "WARNING: task '$t' not found - skipping it."; continue }
        if ($task.State -eq 'Running') {
            Log "'$t' is already Running - a scheduled run is in flight. Exit."
            return
        }
    }

    if ($DryRun) {
        Log "DRY RUN: would run $($Tasks -join ' -> ') sequentially. No action taken."
        return
    }

    # Run each task sequentially; stop the chain if one fails to complete.
    foreach ($t in $Tasks) {
        if ($null -eq (Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue)) { continue }
        Log "Starting '$t'..."
        Start-ScheduledTask -TaskName $t
        if (-not (Wait-Task $t)) {
            Log "Aborting chain: '$t' did not complete cleanly."
            break
        }
    }

    Log "=== Catchup complete ==="
}
catch {
    Log "ERROR: $($_.Exception.Message)"
    # Fail silent - a catchup failure must never block logon.
}
