@echo off
REM Charon scheduled capture wrapper (Windows).
REM Register with Task Scheduler — see EMAIL-PROVIDER-SETUP.md §Scheduling.
REM
REM Per task feedback_no_unattended_local_runs: prefer "run only when user is
REM logged on" + "Interactive only" — do NOT use stored credentials, do NOT
REM "run whether user is logged on or not", do NOT "wake the computer to run".

setlocal

REM Resolve script dir so the task can be registered from anywhere
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

set "LOG=%SCRIPT_DIR%state\scheduled-run.log"
if not exist "%SCRIPT_DIR%state" mkdir "%SCRIPT_DIR%state"

echo ========================================== >> "%LOG%"
echo Run started: %DATE% %TIME% >> "%LOG%"
echo ========================================== >> "%LOG%"

node fetch-mail.mjs all >> "%LOG%" 2>&1
set EXITCODE=%ERRORLEVEL%

echo Run finished: %DATE% %TIME% (exit=%EXITCODE%) >> "%LOG%"
echo. >> "%LOG%"

exit /b %EXITCODE%
