#!/usr/bin/env python3
"""
SessionStart hook: surface a STALE TODO.md (and un-triaged captures) at the top
of the session, so a failed or skipped overnight TODO regeneration can never
silently swallow an inbound action item.

Why this exists: a scheduled TODO-regeneration step can fail quietly (budget
cap, wall-clock timeout, a hung headless run). When it does, TODO.md simply
stops updating and new captures never make it onto your front-of-mind list —
with no signal that anything went wrong. on-error.py logs + (on Windows) toasts
on failure, but a notification fired while you're away is easy to miss and can't
count un-triaged work. This hook is the durable, session-visible safety net.

Design:
  - Freshness is computed LIVE from TODO.md's `generated:` frontmatter date, so
    the net fires regardless of WHY regen didn't run — even if the failing
    process died before writing any flag.
  - The optional TODO-REGEN-FAILED.flag (written by on-error.py when a
    TODO-regeneration runner exits non-zero) only enriches the banner with the
    failure reason; the hook self-cleans it once TODO is fresh again.
  - The (bounded) un-triaged-capture scan runs ONLY when TODO is already stale,
    so normal fresh mornings cost one small file read and return silently.

Output: prints additionalContext markdown to stdout (consumed by Claude Code).
Silent when TODO is fresh. Never raises (a surfacing failure must not block
session start).
"""
import json
import sys
from datetime import date, datetime
from pathlib import Path

# Force UTF-8 stdout on Windows so emoji render cleanly (cp1252 raises on '⚠️').
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
try:
    from lib.harness_paths import vault_root, capture_pipeline_root
except Exception:
    # Fail-silent fallback: assume the vault is the current working directory
    # and the capture pipeline lives at $HOME/capture-pipeline.
    def vault_root() -> Path:
        return Path.cwd()

    def capture_pipeline_root() -> Path:
        return Path.home() / "capture-pipeline"


FLAG_NAME = "TODO-REGEN-FAILED.flag"
# Cap the capture scan so a pathological tree can never stall session start.
_SCAN_FILE_CAP = 8000
_COUNT_DISPLAY_CAP = 500


def _parse_generated_date(todo_path: Path):
    """Return the `generated:` date from TODO.md frontmatter, or None."""
    try:
        with todo_path.open("r", encoding="utf-8", errors="replace") as f:
            # generated: is in the frontmatter block at the very top.
            for _ in range(15):
                line = f.readline()
                if not line:
                    break
                stripped = line.strip()
                if stripped.startswith("generated:"):
                    value = stripped.split(":", 1)[1].strip().strip('"').strip("'")
                    return date.fromisoformat(value[:10])
    except Exception:
        return None
    return None


def _count_untriaged_captures(captured_root: Path, since_dt: datetime) -> str:
    """Count *.md captures modified after since_dt. Bounded + fail-safe.

    Only called on the stale path, so its cost never touches fresh mornings.
    Returns a display string like '12' or '500+' or '' if it couldn't scan.
    """
    if not captured_root.exists():
        return ""
    since_ts = since_dt.timestamp()
    count = 0
    scanned = 0
    try:
        for p in captured_root.rglob("*.md"):
            scanned += 1
            if scanned > _SCAN_FILE_CAP:
                return f"{count}+ (scan capped)"
            try:
                if p.stat().st_mtime > since_ts:
                    count += 1
                    if count >= _COUNT_DISPLAY_CAP:
                        return f"{_COUNT_DISPLAY_CAP}+"
            except OSError:
                continue
    except Exception:
        return str(count) if count else ""
    return str(count) if count else ""


def _read_flag(flag_path: Path):
    if not flag_path.exists():
        return None
    try:
        return json.loads(flag_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"reason": "(flag present but unreadable)"}


def main() -> int:
    vault = vault_root()
    todo_path = vault / "TODO.md"
    flag_path = capture_pipeline_root() / "state" / FLAG_NAME

    # No TODO.md at all — nothing to judge; stay silent (a fresh install has no
    # TODO yet, and it's not this hook's job to nag about that).
    if not todo_path.exists():
        return 0

    generated = _parse_generated_date(todo_path)
    today = datetime.now().date()

    flag = _read_flag(flag_path)

    # Fresh (generated today or somehow ahead) → self-clean any stale flag, stay silent.
    if generated is not None and generated >= today:
        if flag is not None:
            try:
                flag_path.unlink()
            except OSError:
                pass
        return 0

    stale_days = (today - generated).days if generated is not None else None

    # Legitimate pre-scheduled-run window: TODO from yesterday, early morning, no
    # recorded failure → the scheduled run simply hasn't happened yet. Stay quiet.
    now = datetime.now()
    if stale_days == 1 and now.hour < 8 and flag is None:
        return 0

    # --- Stale path: build the banner (capture scan runs only here) ---
    if generated is not None:
        since_dt = datetime.combine(generated, datetime.min.time())
        stale_desc = f"generated **{generated.isoformat()}** ({stale_days} day(s) ago)"
    else:
        # Couldn't parse the date — treat as stale; scan from epoch so nothing is missed.
        since_dt = datetime.fromtimestamp(0)
        stale_desc = "generated date **unreadable** in frontmatter"

    untriaged = _count_untriaged_captures(vault / "00-Inbox" / "_captured", since_dt)

    lines = [
        "## ⚠️ TODO.md looks STALE — don't trust it as complete",
        "",
        f"`TODO.md` is {stale_desc}. The overnight regeneration may have failed or "
        "not run, so new action items may be missing from your front-of-mind list.",
    ]

    if untriaged:
        lines.append("")
        lines.append(
            f"**~{untriaged} captured item(s)** have landed since TODO was last "
            "generated and may be un-triaged."
        )

    if flag is not None:
        reason = flag.get("reason") or flag.get("runner") or "(no reason recorded)"
        ts = flag.get("ts", "unknown")
        exit_code = flag.get("exit_code")
        detail = f"`{flag.get('runner', 'regen')}`"
        if exit_code is not None:
            detail += f" exited {exit_code}"
        lines.append("")
        lines.append(f"**Recorded failure:** {detail} at {ts} — {reason}")

    lines.append("")
    lines.append(
        "**Recover:** run `/refresh-todo` to rebuild from current captures. "
        "This banner clears automatically once TODO.md regenerates successfully."
    )

    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        # Never block session start over a freshness-surfacing failure.
        sys.stderr.write(f"check-todo-freshness.py: {exc}\n")
        sys.exit(0)
