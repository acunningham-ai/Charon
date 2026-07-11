#!/usr/bin/env python3
"""
on-error.py — generic non-zero-exit handler for scheduled automation.

Called from each capture-pipeline / scheduled runner when ERRORLEVEL is
non-zero. Two outputs:
  1. Append a JSONL entry to capture-pipeline/state/error-log.jsonl
  2. Show a desktop notification surfacing the failure (Windows-only;
     no-op on other platforms — see notification-toast.py for the same
     pattern).

Usage:
  python on-error.py <runner-name> <exit-code> [<log-path>]

  runner-name: short name (typically %~n0 from the calling bat)
  exit-code:   numeric exit code (typically %ERRORLEVEL% or a captured %RC%)
  log-path:    optional; if supplied, last 10 lines included in JSONL entry

Failures inside this handler are silent (always returns 0) — must never
cascade into making a failing automation fail harder.
"""
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from lib.harness_paths import capture_pipeline_root  # noqa: E402

ERROR_LOG = capture_pipeline_root() / "state" / "error-log.jsonl"

# When a TODO-regeneration runner fails, also drop a durable flag so the
# SessionStart hook (check-todo-freshness.py) can name the cause — belt-and-braces
# alongside that hook's live staleness check. Matched by substring so it fires
# for whatever the user names their TODO-regen runner.
TODO_FLAG = capture_pipeline_root() / "state" / "TODO-REGEN-FAILED.flag"


def append_jsonl(entry: dict) -> None:
    try:
        ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
        with ERROR_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass


def tail_log(log_path: str, lines: int = 10) -> str:
    if not log_path:
        return ""
    try:
        p = Path(log_path)
        if not p.is_absolute():
            p = capture_pipeline_root() / log_path
        if not p.exists():
            return ""
        with p.open("r", encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-lines:]).rstrip()
    except Exception:
        return ""


def show_toast(runner_name: str, exit_code: str) -> None:
    if sys.platform != "win32":
        return
    title = "Harness automation failed"
    message = f"{runner_name} exited {exit_code}. See state\\error-log.jsonl."
    safe_title = title.replace("'", "''")
    safe_msg = message.replace("'", "''")
    ps = (
        "[void][Windows.UI.Notifications.ToastNotificationManager,"
        "Windows.UI.Notifications,ContentType=WindowsRuntime];"
        "[void][Windows.UI.Notifications.ToastNotification,"
        "Windows.UI.Notifications,ContentType=WindowsRuntime];"
        "[void][Windows.Data.Xml.Dom.XmlDocument,"
        "Windows.Data.Xml.Dom.XmlDocument,ContentType=WindowsRuntime];"
        f"$xml = '<toast><visual><binding template=\"ToastText02\">"
        f"<text id=\"1\">{safe_title}</text>"
        f"<text id=\"2\">{safe_msg}</text>"
        f"</binding></visual></toast>';"
        "$doc = New-Object Windows.Data.Xml.Dom.XmlDocument;"
        "$doc.LoadXml($xml);"
        "$toast = [Windows.UI.Notifications.ToastNotification]::new($doc);"
        "[Windows.UI.Notifications.ToastNotificationManager]"
        "::CreateToastNotifier('HarnessOnError').Show($toast)"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
            timeout=5, capture_output=True,
        )
    except Exception:
        pass


def write_todo_flag(runner_name: str, exit_code: str, tail: str) -> None:
    """Drop the TODO-REGEN-FAILED flag so check-todo-freshness.py can name the
    cause. Fail-safe: a flag-write error must not make the handler fail harder."""
    reason = "TODO regeneration exited non-zero"
    if str(exit_code) == "124":
        reason = "TODO regeneration killed on wall-clock timeout"
    elif tail and "budget" in tail.lower():
        reason = "TODO regeneration exceeded the USD budget cap"
    payload = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "runner": runner_name,
        "exit_code": exit_code,
        "reason": reason,
    }
    try:
        TODO_FLAG.parent.mkdir(parents=True, exist_ok=True)
        TODO_FLAG.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def main() -> int:
    if len(sys.argv) < 3:
        return 0
    runner_name = sys.argv[1]
    exit_code = sys.argv[2]
    log_path = sys.argv[3] if len(sys.argv) >= 4 else ""
    tail = tail_log(log_path)
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "runner": runner_name,
        "exit_code": exit_code,
        "tail": tail,
    }
    append_jsonl(entry)
    show_toast(runner_name, exit_code)
    # A runner whose name mentions "todo" is a TODO-regeneration step; record the
    # failure durably so the freshness hook can name it at next session start.
    if "todo" in runner_name.lower():
        write_todo_flag(runner_name, exit_code, tail)
    return 0


if __name__ == "__main__":
    sys.exit(main())
