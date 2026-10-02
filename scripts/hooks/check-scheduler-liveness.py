#!/usr/bin/env python3
"""
SessionStart hook: detect scheduled automation that has STOPPED RUNNING — or that
starts and never finishes.

Why this exists: most harness detectors check whether an *output is stale* (a TODO
that's old, a re-auth flag present). None of them ask "did the job execute at all?".
On the reference deployment, most scheduled tasks silently stopped running for up to
12 days — and the self-healing watchdog could not report it, because the watchdog is
itself a scheduled task. A watchdog scheduled by the mechanism that failed cannot
detect that mechanism failing.

So this runs as a SessionStart hook, NOT as a scheduled task, and judges liveness by
the mtime of each job's own log/output — the ground truth for "did real work happen"
— rather than by the scheduler's own state.

SECOND CHECK — COMPLETION. Liveness by mtime answers "did it run?" but not "did it
finish?". A job killed partway (closing a visible console sends 0xC000013A, which
writes nothing) still updates its log mtime. **Silence is not success.** So each job
that prints a start marker and a finish marker is also checked: if the most recent
start has no finish after it, the last run died partway.

THIRD CHECK — OFFLINE BACKUP (opt-in). Judged by `last_success` inside
`state/last-brain-backup.json`, never by log mtime: the backup log is written on every
attempt, including ones that found no drive, so mtime would read healthy while no
backup had happened for months.

Configuration: `scripts/hooks/scheduler-liveness-config.json` — the list of jobs to
watch. Ships watching Charon's own scheduled job (the capture pipeline, skipped
silently if it isn't installed). Add your own jobs there. Path placeholders:
  {repo}     this Charon checkout
  {vault}    your vault (HARNESS_VAULT_ROOT)
  {capture}  the capture-pipeline install (HARNESS_CAPTURE_ROOT, default ~/capture-pipeline)

Read-only. Silent when everything is healthy. Never raises: a liveness-check failure
must never block session start.
"""
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO = Path(os.environ.get("CLAUDE_PROJECT_DIR") or Path(__file__).resolve().parents[2])
CONFIG = Path(__file__).resolve().parent / "scheduler-liveness-config.json"

# Read only the tail: busy logs grow. 256KB comfortably spans several runs, so the
# most recent start/finish pair is always inside the window.
TAIL_BYTES = 256 * 1024


def _roots() -> dict:
    """Placeholder values. Falls back to sensible defaults if harness_paths is absent."""
    roots = {"repo": str(REPO), "vault": str(REPO),
             "capture": str(Path.home() / "capture-pipeline")}
    try:
        sys.path.insert(0, str(REPO / "scripts"))
        from lib.harness_paths import vault_root, capture_pipeline_root  # noqa: E402
        roots["vault"] = str(vault_root())
        roots["capture"] = str(capture_pipeline_root())
    except Exception:
        pass
    return roots


def _expand(value: str, roots: dict) -> str:
    out = str(value or "")
    for k, v in roots.items():
        out = out.replace("{" + k + "}", v)
    return out


def load_config(roots: dict):
    """Returns (jobs, backup). A missing or unreadable config watches nothing."""
    try:
        data = json.loads(CONFIG.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [], None
    fire_key = "fire_windows" if os.name == "nt" else "fire_posix"
    jobs = []
    for j in data.get("jobs") or []:
        if not isinstance(j, dict) or not j.get("label") or not j.get("target"):
            continue
        absent = j.get("skip_if_absent")
        if absent and not Path(_expand(absent, roots)).exists():
            continue  # not installed here — not a finding
        jobs.append({
            "label": str(j["label"]),
            "target": Path(_expand(j["target"], roots)),
            "overdue_hours": float(j.get("overdue_hours") or 36),
            "start": j.get("start_marker") or "",
            "finish": j.get("finish_marker") or "",
            "fire": _expand(j.get(fire_key) or j.get("fire") or "", roots),
        })
    backup = data.get("backup") or {}
    if backup.get("enabled"):
        backup = {
            "status": Path(_expand(backup.get("status_file") or "{repo}/state/last-brain-backup.json", roots)),
            "overdue_days": float(backup.get("overdue_days") or 14),
            "fire": _expand(backup.get("fire") or "python scripts/backup-brain.py", roots),
        }
    else:
        backup = None
    return jobs, backup


def backup_finding(now: datetime, backup):
    """Return a human-readable overdue message for the offline backup, or None."""
    if not backup:
        return None
    status = backup["status"]
    if not status.exists():
        return "**never run** — no status file yet"
    try:
        data = json.loads(status.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return "status file unreadable"
    last_success = data.get("last_success")
    if not last_success:
        attempted = data.get("last_attempt_result") or "unknown"
        return f"**no successful backup ever** (last attempt: {attempted})"
    try:
        dt = datetime.fromisoformat(last_success)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return "last_success timestamp unparseable"
    days = (now - dt).total_seconds() / 86400
    if days > backup["overdue_days"]:
        attempted = data.get("last_attempt_result") or "unknown"
        return (
            f"last successful backup **{days:.0f} days ago** "
            f"(most recent attempt: {attempted}) — plug the drive in"
        )
    return None


def incomplete_run(log: Path, start_marker: str, finish_marker: str):
    """Return the last start line if the most recent run never finished, else None.

    Compares byte positions rather than counting occurrences: a job that fails
    intermittently would still show a finish SOMEWHERE, so only the ordering of the
    LAST start against the LAST finish tells us about the most recent run.

    RULES for a job's markers: the finish marker must print on EVERY exit path
    (a failed-but-reported run is COMPLETE; only a killed run should look
    incomplete), and the start marker must not be a substring of the finish marker.
    """
    if not start_marker or not finish_marker:
        return None
    try:
        size = log.stat().st_size
        with log.open("rb") as fh:
            if size > TAIL_BYTES:
                fh.seek(size - TAIL_BYTES)
            text = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return None

    start_idx = text.rfind(start_marker)
    if start_idx == -1:
        return None  # no start in window — cannot judge, stay silent
    if text.rfind(finish_marker) > start_idx:
        return None  # finished after it started: healthy

    line_end = text.find("\n", start_idx)
    line = text[start_idx:line_end if line_end != -1 else len(text)]
    return line.strip()


def newest_mtime(target: Path):
    """Return the newest mtime under target (file → its own; dir → newest descendant)."""
    try:
        if target.is_dir():
            stamps = [c.stat().st_mtime for c in target.rglob("*") if c.is_file()]
            return max(stamps) if stamps else None
        if target.is_file():
            return target.stat().st_mtime
    except OSError:
        return None
    return None


def humanise(hours: float) -> str:
    if hours < 48:
        return f"{hours:.0f} hours"
    return f"{hours / 24:.1f} days"


def main() -> int:
    now = datetime.now(timezone.utc)
    jobs, backup = load_config(_roots())
    overdue, missing, incomplete = [], [], []

    for j in jobs:
        mtime = newest_mtime(j["target"])
        if mtime is None:
            missing.append(j)
            continue
        silent_h = (now - datetime.fromtimestamp(mtime, tz=timezone.utc)).total_seconds() / 3600
        if silent_h > j["overdue_hours"]:
            overdue.append((j, silent_h, mtime))
        if j["target"].is_file():
            line = incomplete_run(j["target"], j["start"], j["finish"])
            if line:
                incomplete.append((j, line))

    backup_msg = backup_finding(now, backup)

    if not overdue and not missing and not backup_msg and not incomplete:
        return 0

    # Header must not assert "stopped producing output" when the only finding is an
    # incomplete run — those jobs ARE producing output; they just die partway.
    out = ["## ⚠️ Scheduled automation needs attention\n"]

    if incomplete:
        out.append(
            "### \U0001f6d1 Started but never FINISHED\n\n"
            "These wrote to their log (so they look alive) but the most recent run "
            "never reached its completion marker — it was killed partway, and every "
            "step after the kill silently did not run. **Silence is not success.** A "
            "console-close kill (`0xC000013A`) writes nothing at all.\n"
        )
        out.append("| Automation | Last run that never completed |")
        out.append("|---|---|")
        for j, line in incomplete:
            out.append(f"| {j['label']} | `{line}` |")
        out.append("")

    if backup_msg:
        fire = backup["fire"]
        out.append(
            f"### \U0001f512 Offline brain backup overdue\n\n"
            f"{backup_msg}.\n\n"
            f"Your memory store and session history live outside the vault — an "
            f"unbacked machine loss takes the harness's memory with it.\n\n"
            f"```\n{fire}\n```\n"
        )

    if overdue:
        out.append(
            "### ⏰ Stopped producing output\n\n"
            "Judged by each job's own log/output mtime, so this means *no work "
            "happened* — not merely that a result looks stale.\n"
        )
        out.append("| Automation | Silent for | Expected within | Last output |")
        out.append("|---|---|---|---|")
        for j, silent_h, mtime in sorted(overdue, key=lambda r: r[1], reverse=True):
            last = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            out.append(
                f"| {j['label']} | **{humanise(silent_h)}** | {humanise(j['overdue_hours'])} | {last} |"
            )
        out.append("")

    if missing:
        out.append("**No output has ever been found for:**\n")
        for j in missing:
            out.append(f"- {j['label']} — `{j['target']}`")
        out.append("")

    # Dedupe by label: a job can be BOTH overdue and incomplete, and printing its
    # fire command twice makes the block look like two separate problems.
    fires, seen = [], set()
    for j in [r[0] for r in overdue] + missing + [r[0] for r in incomplete]:
        if j["label"] not in seen and j["fire"]:
            seen.add(j["label"])
            fires.append((j["label"], j["fire"]))

    if fires:
        out.append("**Fire manually (or ask Claude to):**\n")
        out.append("```")
        for label, fire in fires:
            out.append(f"# {label}\n{fire}")
        out.append("```\n")
    # Only meaningful when jobs stopped RUNNING. An incomplete run points at the job
    # (or a kill), not at the scheduler, so don't misdirect on a completion-only finding.
    if overdue or missing:
        out.append(
            "If several stopped at once, suspect the scheduler rather than the jobs — "
            "on Windows check the task's \"Start the task as soon as possible after a "
            "scheduled start is missed\" setting and its battery conditions."
        )

    print("\n".join(out))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # never block session start
        sys.stderr.write(f"check-scheduler-liveness.py: {exc}\n")
        sys.exit(0)
