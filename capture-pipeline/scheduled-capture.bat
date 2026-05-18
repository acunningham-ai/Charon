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

REM --non-interactive: on silent-auth failure, fetch-mail.mjs writes a
REM REAUTH-NEEDED.flag and exits with code 2 instead of hanging on a
REM device-code prompt nobody is there to answer.
node fetch-mail.mjs all --non-interactive >> "%LOG%" 2>&1
set EXITCODE=%ERRORLEVEL%

if %EXITCODE% EQU 2 (
  echo *** Pipeline halted: re-auth required. Flag file written. *** >> "%LOG%"
  REM Windows toast via built-in WinRT APIs — no third-party install required.
  powershell -NoProfile -Command "[void][Windows.UI.Notifications.ToastNotificationManager,Windows.UI.Notifications,ContentType=WindowsRuntime];[void][Windows.UI.Notifications.ToastNotification,Windows.UI.Notifications,ContentType=WindowsRuntime];[void][Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom.XmlDocument,ContentType=WindowsRuntime];$x=New-Object Windows.Data.Xml.Dom.XmlDocument;$x.LoadXml('<toast><visual><binding template=\"ToastGeneric\"><text>Charon capture: re-auth required</text><text>Run: node fetch-mail.mjs auth</text></binding></visual></toast>');[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Charon').Show([Windows.UI.Notifications.ToastNotification]::new($x))" 2>nul
)

echo Run finished: %DATE% %TIME% (exit=%EXITCODE%) >> "%LOG%"
echo. >> "%LOG%"

exit /b %EXITCODE%
