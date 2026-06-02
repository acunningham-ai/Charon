#!/usr/bin/env python3
"""
Cross-platform safe JSONL append with file locking.

Used by `_verdict.py` and `_telemetry.py` — both append to JSONL audit logs
from hooks that may be invoked by concurrent Claude Code sessions. Without
locking, parallel appends on Windows can interleave bytes and corrupt lines.

Strategy:
  - Windows: msvcrt.locking with non-blocking lock + short retry loop
  - POSIX: fcntl.flock LOCK_EX
  - Either: file handle close releases any held lock as a safety net

Fail-silent: any IO or lock error is swallowed. Audit logging must never
break a hook. After exhausting retries the line is written without a lock
rather than dropped — interleave risk is preferred over data loss.
"""
from __future__ import annotations

import platform
import time
from pathlib import Path

_IS_WINDOWS = platform.system() == "Windows"

if _IS_WINDOWS:
    import msvcrt  # type: ignore
else:
    try:
        import fcntl  # type: ignore
    except ImportError:
        fcntl = None  # type: ignore

LOCK_RETRY_COUNT = 50           # 50 * 10ms = ~0.5s of total wait
LOCK_RETRY_SLEEP_SECONDS = 0.01


def _lock_windows(fileno: int) -> bool:
    for _ in range(LOCK_RETRY_COUNT):
        try:
            msvcrt.locking(fileno, msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            time.sleep(LOCK_RETRY_SLEEP_SECONDS)
    return False


def _unlock_windows(fileno: int) -> None:
    try:
        msvcrt.locking(fileno, msvcrt.LK_UNLCK, 1)
    except Exception:
        pass


def safe_append_line(path: Path, line: str) -> bool:
    """Append `line` to `path` with cross-platform locking.

    Creates parent directories as needed. Best-effort lock acquisition;
    if lock can't be acquired within ~0.5s, falls through to an unlocked
    write rather than dropping the line. Returns True on success, False
    on hard IO failure.
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as f:
            if _IS_WINDOWS:
                got_lock = _lock_windows(f.fileno())
                try:
                    f.write(line)
                finally:
                    if got_lock:
                        _unlock_windows(f.fileno())
            elif fcntl is not None:
                try:
                    fcntl.flock(f.fileno(), fcntl.LOCK_EX)
                    f.write(line)
                finally:
                    try:
                        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
                    except Exception:
                        pass
            else:
                f.write(line)
        return True
    except Exception:
        return False
