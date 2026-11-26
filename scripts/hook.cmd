@echo off
rem scripts\hook.cmd: the cmd.exe twin of scripts/hook (POSIX sh). Same contract:
rem
rem   hook.cmd <repo-relative .py path> [args...]
rem
rem   - the repo root is this file's folder's parent, never the working directory;
rem   - first tries Charon's private virtual environment,
rem     %USERPROFILE%\.charon-venv\Scripts\python.exe (install.ps1 makes it when
rem     the system Python is externally managed, PEP 668). It is used only if,
rem     run with -S, it PRINTS a Python 3 marker (exiting 0 is not enough), so a
rem     venv folder or python.exe that is a link or junction to something that
rem     is not a Python 3 interpreter (or to nothing) is skipped; a link to a
rem     real interpreter is used;
rem   - then tries python3, then python, then "py -3" on PATH, and accepts Python 3
rem     only (each candidate is probed, which also skips the Windows Store python3
rem     stub);
rem   - runs <repo>\<script> with the remaining args; stdin passes through and the
rem     script's exit code is returned;
rem   - no Python 3 found: one line on stderr naming the fix, exit 2 (a PreToolUse
rem     gate then BLOCKS: fails closed);
rem   - a script path that is absolute, holds "..", or is not .py is refused, exit 2;
rem   - never writes any file.
rem
rem Claude Code settings use the sh form on every platform (it runs hook commands
rem through Git Bash on Windows). This file is for callers that only have cmd.exe.
rem
rem Written with no labels or goto, so it parses the same with LF or CRLF endings.
rem Limits of cmd argument handling: extra args may not contain * ? = , ; or empty
rem strings. Charon's own hook and server commands pass none of those.
setlocal EnableExtensions DisableDelayedExpansion

set "HOOK_SCRIPT=%~1"
if not defined HOOK_SCRIPT (
  echo charon hook: usage: hook.cmd ^<repo-relative .py path^> [args...] 1>&2
  exit /b 2
)

set "HOOK_BAD="
if not "%HOOK_SCRIPT:..=%"=="%HOOK_SCRIPT%" set "HOOK_BAD=1"
if not "%HOOK_SCRIPT::=%"=="%HOOK_SCRIPT%" set "HOOK_BAD=1"
if "%HOOK_SCRIPT:~0,1%"=="\" set "HOOK_BAD=1"
if "%HOOK_SCRIPT:~0,1%"=="/" set "HOOK_BAD=1"
if /i not "%HOOK_SCRIPT:~-3%"==".py" set "HOOK_BAD=1"
if defined HOOK_BAD (
  echo charon hook: refused script path: give a repo-relative .py path with no .. steps 1>&2
  exit /b 2
)

for %%I in ("%~dp0..") do set "HOOK_ROOT=%%~fI"

set "HOOK_ARGS="
set "HOOK_FIRST=1"
for %%A in (%*) do (
  if defined HOOK_FIRST (set "HOOK_FIRST=") else call set HOOK_ARGS=%%HOOK_ARGS%% %%A
)

set "HOOK_PY="
set "HOOK_FLAG="
set "HOOK_VENV_PY="
if defined USERPROFILE set "HOOK_VENV_PY=%USERPROFILE%\.charon-venv\Scripts\python.exe"
if defined HOOK_VENV_PY if exist "%HOOK_VENV_PY%" for /f "usebackq delims=" %%O in (`call "%HOOK_VENV_PY%" -S -c "import sys; sys.stdout.write('charon-py3' if sys.version_info[0] == 3 else '')" ^<nul 2^>nul`) do if "%%O"=="charon-py3" set "HOOK_PY=%HOOK_VENV_PY%"
for %%P in (python3.exe python.exe) do if not defined HOOK_PY if not "%%~$PATH:P"=="" (
  "%%~$PATH:P" -S -c "import sys; sys.exit(0 if sys.version_info[0] == 3 else 1)" <nul >nul 2>&1 && set "HOOK_PY=%%~$PATH:P"
)
if not defined HOOK_PY for %%P in (py.exe) do if not "%%~$PATH:P"=="" (
  "%%~$PATH:P" -3 -S -c "import sys; sys.exit(0 if sys.version_info[0] == 3 else 1)" <nul >nul 2>&1 && set "HOOK_PY=%%~$PATH:P" && set "HOOK_FLAG=-3"
)

if not defined HOOK_PY (
  echo charon hook: no Python 3 found ^(tried python3, python, py -3^). Install Python 3 so one of those is on PATH, then restart Claude Code. 1>&2
  exit /b 2
)

"%HOOK_PY%" %HOOK_FLAG% "%HOOK_ROOT%\%HOOK_SCRIPT%" %HOOK_ARGS%
exit /b %ERRORLEVEL%
