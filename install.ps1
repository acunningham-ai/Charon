# Charon bootstrap installer - Windows
# -------------------------------------
# Pre-Python bootstrap. Detects prerequisites, offers auto-install via
# winget OR shows install instructions, then hands off to the first-run
# wizard.
#
# Usage (default: locally-cloned script, least-permissive policy that works):
#   powershell -ExecutionPolicy RemoteSigned -File install.ps1
#
# Fallback for locked-down machines (only after inspecting this file):
#   powershell -ExecutionPolicy Bypass -Scope Process -File install.ps1
#   (-Scope Process confines the bypass to this one invocation, not the
#   machine. Don't use the older -ExecutionPolicy Bypass without -Scope
#   Process: same blast radius for this run, harder discipline elsewhere.)
#
# Run it from a saved copy, never piped in (`irm ... | iex`) or as a script
# block: without its own folder it cannot find the Charon files, so it refuses
# (exit 66). An elevated (Run as administrator) window is refused too (exit
# 77): Charon installs for one user, and an elevated run would leave the
# secrets folder and packages owned by the administrators group.
#
# Accept-defaults mode (answers every installer question with its default,
# but the wizard still asks its own questions):
#   .\install.ps1 -AcceptDefaults
#
# Fully non-interactive (never prompts; the restore offer is skipped and the
# first-run wizard is started with --non-interactive):
#   .\install.ps1 -NonInteractive
#
# Wizard answers from a file (JSON or YAML, question id -> answer), passed to
# the first-run wizard as --answers. A missing file or a folder is exit 64,
# checked before anything runs:
#   .\install.ps1 -NonInteractive -AnswersFile answers.yaml
#
# Side-effect free (detects and reports only: installs nothing, runs no pip
# install, creates no folders or virtual environment, changes no permissions,
# starts no wizard and opens no browser; it prints the commands it would run):
#   .\install.ps1 -DryRun
#
# Python interpreter: searched in the same order the hook launcher uses
# (python3, then python, then `py -3`), Python 3 only, .exe files only (as
# scripts\hook.cmd does), so the interpreter that gets the dependencies and
# runs the wizard is the one the hooks run.
#
# A Python marked externally managed (PEP 668) is never forced: Charon makes
# a private virtual environment at %USERPROFILE%\.charon-venv with it instead,
# installs the requirements into that, and runs the wizard with its python.
#
# Exit status: 0 finished with the required Python packages importable;
# 3 finished but a required package (PyYAML, mcp) is still missing, or Python
# was just installed and this window cannot see it yet (3, not 2, so it is
# never confused with a usage error from the wizard's argument parser);
# 64 bad -AnswersFile; 66 refused (no script folder: piped / iex);
# 77 refused (elevated); any other non-zero value means a step failed (or is
# the wizard's own status).
#
# See INSTALL.md for the full three-step ladder (inspect, verify SHA-256,
# run). This script never elevates to admin on its own. winget runs
# per-user by default.

[CmdletBinding()]
param(
    [switch]$AcceptDefaults,
    [switch]$NonInteractive,
    [switch]$DryRun,
    [switch]$SkipPython,
    [switch]$SkipObsidian,
    [switch]$SkipNode,
    [switch]$SkipFirstRun,
    [string]$AnswersFile
)

$ErrorActionPreference = "Stop"

# --- Refusals, before anything else runs ---
# Piped (`irm ... | iex`) or run as a script block: there is no script file,
# so no Charon folder to install from.
if (-not $PSScriptRoot) {
    Write-Host "install.ps1: Refusing to run without its own folder (piped into iex, or run as a script block)." -ForegroundColor Red
    Write-Host "  Clone or download Charon, read install.ps1, then run it as a file:" -ForegroundColor Red
    Write-Host "    powershell -ExecutionPolicy RemoteSigned -File install.ps1" -ForegroundColor Red
    exit 66
}
# Elevated: Charon is a per-user install.
$elevated = $false
try {
    $principal = New-Object Security.Principal.WindowsPrincipal([Security.Principal.WindowsIdentity]::GetCurrent())
    $elevated = $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
} catch {
    $elevated = $false
}
if ($elevated) {
    Write-Host "install.ps1: Refusing to run elevated (Run as administrator). Charon installs for one user:" -ForegroundColor Red
    Write-Host "  open a normal PowerShell window and run it again. winget installs per-user." -ForegroundColor Red
    exit 77
}
# -AnswersFile must name a file.
$AnswersPath = $null
if ($PSBoundParameters.ContainsKey("AnswersFile")) {
    if (-not $AnswersFile -or -not (Test-Path -LiteralPath $AnswersFile -PathType Leaf)) {
        Write-Host "install.ps1: -AnswersFile: not a file: $AnswersFile" -ForegroundColor Red
        Write-Host "  Give a JSON or YAML file of question id -> answer." -ForegroundColor Red
        exit 64
    }
    $AnswersPath = (Resolve-Path -LiteralPath $AnswersFile).ProviderPath
}

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
$CharonVenv = Join-Path $env:USERPROFILE ".charon-venv"
$CharonVenvPy = Join-Path $CharonVenv "Scripts\python.exe"
$script:VenvPython = $null   # set once Step 4 has made and filled the venv

function Ask {
    param([string]$Prompt, [string]$Default = "")
    # Never read from the console in non-interactive mode.
    if ($NonInteractive) { return $Default }
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

# The first .exe on PATH for a name, as a full path, or $null. A .cmd / .bat /
# .ps1 of the same name is never an interpreter (scripts\hook.cmd accepts .exe
# only), and calling the full path stops PATHEXT picking a .cmd instead.
function Find-Exe {
    param([string]$Name)
    $hit = Get-Command $Name -CommandType Application -All -ErrorAction SilentlyContinue |
        Where-Object { [IO.Path]::GetExtension($_.Source) -ieq ".exe" } |
        Select-Object -First 1
    if ($hit) { return $hit.Source }
    return $null
}

# Run a command with its output going straight to the console (never into a
# function's return value) and return its exit code.
function Invoke-Streamed {
    param([string]$Command, [string[]]$Arguments)
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $rc = 1
    try {
        & $Command @Arguments | Out-Host
        $rc = $LASTEXITCODE
    } catch {
        Write-Host "    $_" -ForegroundColor Yellow
        $rc = 1
    } finally {
        $ErrorActionPreference = $prevEap
    }
    if ($null -eq $rc) { $rc = 1 }
    return [int]$rc
}

# The hook launcher tries python3, then python, then `py -3`, and accepts
# Python 3 only. Search in exactly that order so the interpreter that gets the
# dependencies and runs the wizard is the one the hooks will run. A Python 3
# older than 3.10 is still the launcher's choice: it is reported as too old,
# never skipped, so the installer and the hooks cannot disagree.
# (The Microsoft Store alias for python3 prints "Python was not found" and is
# skipped because it reports no version.)
function Get-PythonVersion {
    $candidates = @(
        @{ Name = "python3"; Prefix = @();     Label = "python3" },
        @{ Name = "python";  Prefix = @();     Label = "python" },
        @{ Name = "py";      Prefix = @("-3"); Label = "py -3" }
    )
    foreach ($c in $candidates) {
        $exe = Find-Exe $c.Name
        if (-not $exe) { continue }
        $prevEap = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        try {
            $probeArgs = @($c.Prefix | Where-Object { $_ }) + @("--version")
            $v = (& $exe @probeArgs 2>&1 | Out-String).Trim()
        } catch {
            $v = ""
        } finally {
            $ErrorActionPreference = $prevEap
        }
        if ($v -match "^Python (\d+)\.(\d+)") {
            if ([int]$Matches[1] -ne 3) { continue }
            return [pscustomobject]@{
                Command = $exe
                Prefix  = $c.Prefix
                Label   = $c.Label
                Major   = [int]$Matches[1]
                Minor   = [int]$Matches[2]
                Raw     = $v
            }
        }
    }
    return $null
}

# The interpreter for every step after the venv decision: Charon's private
# venv once Step 4 has set it up, else the launcher's choice.
function Get-InstallPython {
    if ($script:VenvPython) { return $script:VenvPython }
    return Get-PythonVersion
}

function Test-PythonNewEnough {
    param($Py)
    return ($Py -and $Py.Major -eq 3 -and $Py.Minor -ge 10)
}

# Run the found interpreter for a short probe and capture its stdout as text
# (.Output) with its exit code (.ExitCode). Long-running or interactive calls
# (pip install, restore, the wizard) are made at script scope or through
# Invoke-Streamed instead, so their output streams straight to the console.
function Invoke-Python {
    param($Py, [string[]]$Arguments, [switch]$Capture)
    $allArgs = @($Py.Prefix | Where-Object { $_ }) + @($Arguments)
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    try {
        $out = (& $Py.Command @allArgs 2>$null | Out-String)
        $rc = $LASTEXITCODE
    } catch {
        $out = ""
        $rc = 1
    } finally {
        $ErrorActionPreference = $prevEap
    }
    if ($null -eq $rc) { $rc = 1 }
    return [pscustomobject]@{ ExitCode = [int]$rc; Output = $out }
}

# Required Python packages, by import name. PyYAML is needed by the first-run
# wizard and mcp by the vault MCP servers. anthropic is optional (the hook
# that uses it no-ops without it), so it is reported but never fails.
$RequiredModules = @("yaml", "mcp")
$OptionalModules = @("anthropic")
# Both probes drop the current folder from sys.path before importing anything,
# so a yaml.py / mcp.py (or sysconfig.py) in the folder the installer was run
# from is never loaded or mistaken for the real package. (Not `python -I`: it
# would also hide PYTHONPATH and the user site-packages, and report installed
# packages as missing.)
# One argument, no double quotes (Windows PowerShell 5.1 strips them from
# native-command arguments). The \n are Python string escapes inside exec().
$DepProbe = 'import os, sys; c = os.path.normcase(os.path.realpath(os.getcwd())); sys.path[:] = [p for p in sys.path if p and os.path.normcase(os.path.realpath(p)) != c]; exec(''m=[]\nfor n in sys.argv[1:]:\n try:\n  __import__(n)\n except Exception:\n  m.append(n)\nprint(chr(32).join(m))'')'
$Pep668Probe = 'import os, sys; c = os.path.normcase(os.path.realpath(os.getcwd())); sys.path[:] = [p for p in sys.path if p and os.path.normcase(os.path.realpath(p)) != c]; import sysconfig; print(int(sys.prefix == sys.base_prefix and os.path.isfile(os.path.join(sysconfig.get_path(''stdlib''), ''EXTERNALLY-MANAGED''))))'

function Get-MissingModules {
    # Fails closed: no interpreter or a probe that errors reports all missing.
    param($Py, [string[]]$Modules)
    if (-not $Py) { return $Modules }
    $r = Invoke-Python -Py $Py -Arguments (@("-c", $DepProbe) + $Modules) -Capture
    if ($r.ExitCode -ne 0) { return $Modules }
    $line = ($r.Output -split "`r?`n" | Select-Object -First 1)
    if (-not $line) { return @() }
    return @($line.Trim() -split "\s+" | Where-Object { $_ })
}

function Get-PackageName {
    param([string]$Module)
    if ($Module -eq "yaml") { return "PyYAML" }
    return $Module
}

function Write-Loud {
    param([string[]]$Lines)
    Write-Host "  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!" -ForegroundColor Red
    foreach ($l in $Lines) { Write-Host "  !! $l" -ForegroundColor Red }
    Write-Host "  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!" -ForegroundColor Red
}

# Exact remedies, every path spelled out and quoted so it pastes as it stands.
function Write-DepRemedy {
    param($Py)
    $label = if ($Py) { $Py.Label } else { "python" }
    $req = Join-Path $RepoRoot "requirements.txt"
    Write-Host "  How to fix it (pick one):" -ForegroundColor Yellow
    Write-Host "  1. Charon's private virtual environment, then launch Claude Code from a"
    Write-Host "     shell where it is active (the hooks use the first python3 / python on PATH):"
    Write-Host "       $label -m venv `"$CharonVenv`""
    Write-Host "       & `"$CharonVenvPy`" -m pip install -r `"$req`""
    Write-Host "       & `"$(Join-Path $CharonVenv 'Scripts\Activate.ps1')`""
    Write-Host "  2. Fix pip for this Python (see its output above), then re-run install.ps1, or:"
    Write-Host "       $label -m pip install -r `"$req`""
    Write-Host "  This installer never passes --break-system-packages to pip."
}

# Make the private venv with the launcher's Python and install the
# requirements into it. Returns the venv's interpreter only when both steps
# succeed; on failure the system Python stays in use and the remedy is shown.
function New-CharonVenv {
    param($Py, [string]$Reqs)
    Write-Host "  Creating Charon's private virtual environment instead:" -ForegroundColor Cyan
    Write-Host "  Running: $($Py.Label) -m venv `"$CharonVenv`"" -ForegroundColor Cyan
    $venvArgs = @($Py.Prefix | Where-Object { $_ }) + @("-m", "venv", $CharonVenv)
    $rc = Invoke-Streamed -Command $Py.Command -Arguments $venvArgs
    if ($rc -ne 0) {
        Write-Loud @(
            "Could not create the virtual environment $CharonVenv (exit $rc).",
            "Continuing to the wizard with $($Py.Label). Required packages are checked again at the end."
        )
        return $null
    }
    if (-not (Test-Path -LiteralPath $CharonVenvPy -PathType Leaf)) {
        Write-Loud @(
            "The virtual environment $CharonVenv has no Scripts\python.exe in it.",
            "Continuing to the wizard with $($Py.Label). Required packages are checked again at the end."
        )
        return $null
    }
    Write-Host "  Running: & `"$CharonVenvPy`" -m pip install -r requirements.txt" -ForegroundColor Cyan
    $rc = Invoke-Streamed -Command $CharonVenvPy -Arguments @("-m", "pip", "install", "-r", $Reqs)
    if ($rc -ne 0) {
        Write-Loud @(
            "pip install into $CharonVenv failed (exit $rc). See the pip output above.",
            "Continuing to the wizard with $($Py.Label). Required packages are checked again at the end."
        )
        return $null
    }
    Write-Host "  Installed into $CharonVenv. The wizard runs with its python." -ForegroundColor Green
    Write-Host "  The hooks use the first python3 / python on PATH, so start Claude Code from a" -ForegroundColor Yellow
    Write-Host "  window where this venv is active:  & `"$(Join-Path $CharonVenv 'Scripts\Activate.ps1')`"" -ForegroundColor Yellow
    return [pscustomobject]@{
        Command = $CharonVenvPy
        Prefix  = @()
        Label   = "& `"$CharonVenvPy`""
        Major   = $Py.Major
        Minor   = $Py.Minor
        Raw     = $Py.Raw
    }
}

# Exit: a non-zero status wins; otherwise 3 when a required package is still
# missing for the interpreter in use.
function Exit-Install {
    param([int]$Code)
    if ($Code -ne 0) { exit $Code }
    $still = @(Get-MissingModules -Py (Get-InstallPython) -Modules $RequiredModules)
    if ($still.Count -gt 0) {
        $pkgs = ($still | ForEach-Object { Get-PackageName $_ }) -join " "
        Write-Host ""
        Write-Loud @(
            "Install finished, but required Python packages are still missing: $pkgs",
            "Fix them with the remedy printed in Step 4, then re-run install.ps1.",
            "Exiting with status 3."
        )
        exit 3
    }
    if ($script:VenvPython) {
        Write-Host ""
        Write-Host "  Reminder: start Claude Code from a window where Charon's venv is active:" -ForegroundColor Yellow
        Write-Host "    & `"$(Join-Path $CharonVenv 'Scripts\Activate.ps1')`""
    }
    exit 0
}

function Get-NodeVersion {
    if (Test-Command "node") {
        try {
            $v = & node --version 2>&1
            if ($v -match "v(\d+)\.(\d+)") {
                return [pscustomobject]@{
                    Major = [int]$Matches[1]
                    Minor = [int]$Matches[2]
                    Raw = $v
                }
            }
        } catch { }
    }
    return $null
}

# winget reports failure through its exit code, not an exception: check it.
function Install-WithWinget {
    param([string]$Id, [string]$Friendly)
    if (-not (Test-Command "winget")) {
        Write-Host "    winget not available. Install manually from the link above." -ForegroundColor Yellow
        return $false
    }
    Write-Host "    Running: winget install --id $Id -e --silent" -ForegroundColor Cyan
    $rc = Invoke-Streamed -Command "winget" -Arguments @("install", "--id", $Id, "-e", "--silent",
        "--accept-package-agreements", "--accept-source-agreements")
    if ($rc -ne 0) {
        Write-Host "    winget install --id $Id failed (exit $rc)." -ForegroundColor Yellow
        return $false
    }
    return $true
}

# --- Step 1: Python ---
if ($DryRun) {
    Write-Host "Dry run: detecting and reporting only. Nothing is installed, created or started." -ForegroundColor Cyan
    Write-Host ""
}
Write-Host "Step 1 - Python 3.10+" -ForegroundColor Green
$py = Get-PythonVersion
if (Test-PythonNewEnough $py) {
    Write-Host "  Found: $($py.Raw) via '$($py.Label)' (the interpreter the hooks will use)"
} elseif ($SkipPython) {
    Write-Host "  Skipped per -SkipPython"
} else {
    if ($py) {
        Write-Host "  Found $($py.Raw) via '$($py.Label)', which is the interpreter the hooks will use. Need 3.10+." -ForegroundColor Yellow
    } else {
        Write-Host "  Python 3 not found (looked for python3, python, py -3)." -ForegroundColor Yellow
    }
    Write-Host ""
    Write-Host "  Install URL:  https://www.python.org/downloads/"
    Write-Host "  winget id:    Python.Python.3.12"
    Write-Host ""
    if ($DryRun) {
        $choice = "dry"
        Write-Host "  [dry-run] would offer to install Python via winget here."
    } else {
        $choice = Ask-Choice -Prompt "(a)uto-install via winget / (m)anual install (open URL, then re-run) / (s)kip" -Choices @("a","m","s") -Default "a"
    }
    switch ($choice) {
        "a" {
            $ok = Install-WithWinget -Id "Python.Python.3.12" -Friendly "Python 3.12"
            if (-not $ok) {
                Write-Host "  Could not install Python. Install Python 3.10+ from the URL above, then re-run install.ps1." -ForegroundColor Red
                exit 1
            }
            # PATH is read when a window opens, so this one cannot see the new
            # Python: nothing below can run with it.
            Write-Loud @(
                "Python was installed by winget, but this window cannot see it yet.",
                "The Python dependencies and the first-run wizard did NOT run.",
                "Open a new terminal and run install.ps1 again. Exiting with status 3."
            )
            exit 3
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
    if ($DryRun) {
        $choice = "dry"
        Write-Host "  [dry-run] would offer to install Obsidian via winget here."
    } else {
        $choice = Ask-Choice -Prompt "(a)uto-install via winget / (m)anual install / (s)kip - the harness works without Obsidian" -Choices @("a","m","s") -Default "s"
    }
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

# --- Step 3: Node.js (for capture-pipeline) ---
Write-Host ""
Write-Host "Step 3 - Node.js 18+ (required by the email capture pipeline)" -ForegroundColor Green
$nodeVer = Get-NodeVersion
if ($nodeVer -and $nodeVer.Major -ge 18) {
    Write-Host "  Found: $($nodeVer.Raw)"
} elseif ($SkipNode) {
    Write-Host "  Skipped per -SkipNode"
} else {
    if ($nodeVer) {
        Write-Host "  Found older Node: $($nodeVer.Raw). Need 18+." -ForegroundColor Yellow
    } else {
        Write-Host "  Node.js not found. The email capture pipeline needs Node 18+ to run." -ForegroundColor Yellow
    }
    Write-Host ""
    Write-Host "  Install URL:  https://nodejs.org/"
    Write-Host "  winget id:    OpenJS.NodeJS.LTS"
    Write-Host ""
    if ($DryRun) {
        $choice = "dry"
        Write-Host "  [dry-run] would offer to install Node.js via winget here."
    } else {
        $choice = Ask-Choice -Prompt "(a)uto-install via winget / (m)anual install (open URL, then re-run) / (s)kip - you can install later" -Choices @("a","m","s") -Default "a"
    }
    switch ($choice) {
        "a" {
            # Node is not needed by anything below, so its install never ends
            # the run: the Python dependencies and the wizard still happen.
            $ok = Install-WithWinget -Id "OpenJS.NodeJS.LTS" -Friendly "Node.js LTS"
            if ($ok) {
                Write-Host "  Node.js installed. Open a new terminal before using the capture pipeline, so PATH sees it." -ForegroundColor Green
            } else {
                Write-Host "  Node.js was not installed. Install it later if you want the capture pipeline." -ForegroundColor Yellow
            }
        }
        "m" {
            Start-Process "https://nodejs.org/"
            Write-Host "  Browser opened. Install Node.js 18+ and re-run install.ps1." -ForegroundColor Yellow
            exit 0
        }
        "s" {
            Write-Host "  Skipping. Note: without Node, the capture pipeline cannot run." -ForegroundColor Yellow
        }
    }
}

# --- Step 4: Python dependencies ---
Write-Host ""
Write-Host "Step 4 - Python dependencies (PyYAML, anthropic, mcp)" -ForegroundColor Green
# A pip that is missing, refuses (PEP 668) or fails is reported loudly with its
# remedy and the installer carries on to the wizard; it is never swallowed. The
# exit status at the end says whether the required packages made it.
$py = Get-PythonVersion
$reqs = Join-Path $RepoRoot "requirements.txt"
$depsProblem = ""
$dryVenv = $false
if (-not $py) {
    Write-Host "  No Python 3 found - skipping dependency install. Re-run install.ps1 after installing Python." -ForegroundColor Yellow
} elseif (-not (Test-PythonNewEnough $py)) {
    Write-Host "  $($py.Raw) via '$($py.Label)' is older than 3.10 - skipping dependency install." -ForegroundColor Yellow
} elseif (-not (Test-Path $reqs)) {
    Write-Host "  requirements.txt not found at $reqs - skipping." -ForegroundColor Yellow
} else {
    Write-Host "  Interpreter: $($py.Label) ($($py.Raw))"
    $pipCheck = Invoke-Python -Py $py -Arguments @("-m", "pip", "--version") -Capture
    $pep668 = Invoke-Python -Py $py -Arguments @("-c", $Pep668Probe) -Capture
    $managed = ($pep668.ExitCode -eq 0 -and $pep668.Output.Trim() -eq "1")
    if ($managed) {
        # Never pip into a protected Python. A private venv carries its own
        # pip, so this holds with or without a system pip.
        $depsProblem = "externally-managed"
        Write-Loud @(
            "$($py.Label) is externally managed (PEP 668): pip will refuse to install into it.",
            "pip install was NOT run against it."
        )
        if ($DryRun) {
            $dryVenv = $true
            Write-Host "  [dry-run] would run: $($py.Label) -m venv `"$CharonVenv`""
            Write-Host "  [dry-run] would run: & `"$CharonVenvPy`" -m pip install -r `"$reqs`""
            Write-Host "  [dry-run] the wizard would then run with that venv's python."
        } else {
            $venvPy = New-CharonVenv -Py $py -Reqs $reqs
            if ($venvPy) {
                $script:VenvPython = $venvPy
                $depsProblem = ""
            }
        }
    } elseif ($pipCheck.ExitCode -ne 0) {
        $depsProblem = "no-pip"
        Write-Loud @(
            "pip is not available for $($py.Label), so nothing can be installed with it.",
            "To get pip: $($py.Label) -m ensurepip --user",
            "Continuing to the wizard. Required packages are checked again at the end."
        )
    } elseif ($DryRun) {
        Write-Host "  [dry-run] would run: $($py.Label) -m pip install -r `"$reqs`""
    } else {
        Write-Host "  Running: $($py.Label) -m pip install -r requirements.txt" -ForegroundColor Cyan
        # Script scope, not a function: pip's output streams to the console.
        $pipArgs = @($py.Prefix | Where-Object { $_ }) + @("-m", "pip", "install", "-r", $reqs)
        $prevEap = $ErrorActionPreference
        $ErrorActionPreference = "Continue"
        $pipRc = 1
        try { & $py.Command @pipArgs; $pipRc = $LASTEXITCODE } catch { $pipRc = 1 }
        finally { $ErrorActionPreference = $prevEap }
        if ($null -eq $pipRc) { $pipRc = 1 }
        if ($pipRc -ne 0) {
            $depsProblem = "pip-failed"
            Write-Loud @(
                "pip install failed (exit $pipRc). See the pip output above.",
                "Continuing to the wizard. Required packages are checked again at the end."
            )
        }
    }

    # From here on the venv (when it was set up) is the interpreter in use.
    $remedyPy = $py
    $py = Get-InstallPython
    $step4Missing = @(Get-MissingModules -Py $py -Modules $RequiredModules)
    $step4Optional = @(Get-MissingModules -Py $py -Modules $OptionalModules)
    if ($depsProblem -or $step4Missing.Count -gt 0) {
        if ($step4Missing.Count -gt 0) {
            $pkgs = ($step4Missing | ForEach-Object { Get-PackageName $_ }) -join " "
            Write-Loud @(
                "Required Python packages missing for $($py.Label): $pkgs",
                "The hooks and the wizard need them. install.ps1 will exit with status 3."
            )
        }
        Write-Host ""
        Write-DepRemedy $remedyPy
    } else {
        Write-Host "  Required packages import cleanly (PyYAML, mcp)." -ForegroundColor Green
    }
    if ($step4Optional.Count -gt 0) {
        Write-Host "  Optional package not installed: $($step4Optional -join ' ') (the hook that uses it no-ops without it)." -ForegroundColor Yellow
    }
}

# --- Step 5: Secrets directory ---
Write-Host ""
Write-Host "Step 5 - Secrets directory" -ForegroundColor Green
$secretsDefault = Join-Path $env:USERPROFILE ".secrets"
if ($DryRun) {
    Write-Host "  [dry-run] would create $secretsDefault (or the folder you name) and restrict it to $env:USERNAME"
} else {
    $secrets = Ask -Prompt "Where should credentials live?" -Default $secretsDefault
    if (-not $secrets) { $secrets = $secretsDefault }
    # A leading ~ means the user's profile folder. icacls and New-Item would
    # otherwise each read it their own way.
    if ($secrets -eq "~") {
        $secrets = $env:USERPROFILE
    } elseif ($secrets -match '^~[\\/]') {
        $secrets = Join-Path $env:USERPROFILE $secrets.Substring(2)
    } elseif ($secrets.StartsWith("~")) {
        Write-Host "  '$secrets': ~user paths are not supported. Give a full path, or ~\folder." -ForegroundColor Red
        exit 1
    }
    if (-not (Test-Path -LiteralPath $secrets)) {
        New-Item -ItemType Directory -Path $secrets -Force | Out-Null
        Write-Host "  Created $secrets"
    }
    # Restrict permissions: remove inherited entries and leave one explicit
    # full-control grant for the current user, by SID (a user name can be
    # ambiguous or localised). Not recursive: files already in the folder keep
    # their own permissions. icacls reports failure by exit code, so check it.
    $icacls = Join-Path $env:SystemRoot "System32\icacls.exe"
    $prevEap = $ErrorActionPreference
    $ErrorActionPreference = "Continue"
    $icaclsRc = 1
    $icaclsOut = ""
    try {
        $sid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
        $icaclsOut = (& $icacls $secrets /inheritance:r /grant:r "*$($sid):(OI)(CI)F" 2>&1 | Out-String).Trim()
        $icaclsRc = $LASTEXITCODE
    } catch {
        $icaclsOut = "$_"
        $icaclsRc = 1
    } finally {
        $ErrorActionPreference = $prevEap
    }
    if ($null -eq $icaclsRc) { $icaclsRc = 1 }
    if ($icaclsRc -eq 0) {
        Write-Host "  Permissions restricted to $env:USERNAME (one explicit entry, nothing inherited)"
    } else {
        Write-Host "  Could not restrict permissions on $secrets (icacls exit $icaclsRc)." -ForegroundColor Yellow
        if ($icaclsOut) { Write-Host "    $icaclsOut" -ForegroundColor Yellow }
        Write-Host "  Restrict it yourself: right-click - Properties - Security - your user only." -ForegroundColor Yellow
    }
}

# --- Step 6: Restore from a previous machine? ---
# Offered BEFORE the wizard on purpose. If the user is migrating, the wizard's
# questions are the wrong first experience - their answers already exist in the
# backup. Restore first, and first-run only has to fill genuine gaps.
Write-Host ""
Write-Host "Step 6 - Moving from another computer?" -ForegroundColor Green
$pyR = Get-InstallPython
$backupTool = Join-Path $RepoRoot "scripts\backup-brain.py"
$foundBackup = $null   # the backup folder itself: <drive>\Charon-Backup
if ($pyR -and (Test-Path $backupTool)) {
    foreach ($v in (Get-PSDrive -PSProvider FileSystem -ErrorAction SilentlyContinue)) {
        if (-not $v.Root) { continue }
        try {
            $markerPath = Join-Path $v.Root ".charon-backup-target"
            $backupDir = Join-Path $v.Root "Charon-Backup"
            if ((Test-Path -LiteralPath $markerPath -ErrorAction SilentlyContinue) -and
                (Test-Path -LiteralPath $backupDir -PathType Container -ErrorAction SilentlyContinue)) {
                $foundBackup = $backupDir; break
            }
        } catch { }
    }
    if ($foundBackup) {
        Write-Host "  A Charon backup is on a plugged-in drive: $foundBackup" -ForegroundColor Cyan
        Write-Host "  Restoring brings across your memory, session history and pipeline state."
        Write-Host "  Credentials are never restored - you re-authenticate afterwards."
        if ($DryRun -or $NonInteractive) {
            # A restore overwrites memory; it always needs a person to say yes.
            Write-Host "  Not restoring without a person to confirm. To restore, run:"
            Write-Host "    $($pyR.Label) `"$backupTool`" --restore --from `"$foundBackup`""
        } else {
            $doRestore = Ask-Choice "  Restore from that backup now?" @("y", "n") "y"
            if ($doRestore -eq "y") {
                $restoreArgs = @($pyR.Prefix | Where-Object { $_ }) + @($backupTool, "--restore", "--from", $foundBackup)
                $prevEap = $ErrorActionPreference
                $ErrorActionPreference = "Continue"
                $restoreRc = 1
                try { & $pyR.Command @restoreArgs; $restoreRc = $LASTEXITCODE } catch { $restoreRc = 1 }
                finally { $ErrorActionPreference = $prevEap }
                if ($null -eq $restoreRc) { $restoreRc = 1 }
                if ($restoreRc -ne 0) {
                    Write-Host "  Restore reported a problem (exit $restoreRc) - continuing to the wizard." -ForegroundColor Yellow
                }
                Write-Host ""
                Write-Host "  Restore finished. The wizard will only fill what's missing." -ForegroundColor Green
            }
        }
    } else {
        Write-Host "  No backup drive detected - continuing with a fresh setup."
        Write-Host "  (Have one? Plug it in, then: $($pyR.Label) `"$backupTool`" --restore)"
    }
} else {
    Write-Host "  Skipped (needs Python + scripts\backup-brain.py)."
}

# --- Step 7: First-run wizard ---
$wizard = Join-Path $RepoRoot "scripts\first-run.py"
$wizardArgs = @($wizard)
$wizardFlagsShown = ""
if ($NonInteractive) {
    $wizardArgs += "--non-interactive"
    $wizardFlagsShown += " --non-interactive"
}
if ($AnswersPath) {
    $wizardArgs += @("--answers", $AnswersPath)
    $wizardFlagsShown += " --answers `"$AnswersPath`""
}
if ($SkipFirstRun) {
    $label = if ($pyR) { $pyR.Label } else { "python" }
    Write-Host ""
    Write-Host "Skipping first-run wizard per -SkipFirstRun. Run later with:" -ForegroundColor Yellow
    Write-Host "    $label `"$wizard`"$wizardFlagsShown"
    Exit-Install 0
}
Write-Host ""
Write-Host "Step 7 - Hand off to first-run wizard" -ForegroundColor Green
$py = Get-InstallPython
if (-not $py) {
    Write-Host "  No Python 3 found - can't run the wizard. Install Python and re-run install.ps1." -ForegroundColor Red
    exit 1
}
if (-not (Test-PythonNewEnough $py)) {
    Write-Host "  $($py.Raw) via '$($py.Label)' is older than 3.10 - can't run the wizard. Install Python 3.10+ and re-run install.ps1." -ForegroundColor Red
    exit 1
}
if (-not (Test-Path $wizard)) {
    Write-Host "  Wizard not found at $wizard" -ForegroundColor Red
    exit 1
}
Write-Host ""
if ($DryRun) {
    $shownPy = if ($dryVenv) { "& `"$CharonVenvPy`"" } else { $py.Label }
    Write-Host "  [dry-run] would run: $shownPy `"$wizard`"$wizardFlagsShown"
    Exit-Install 0
}
# Script scope, not a function, so the wizard talks to the console directly.
$runArgs = @($py.Prefix | Where-Object { $_ }) + $wizardArgs
$prevEap = $ErrorActionPreference
$ErrorActionPreference = "Continue"
$wizardRc = 1
try { & $py.Command @runArgs; $wizardRc = $LASTEXITCODE } catch { $wizardRc = 1 }
finally { $ErrorActionPreference = $prevEap }
if ($null -eq $wizardRc) { $wizardRc = 1 }
if ($wizardRc -ne 0) {
    if ($NonInteractive) {
        Write-Loud @(
            "The first-run wizard stopped (exit $wizardRc): your profile is not set.",
            "Non-interactive, it cannot ask, so a required answer was missing or invalid.",
            "Give the answers in a file:  .\install.ps1 -NonInteractive -AnswersFile FILE",
            "or run the wizard yourself:  $($py.Label) `"$wizard`""
        )
    } else {
        Write-Host "  The first-run wizard stopped (exit $wizardRc). Run it again with:" -ForegroundColor Yellow
        Write-Host "    $($py.Label) `"$wizard`""
    }
}
Exit-Install $wizardRc
