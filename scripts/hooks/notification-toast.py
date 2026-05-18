#!/usr/bin/env python3
"""
Notification hook: show a desktop notification when Claude Code emits one
(e.g. "Claude needs your input", long-running task complete, idle prompt).

Currently Windows-only — uses the Windows-native ToastNotificationManager
via PowerShell. On Linux/macOS this hook is a no-op (still logs to file).
If you're on Linux/macOS and want desktop notifications, swap the
`show_toast` body for `notify-send` (Linux) or `osascript` (macOS).

Also writes a one-line entry to scripts/hooks/notification.log so missed
toasts are recoverable.
"""
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

LOG_PATH = Path(__file__).resolve().parent / "notification.log"


def write_log(msg: str) -> None:
    try:
        with LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"{datetime.now().isoformat(timespec='seconds')}\t{msg}\n")
    except Exception:
        pass


def show_toast(title: str, message: str) -> None:
    # Windows-only path. Quietly no-op on other platforms.
    if sys.platform != "win32":
        return
    safe_title = (title or "Claude Code").replace("'", "''")
    safe_msg = (message or "").replace("'", "''")
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
        "::CreateToastNotifier('ClaudeCode').Show($toast)"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
            timeout=5,
            capture_output=True,
        )
    except Exception:
        pass


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    msg = data.get("message", "Claude needs your attention")
    title = data.get("title", "Claude Code")
    write_log(f"{title} | {msg}")
    show_toast(title, msg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
