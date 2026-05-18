# Charon bootstrap installer — Windows
# -------------------------------------
# Pre-Python bootstrap. Detects prerequisites, offers auto-install via
# winget OR shows install instructions, then hands off to the first-run
# wizard.
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File install.ps1
#   or, if your execution policy allows:
#   .\install.ps1
#
# Non-interactive mode for unattended installs:
#   .\install.ps1 -AcceptDefaults
#
# This script never elevates to admin on its own. winget runs per-user
# by default.

[CmdletBinding()]
param(
    [switch]$AcceptDefaults,
    [switch]$SkipPython,
    [switch]$SkipObsidian,
    [switch]$SkipFirstRun
)

$ErrorActionPreference = "Stop"

# --- Small inline banner (pre-Python) ---
Write-Host ""
Write-Host "+----------------------------------------------------------+"
Write-Host "|                                                          |"
Write-Host "|        CHARON  -  second-brain harness                   |"
Write-Host "|        for Claude Code                                   |"
Write-Host "|                                                          |"
Write-Host "+----------------------------------------------------------+"
Write-Host ""
Write-Host "Bootstrap installer (Windows)"
Write-Host ""

$RepoRoot = $PSScriptRoot

function Ask {
    param([string]$Prompt, [string]$Default = "")
    if ($AcceptDefaults -and $Default) { return $Default }
    $suffix = if ($Default) { " [$Default]" } else { "" }
    $answer = Read-Host "  $Prompt$suffix"
    if (-not $answer -and $Default) { return $Default }
    return $answer
}

function Ask-Choice {
    param([string]$Prompt, [string[]]$Choices, [string]$Default)
    while ($true) {
        $a = Ask -Prompt $Prompt -Default $Default
        $lower = $a.ToLower()
        foreach ($c in $Choices) { if ($lower -eq $c.ToLower()) { return $lower } }
        Write-Host "    Please answer one of: $($Choices -join ', ')" -ForegroundColor Yellow
    }
}

function Test-Command {
    param([string]$Name)
    try { return [bool](Get-Command $Name -ErrorAction Stop) }
    catch { return $false }
}

function Get-PythonVersion {
    foreach ($cmd in @("python", "python3", "py")) {
        if (Test-Command $cmd) {
            try {
                $v = & $cmd --version 2>&1
                if ($v -match "Python (\d+)\.(\d+)") {
                    return [pscustomobject]@{
                        Command = $cmd
                        Major = [int]$Matches[1]
                        Minor = [int]$Matches[2]
                        Raw = $v
                    }
                }
            } catch { }
        }
    }
    return $null
}

function Install-WithWinget {
    param([string]$Id, [string]$Friendly)
    if (-not (Test-Command "winget")) {
        Write-Host "    winget not available. Install manually from the link above." -ForegroundColor Yellow
        return $false
    }
    Write-Host "    Running: winget install --id $Id -e --silent" -ForegroundColor Cyan
    try {
        winget install --id $Id -e --silent --accept-package-agreements --accept-source-agreements
        return $true
    } catch {
        Write-Host "    winget install failed: $_" -ForegroundColor Yellow
        return $false
    }
}

# --- Step 1: Python ---
Write-Host "Step 1 - Python 3.10+" -ForegroundColor Green
$py = Get-PythonVersion
if ($py -and $py.Major -ge 3 -and $py.Minor -ge 10) {
    Write-Host "  Found: $($py.Raw) via '$($py.Command)'"
} elseif ($SkipPython) {
    Write-Host "  Skipped per -SkipPython"
} else {
    if ($py) {
        Write-Host "  Found older Python: $($py.Raw). Need 3.10+." -ForegroundColor Yellow
    } else {
        Write-Host "  Python not found." -ForegroundColor Yellow
    }
    Write-Host ""
    Write-Host "  Install URL:  https://www.python.org/downloads/"
    Write-Host "  winget id:    Python.Python.3.12"
    Write-Host ""
    $choice = Ask-Choice -Prompt "(a)uto-install via winget / (m)anual install (open URL, then re-run) / (s)kip" -Choices @("a","m","s") -Default "a"
    switch ($choice) {
        "a" {
            $ok = Install-WithWinget -Id "Python.Python.3.12" -Friendly "Python 3.12"
            if ($ok) {
                Write-Host "  Python installed. You may need to open a new shell for PATH to update." -ForegroundColor Green
                Write-Host "  Re-run install.ps1 in a fresh terminal." -ForegroundColor Yellow
                exit 0
            }
        }
        "m" {
            Start-Process "https://www.python.org/downloads/"
            Write-Host "  Browser opened. Install Python 3.10+ and re-run install.ps1." -ForegroundColor Yellow
            exit 0
        }
        "s" {
            Write-Host "  Skipping. Note: Charon hooks need Python to run." -ForegroundColor Yellow
        }
    }
}

# --- Step 2: Obsidian (optional) ---
Write-Host ""
Write-Host "Step 2 - Obsidian (optional but recommended)" -ForegroundColor Green
$obsidianInstalled = (Test-Path "$env:LOCALAPPDATA\Obsidian\Obsidian.exe") -or (Test-Path "C:\Program Files\Obsidian\Obsidian.exe")
if ($obsidianInstalled) {
    Write-Host "  Found in standard install path."
} elseif ($SkipObsidian) {
    Write-Host "  Skipped per -SkipObsidian"
} else {
    Write-Host "  Obsidian not detected (or installed in a non-standard path)." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  Install URL:  https://obsidian.md/download"
    Write-Host "  winget id:    Obsidian.Obsidian"
    Write-Host ""
    $choice = Ask-Choice -Prompt "(a)uto-install via winget / (m)anual install / (s)kip - the harness works without Obsidian" -Choices @("a","m","s") -Default "s"
    switch ($choice) {
        "a" {
            Install-WithWinget -Id "Obsidian.Obsidian" -Friendly "Obsidian" | Out-Null
        }
        "m" {
            Start-Process "https://obsidian.md/download"
            Write-Host "  Browser opened. Install Obsidian and continue." -ForegroundColor Yellow
        }
        "s" {
            Write-Host "  Skipping. You can edit the vault with any markdown tool."
        }
    }
}

# --- Step 3: Python dependencies ---
Write-Host ""
Write-Host "Step 3 - Python dependencies (PyYAML, anthropic, mcp)" -ForegroundColor Green
$pyCmd = (Get-PythonVersion).Command
if (-not $pyCmd) {
    Write-Host "  No Python found - skipping dependency install. Re-run install.ps1 after installing Python." -ForegroundColor Yellow
} else {
    $reqs = Join-Path $RepoRoot "requirements.txt"
    if (Test-Path $reqs) {
        Write-Host "  Running: $pyCmd -m pip install -r requirements.txt" -ForegroundColor Cyan
        & $pyCmd -m pip install -r $reqs
    } else {
        Write-Host "  requirements.txt not found at $reqs - skipping." -ForegroundColor Yellow
    }
}

# --- Step 4: Secrets directory ---
Write-Host ""
Write-Host "Step 4 - Secrets directory" -ForegroundColor Green
$secretsDefault = Join-Path $env:USERPROFILE ".secrets"
$secrets = Ask -Prompt "Where should credentials live?" -Default $secretsDefault
if (-not (Test-Path $secrets)) {
    New-Item -ItemType Directory -Path $secrets -Force | Out-Null
    Write-Host "  Created $secrets"
}
# Restrict permissions: remove inheritance, grant current user only.
try {
    icacls $secrets /inheritance:r /grant:r "$($env:USERNAME):(OI)(CI)F" /T | Out-Null
    Write-Host "  Permissions restricted to $env:USERNAME"
} catch {
    Write-Host "  Couldn't restrict permissions automatically. Right-click - Properties - Security - restrict to your user." -ForegroundColor Yellow
}

# --- Step 5: First-run wizard ---
if ($SkipFirstRun) {
    Write-Host ""
    Write-Host "Skipping first-run wizard per -SkipFirstRun. Run later with:" -ForegroundColor Yellow
    Write-Host "    python scripts\first-run.py"
    exit 0
}
Write-Host ""
Write-Host "Step 5 - Hand off to first-run wizard" -ForegroundColor Green
$pyCmd = (Get-PythonVersion).Command
if (-not $pyCmd) {
    Write-Host "  No Python found - can't run the wizard. Install Python and re-run install.ps1." -ForegroundColor Red
    exit 1
}
$wizard = Join-Path $RepoRoot "scripts\first-run.py"
if (-not (Test-Path $wizard)) {
    Write-Host "  Wizard not found at $wizard" -ForegroundColor Red
    exit 1
}
Write-Host ""
& $pyCmd $wizard
