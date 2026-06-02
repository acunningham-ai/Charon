<#
.SYNOPSIS
  Registers the harness login/unlock catchup scheduled task (Windows). Run once,
  from an ELEVATED PowerShell.

.DESCRIPTION
  Creates a scheduled task that fires at logon AND on workstation unlock, and
  runs login-catchup.ps1 (in this same directory). That script no-ops if the
  freshness file (default TODO.md) is already today's, and otherwise triggers
  the configured daily task(s) to catch up a missed scheduled run (machine
  asleep / off / on battery at the scheduled time).

  Registering a task touches the protected Task Scheduler store, so this MUST be
  run elevated (Run as Administrator). The task itself runs NON-elevated
  (RunLevel Limited), interactively, as the current user - no wake-from-sleep,
  battery-start allowed (so it runs when you open a laptop lid on battery).

  Compliance: stays inside the harness interactive-only rule. Logon/unlock
  triggers fire only when the user is present; no stored credentials; no wake.

  Idempotent: -Force replaces any existing task of the same name.

  ASCII-only on purpose (PowerShell 5.1 reads BOM-less files as ANSI).

.PARAMETER TaskName
  Name for the catchup task. Default: "Harness Login Catchup".

.PARAMETER User
  User the task runs as. Default: current user (DOMAIN\name or local name).

.PARAMETER CatchupScript
  Full path to login-catchup.ps1. Default: alongside this script.

.PARAMETER CatchupArgs
  Extra arguments passed through to login-catchup.ps1 (e.g. to override -Tasks
  or -FreshnessFile). Example:
    -CatchupArgs '-Tasks "Harness Daily","Harness TODO Refresh"'
#>
param(
    [string]$TaskName      = "Harness Login Catchup",
    [string]$User          = "$env:USERDOMAIN\$env:USERNAME",
    [string]$CatchupScript = "",
    [string]$CatchupArgs   = ""
)

$ErrorActionPreference = 'Stop'

if (-not $CatchupScript) { $CatchupScript = Join-Path $PSScriptRoot 'login-catchup.ps1' }
if (-not (Test-Path $CatchupScript)) { throw "Catchup script not found: $CatchupScript" }

$argLine = "-NoProfile -File `"$CatchupScript`""
if ($CatchupArgs) { $argLine += " $CatchupArgs" }

$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $argLine

$logon = New-ScheduledTaskTrigger -AtLogOn -User $User

# Workstation-unlock trigger. StateChange 8 = TASK_SESSION_UNLOCK.
# New-ScheduledTaskTrigger has no -AtUnlock switch, so build it via CIM.
$cls = Get-CimClass -Namespace ROOT\Microsoft\Windows\TaskScheduler `
    -ClassName MSFT_TaskSessionStateChangeTrigger
$unlock = New-CimInstance -CimClass $cls -ClientOnly
$unlock.StateChange = 8
$unlock.Enabled = $true

$principal = New-ScheduledTaskPrincipal -UserId $User -LogonType Interactive -RunLevel Limited

# Battery-start allowed (laptop catchup often happens unplugged); never wake.
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew `
    -ExecutionTimeLimit (New-TimeSpan -Hours 2) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries

$desc = "Catches up a missed daily harness run when the machine was " +
        "asleep/off/on-battery at the scheduled time. Fires at logon and on " +
        "workstation unlock. No-ops if the freshness file (TODO.md) is already " +
        "today's. Interactive-only, no wake-from-sleep."

Register-ScheduledTask -TaskName $TaskName -Action $action `
    -Trigger @($logon, $unlock) -Principal $principal -Settings $settings `
    -Description $desc -Force | Out-Null

Write-Host "Registered '$TaskName'. Verifying:" -ForegroundColor Green
$t = Get-ScheduledTask -TaskName $TaskName
Write-Host ("  Triggers : " + (($t.Triggers | ForEach-Object { $_.CimClass.CimClassName }) -join ", "))
Write-Host ("  State    : " + $t.State)
Write-Host ("  RunLevel : " + $t.Principal.RunLevel + " (Limited = non-admin, correct)")
Write-Host ("  Battery  : start-on-battery = " + (-not $t.Settings.DisallowStartIfOnBatteries))
Write-Host ("  WakeToRun: " + $t.Settings.WakeToRun + " (False = compliant)")
