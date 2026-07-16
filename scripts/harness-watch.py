#!/usr/bin/env python3
"""
Harness watch — read-only self-healing observability for your harness.

Walks the harness (discovery over enumeration), runs a set of health
detectors, emits a structured verdict per finding (allow / observe / ask /
deny via the verdict layer), writes a dated vault note, and — on scheduled
runs — toasts on any declared ask/deny.

The differentiated core is the **coverage self-report**: alongside the
findings it prints what it inventoried, what it has NO detector for (blind
spots), and which detectors can still prove they fire (per-detector
selftests). A harness that names the limits of its own vision instead of
going quietly blind.

Ships OBSERVE-ONLY. Every finding is logged, nothing is enforced and nothing
is auto-fixed — surfacing an issue plus ranked fix options is the whole job;
applying a fix is always a separate, human-approved step. Run your own shadow
window, then use `/harness-watch-review` to promote a signal observe->ask
(populate PROMOTED_RULES below once you've reviewed it).

Usage:
  python scripts/harness-watch.py --doctor          # scan everything now, print inline
  python scripts/harness-watch.py --phase post       # scheduled post-run (writes note + toast)
  python scripts/harness-watch.py --dry-run          # print findings, write nothing

Exit code is always 0 — this is an observer, not a gate. A detector that
raises degrades to an observe entry; it never crashes the run.

Env configuration (all optional — sensible defaults):
  HARNESS_VAULT_ROOT       your second-brain root (default: cwd)
  HARNESS_CAPTURE_ROOT     capture-pipeline install dir (default: ~/capture-pipeline)
  HARNESS_TASK_PREFIX      scheduled-task name prefix to watch (default: "Charon")
  HARNESS_CAPTURE_MARKERS  comma-separated cmdline markers for the zombie-process
                           check (default: capture-pipeline entry points)

See:
  - .claude/commands/harness-doctor.md        (on-demand scan)
  - .claude/commands/harness-watch-review.md  (shadow-window promotion call)
  - scripts/hooks/_verdict.py                 (verdict emission)
  - .claude/rules/verdict-vocabulary.md       (the allow/observe/ask/deny schema)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Callable, Optional

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))
try:
    from lib.harness_paths import vault_root, capture_pipeline_root  # noqa: E402
except Exception:
    def vault_root() -> Path:  # type: ignore
        env = os.environ.get("HARNESS_VAULT_ROOT")
        return Path(env).resolve() if env else Path.cwd().resolve()

    def capture_pipeline_root() -> Path:  # type: ignore
        env = os.environ.get("HARNESS_CAPTURE_ROOT")
        return Path(env).resolve() if env else (Path.home() / "capture-pipeline").resolve()

# Verdict layer lives in scripts/hooks.
HOOKS_DIR = THIS_DIR / "hooks"
sys.path.insert(0, str(HOOKS_DIR))
try:
    from _verdict import emit_verdict, current_mode, MONITOR_MODE  # noqa: E402
except Exception:
    def emit_verdict(*args, **kwargs):  # type: ignore
        return kwargs.get("verdict", "allow")

    def current_mode():  # type: ignore
        return "production"

    MONITOR_MODE = "monitor"

HOOK_NAME = "harness-watch"

# Rules promoted OUT of shadow (observe -> enforcing) after clearing their own
# shadow window via /harness-watch-review. EMPTY by default: Charon ships
# observe-only, so every user runs their own fortnight and promotes the signals
# that proved clean on THEIR harness. To promote a rule, add its `rule` literal
# here (it then emits at full strength even under HARNESS_MODE=monitor).
#
# CO-CHANGE (anti-silent-rot): a string here MUST match a `rule` literal emitted
# by a judge below. Rename a rule id -> rename it here too, or membership
# silently misses and the "promoted" rule quietly reverts to shadow.
PROMOTED_RULES: set = set()

# --- Thresholds (tune against your own shadow window) -----------------

TOKEN_AGE_ASK_DAYS = 25
TOKEN_AGE_DENY_DAYS = 28
CAPTURE_STALE_HOURS = 36
TODO_STALE_HOURS = 6
ERROR_LOG_WINDOW_HOURS = 24
TASK_RUNNING_MAX_MIN = 60        # a watched task still 'Running' longer than this = likely zombie
ZOMBIE_PROC_MAX_HOURS = 1        # a capture-pipeline process alive longer than this = likely hung

# Task-scheduler LastTaskResult codes that are NOT failures: success + benign
# lifecycle states (ready/not-run/running/disabled/terminated). Anything else = a
# real non-zero exit worth surfacing.
BENIGN_TASK_RESULTS = {0, 267008, 267009, 267010, 267011, 267014}

# Scheduled-task name prefix to watch, and the cmdline markers that identify a
# capture-pipeline process for the zombie check — both env-overridable so this
# adapts to your install without editing code.
TASK_PREFIX = os.environ.get("HARNESS_TASK_PREFIX", "Charon")
ZOMBIE_CMD_MARKERS = tuple(
    m.strip() for m in os.environ.get(
        "HARNESS_CAPTURE_MARKERS", "fetch-graph,scheduled-capture,capture-pipeline"
    ).split(",") if m.strip()
)

# Self-flag suppression: the watch's OWN interactive tasks get 0x800710E0
# ("operator/administrator refused the request") when they miss a scheduled slot
# (machine asleep/logged-off) and fire late on wake — a benign lifecycle outcome,
# not a run failure (the wrapper never even starts). Don't let the watch alarm on
# its own missed catch-up. Scoped to the watch's own tasks + this exact code, so a
# real watch failure and any OTHER task's refusal still surface.
SELF_WATCH_TASKS = {f"{TASK_PREFIX} Harness Watch Pre", f"{TASK_PREFIX} Harness Watch Post"}
SCHED_REFUSED_MISSED = 0x800710E0  # 2147943648 — missed interactive slot, fired late, terminated

# --- Path helpers ------------------------------------------------------

def capture_state(name: str) -> Path:
    return capture_pipeline_root() / "state" / name


def vault_path(rel: str) -> Path:
    return vault_root() / rel


def _capture_configured() -> bool:
    """Capture-pipeline detectors only make sense when the pipeline is installed.
    On a fresh Charon without capture configured, a missing token-cache is NOT a
    fault — so gate those detectors on the state dir existing."""
    try:
        return (capture_pipeline_root() / "state").exists()
    except Exception:
        return False


def _mtime_age(path: Path) -> Optional[timedelta]:
    if not path.exists():
        return None
    return datetime.now(timezone.utc) - datetime.fromtimestamp(
        path.stat().st_mtime, tz=timezone.utc
    )


def _sanitize_runner(name) -> str:
    """Runner names come from an untrusted error log and flow into a finding's
    reason string + the vault-note body. Strip non-printable chars (newlines,
    control chars) and bound length so a crafted log entry can't inject markdown
    headings into the note."""
    s = "".join(ch for ch in str(name or "") if ch.isprintable())
    return s[:80]

# --- Signal checks ----------------------------------------------------
#
# Each check returns None (no issue), a dict, or a list[dict]. A finding dict:
#   rule:      stable identifier for the audit log
#   declared:  allow | observe | ask | deny
#   reason:    one-line human description
#   context:   structured dict for the vault note + audit log
#              (DO NOT put secrets / tokens / cred values here)

def check_token_age() -> Optional[dict]:
    if not _capture_configured():
        return None
    path = capture_state("token-cache.json")
    age = _mtime_age(path)
    age_days = None if age is None else age.total_seconds() / 86400
    return _judge_token_age(age_days, path.name)  # basename only — path not logged to the synced audit


def check_capture_freshness() -> Optional[dict]:
    if not _capture_configured():
        return None
    path = capture_state("captured.json")
    age = _mtime_age(path)
    age_hours = None if age is None else age.total_seconds() / 3600
    return _judge_capture_age(age_hours, path.name)  # basename only — path not logged to the synced audit


def check_todo_freshness(phase: str) -> Optional[dict]:
    # A stale TODO.md at the post-run check means a daily refresh automation
    # (e.g. the capture pipeline's morning update) didn't complete — only
    # meaningful when such an automation exists, so gate on capture configured.
    if phase != "post" or not _capture_configured():
        return None
    path = vault_path("TODO.md")
    age = _mtime_age(path)
    age_hours = None if age is None else age.total_seconds() / 3600
    return _judge_todo_age(age_hours, path.name)  # basename only — path not logged to the synced audit


def check_error_log_recent() -> Optional[dict]:
    """Surface recent capture-pipeline failures. device_code_expired is a deny
    (auth expiry breaks capture); any other recent failure surfaces as an ask."""
    if not _capture_configured():
        return None
    path = capture_state("error-log.jsonl")
    if not path.exists():
        return None
    try:
        size = path.stat().st_size
    except Exception:
        return None
    cutoff = datetime.now(timezone.utc) - timedelta(hours=ERROR_LOG_WINDOW_HOURS)
    device_code_hits = []
    other_failures = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as f:
            if size > _SAFE_READ_MAX_BYTES:
                # Bound the read — only the tail matters (recent entries are
                # appended last). Seek near the end, discard the partial line.
                f.seek(size - _SAFE_READ_MAX_BYTES)
                f.readline()
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except Exception:
                    continue
                ts = entry.get("ts", "")
                try:
                    when = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                except Exception:
                    continue
                if when < cutoff:
                    continue
                if "device_code_expired" in (entry.get("tail") or ""):
                    device_code_hits.append({"ts": ts, "runner": _sanitize_runner(entry.get("bat", ""))})
                else:
                    other_failures.append({"ts": ts, "runner": _sanitize_runner(entry.get("bat", ""))})
    except Exception:
        return None
    return _judge_error_log(device_code_hits, other_failures)


# --- Scheduled-task + process health (Windows-first) -------------------
# Each detector = a pure _judge() (selftested against synthetic fixtures, so it
# can never go structurally-dead unnoticed) + a PowerShell probe. On non-Windows
# both return None (the probe is Windows-only) rather than emit noise every run.

def _ps_json(ps: str):
    """Run a PowerShell command that emits ConvertTo-Json; return a list (or None
    on probe failure). Single-object JSON is wrapped into a one-element list."""
    try:
        r = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
            capture_output=True, encoding="utf-8", errors="replace", timeout=30,
        )
        out = (r.stdout or "").strip()
        if not out:
            return []
        data = json.loads(out)
        return data if isinstance(data, list) else [data]
    except Exception:
        return None  # probe failed — detector emits an observe, never crashes


def _parse_iso(s) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def _judge_scheduled_tasks(tasks, now: datetime) -> dict:
    """Pure: classify watched tasks into zombies (Running too long) + failed
    (non-benign LastTaskResult). `tasks` is a list of {name,state,result,last} or None."""
    if tasks is None:
        return {"probe_failed": True}
    zombies, failed = [], []
    for t in tasks:
        name = t.get("name", "?")
        state = (t.get("state") or "").lower()
        result = t.get("result")
        last = _parse_iso(t.get("last"))
        if state == "running" and last is not None and (now - last) > timedelta(minutes=TASK_RUNNING_MAX_MIN):
            zombies.append({"name": name, "running_min": round((now - last).total_seconds() / 60)})
        elif isinstance(result, (int, float)) and int(result) not in BENIGN_TASK_RESULTS:
            # Suppress the watch's own missed-catch-up refusal (see SCHED_REFUSED_MISSED).
            if name in SELF_WATCH_TASKS and (int(result) & 0xFFFFFFFF) == SCHED_REFUSED_MISSED:
                continue
            failed.append({"name": name, "result": "0x%08X" % (int(result) & 0xFFFFFFFF)})
    return {"zombies": zombies, "failed": failed}


def check_scheduled_task_health() -> Optional[dict]:
    if sys.platform != "win32":
        return None  # Windows Task Scheduler only — no-op elsewhere
    prefix_ps = TASK_PREFIX.replace("'", "''")  # bound the PS single-quoted literal — no injection via HARNESS_TASK_PREFIX
    ps = (
        "Get-ScheduledTask | Where-Object {$_.TaskName -like '" + prefix_ps + "*'} | "
        "ForEach-Object { $i=$_|Get-ScheduledTaskInfo; [pscustomobject]@{"
        "name=$_.TaskName; state=[string]$_.State; result=[int64]$i.LastTaskResult; "
        "last=$(if($i.LastRunTime){$i.LastRunTime.ToUniversalTime().ToString('o')}else{$null})} } | "
        "ConvertTo-Json -Compress"
    )
    v = _judge_scheduled_tasks(_ps_json(ps), datetime.now(timezone.utc))
    if v.get("probe_failed"):
        return {"rule": "scheduled-task-probe-failed", "declared": "observe",
                "reason": f"could not query {TASK_PREFIX}* scheduled tasks", "context": {}}
    zombies, failed = v["zombies"], v["failed"]
    if not zombies and not failed:
        return None
    parts = []
    if zombies:
        parts.append(f"{len(zombies)} task(s) still Running > {TASK_RUNNING_MAX_MIN}m: "
                     + ", ".join(f"{z['name']} ({z['running_min']}m)" for z in zombies))
    if failed:
        parts.append(f"{len(failed)} task(s) last exited non-zero: "
                     + ", ".join(f"{x['name']} {x['result']}" for x in failed))
    return {
        "rule": "scheduled-task-unhealthy",
        "declared": "ask",
        "reason": "; ".join(parts),
        "context": {
            "zombies": zombies, "failed": failed,
            "fix_options": [
                "kill a hung task's tree: taskkill /PID <pid> /T /F",
                "read the task's log for the failure",
                "if recurring, the task's script likely needs a timeout/lock guard",
            ],
        },
    }


def _judge_processes(procs, now: datetime) -> dict:
    """Pure: find capture-pipeline processes alive longer than the zombie
    threshold. `procs` is a list of {name,pid,creation,cmdline} or None."""
    if procs is None:
        return {"probe_failed": True}
    zombies = []
    for p in procs:
        cmd = p.get("cmdline") or ""
        marker = next((m for m in ZOMBIE_CMD_MARKERS if m and m in cmd), None)
        if not marker:
            continue
        created = _parse_iso(p.get("creation"))
        if created is not None and (now - created) > timedelta(hours=ZOMBIE_PROC_MAX_HOURS):
            zombies.append({"pid": p.get("pid"), "name": p.get("name"),
                            "age_h": round((now - created).total_seconds() / 3600, 1), "marker": marker})
    return {"zombies": zombies}


def check_process_health() -> Optional[dict]:
    if sys.platform != "win32":
        return None  # Win32_Process probe only — no-op elsewhere
    ps = (
        "Get-CimInstance Win32_Process -Filter \"Name='cmd.exe' OR Name='node.exe'\" | "
        "ForEach-Object { [pscustomobject]@{name=$_.Name; pid=$_.ProcessId; "
        "creation=$_.CreationDate.ToUniversalTime().ToString('o'); cmdline=$_.CommandLine} } | "
        "ConvertTo-Json -Compress"
    )
    v = _judge_processes(_ps_json(ps), datetime.now(timezone.utc))
    if v.get("probe_failed"):
        return {"rule": "process-probe-failed", "declared": "observe",
                "reason": "could not enumerate processes", "context": {}}
    zombies = v["zombies"]
    if not zombies:
        return None
    desc = ", ".join(f"{z['name']} PID {z['pid']} ({z['marker']}, {z['age_h']}h)" for z in zombies)
    return {
        "rule": "capture-pipeline-zombie",
        "declared": "ask",
        "reason": f"{len(zombies)} capture-pipeline process(es) alive > {ZOMBIE_PROC_MAX_HOURS}h (hung?): {desc}",
        "context": {
            "zombies": zombies,
            "fix_options": [
                "kill the hung tree: taskkill /PID <pid> /T /F",
                "inspect its log",
                "if recurring, wire a timeout guard into the runner",
            ],
        },
    }


# --- Inventory + discovery detectors + coverage self-report ------------
# "See every aspect, now and future" = DISCOVERY (walk the harness, never
# hand-list), so new instances of a known class are covered automatically.
# Anti-silent-rot = a COVERAGE SELF-REPORT (what has no detector) + per-detector
# SELFTESTS (a detector must prove it still fires on a known-bad fixture, else
# it's flagged dead/unverified). The watch names the limits of its own vision
# rather than going quietly blind.

def build_inventory() -> dict:
    """Discover harness surfaces by walking known roots. New files of a known
    class are picked up automatically — discovery over enumeration."""
    root = vault_root()

    def _glob(rel: str, pat: str) -> list:
        d = root / rel
        return sorted(str(p.relative_to(root)) for p in d.glob(pat)) if d.exists() else []

    state_dir = capture_pipeline_root() / "state"
    inv = {
        "workflows": _glob(".claude/workflows", "*.js"),
        "commands": _glob(".claude/commands", "*.md"),
        "agents": _glob(".claude/agents", "*.md"),
        "rules": _glob(".claude/rules", "*.md"),
        "hooks": _glob("scripts/hooks", "*.py"),
        "scripts": _glob("scripts", "*.py"),
        "mcp_servers": _glob("scripts/mcp", "*.py"),
        "state_logs": [p.name for p in state_dir.glob("*.log")] if state_dir.exists() else [],
    }
    inv["counts"] = {k: len(v) for k, v in inv.items()}
    return inv


def check_static_validity() -> list:
    """Discovery-driven, multi-finding: every workflow declares meta.name == its
    filename (mirrors deterministic check D22), and every harness python file
    compiles. New files are covered automatically — future-proof by construction."""
    findings: list = []
    root = vault_root()
    inv = build_inventory()
    for rel in inv["workflows"]:
        f = _judge_workflow_meta(rel, _safe_read(root / rel), Path(rel).stem)
        if f:
            findings.append(f)
    for rel in sorted(set(inv["hooks"] + inv["scripts"] + inv["mcp_servers"])):
        f = _judge_python_source(rel, _safe_read(root / rel))
        if f:
            findings.append(f)
    return findings


# --- Pure judges (extracted so each can be selftested) ----------------
# Each judge is the DECISION half of a detector; the detector keeps the
# file/probe half and delegates the verdict here. A selftest then proves the
# judge fires on bad input AND stays quiet on good input — so a detector can't
# silently stop discriminating.

def _judge_token_age(age_days, path_str):
    if age_days is None:
        return {"rule": "token-cache-missing", "declared": "ask",
                "reason": "token-cache.json not found at expected path", "context": {"path": path_str}}
    if age_days >= TOKEN_AGE_DENY_DAYS:
        return {"rule": "token-age-imminent", "declared": "deny",
                "reason": f"token cache is {age_days:.1f} days old (threshold {TOKEN_AGE_DENY_DAYS}d) — silent expiry imminent",
                "context": {"age_days": round(age_days, 1), "threshold_days": TOKEN_AGE_DENY_DAYS,
                            "remediation": "re-run your capture pipeline's auth flow"}}
    if age_days >= TOKEN_AGE_ASK_DAYS:
        return {"rule": "token-age-pre-warn", "declared": "ask",
                "reason": f"token cache is {age_days:.1f} days old — reauth recommended this week before silent expiry",
                "context": {"age_days": round(age_days, 1), "threshold_days": TOKEN_AGE_ASK_DAYS,
                            "remediation": "re-run your capture pipeline's auth flow"}}
    return None


def _judge_capture_age(age_hours, path_str):
    if age_hours is None:
        return {"rule": "captured-json-missing", "declared": "ask",
                "reason": "captured.json not found at expected path", "context": {"path": path_str}}
    if age_hours > CAPTURE_STALE_HOURS:
        return {"rule": "capture-gap", "declared": "ask",
                "reason": f"captured.json last updated {age_hours:.1f} hours ago (threshold {CAPTURE_STALE_HOURS}h)",
                "context": {"age_hours": round(age_hours, 1), "threshold_hours": CAPTURE_STALE_HOURS}}
    return None


def _judge_todo_age(age_hours, path_str):
    if age_hours is None:
        return {"rule": "todo-missing", "declared": "ask",
                "reason": "TODO.md not found at expected path", "context": {"path": path_str}}
    if age_hours > TODO_STALE_HOURS:
        return {"rule": "todo-not-refreshed", "declared": "ask",
                "reason": f"TODO.md mtime is {age_hours:.1f} hours old at post-run check (threshold {TODO_STALE_HOURS}h) — the daily refresh may not have completed",
                "context": {"age_hours": round(age_hours, 1), "threshold_hours": TODO_STALE_HOURS}}
    return None


def _judge_error_log(device_code_hits, other_failures):
    if device_code_hits:
        return {"rule": "device-code-expired-recent", "declared": "deny",
                "reason": f"{len(device_code_hits)} device_code_expired error(s) in last {ERROR_LOG_WINDOW_HOURS}h — capture pipeline is broken until re-auth",
                "context": {"count": len(device_code_hits), "window_hours": ERROR_LOG_WINDOW_HOURS,
                            "remediation": "re-run your capture pipeline's auth flow",
                            "recent_runners": sorted({h["runner"] for h in device_code_hits})}}
    if other_failures:
        runners = sorted({h["runner"] for h in other_failures if h["runner"]})
        return {"rule": "error-log-failures-recent", "declared": "ask",
                "reason": f"{len(other_failures)} automation failure(s) logged in last {ERROR_LOG_WINDOW_HOURS}h ({', '.join(runners) or 'unknown'}) — not device-code; a scheduled task is erroring",
                "context": {"count": len(other_failures), "window_hours": ERROR_LOG_WINDOW_HOURS, "runners": runners}}
    return None


def _judge_python_source(rel, src):
    import ast
    try:
        ast.parse(src)
        return None
    except SyntaxError as e:
        return {"rule": "python-syntax-error", "declared": "ask",
                "reason": f"{rel} has a syntax error at line {e.lineno}: {e.msg}",
                "context": {"file": rel, "line": e.lineno,
                            "fix_options": ["open the file and fix the syntax error",
                                            "review recent edits to this file"]}}
    except Exception:
        return None


def _judge_workflow_meta(rel, text, stem):
    if "export const meta" not in text:
        return {"rule": "workflow-meta-missing", "declared": "ask",
                "reason": f"workflow {rel} has no `export const meta`", "context": {"file": rel}}
    m = re.search(r"name:\s*['\"]([^'\"]+)['\"]", text)
    got = m.group(1) if m else None
    if got != stem:
        return {"rule": "workflow-meta-name-mismatch", "declared": "ask",
                "reason": f"workflow {rel} meta.name '{got}' != filename '{stem}'",
                "context": {"file": rel, "meta_name": got}}
    return None


_SAFE_READ_MAX_BYTES = 1_000_000  # bound memory/parse time on discovered files


def _safe_read(path) -> str:
    try:
        if path.stat().st_size > _SAFE_READ_MAX_BYTES:
            return ""  # oversized discovered file — skip rather than spike memory / stall ast.parse
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _judge_config_file(rel, text, required_key):
    """Validate a command/agent/rule .md: frontmatter parses + has its required field."""
    if not text.startswith("---"):
        if required_key:
            return {"rule": "config-frontmatter-missing", "declared": "ask",
                    "reason": f"{rel} has no YAML frontmatter (expected '{required_key}')", "context": {"file": rel}}
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return {"rule": "config-frontmatter-unterminated", "declared": "ask",
                "reason": f"{rel} YAML frontmatter is not terminated", "context": {"file": rel}}
    fm = text[3:end]
    try:
        import yaml
        data = yaml.safe_load(fm)
    except ImportError:
        if required_key and (required_key + ":") not in fm:
            return {"rule": "config-missing-field", "declared": "ask",
                    "reason": f"{rel} frontmatter missing required '{required_key}'", "context": {"file": rel}}
        return None
    except Exception as e:
        return {"rule": "config-frontmatter-yaml-error", "declared": "ask",
                "reason": f"{rel} frontmatter YAML error: {str(e).splitlines()[0][:100]}",
                "context": {"file": rel,
                            "fix_options": ["fix the YAML frontmatter (often an unquoted colon in a value)",
                                            "quote the offending value"]}}
    if not isinstance(data, dict):
        return {"rule": "config-frontmatter-invalid", "declared": "ask",
                "reason": f"{rel} frontmatter is not a key:value mapping", "context": {"file": rel}}
    if required_key and required_key not in data:
        return {"rule": "config-missing-field", "declared": "ask",
                "reason": f"{rel} frontmatter missing required '{required_key}'", "context": {"file": rel}}
    return None


def _is_readme(rel: str) -> bool:
    # READMEs are documentation, not command/agent definitions — they carry no
    # required frontmatter, so exclude them from the config-validity check.
    return Path(rel).name.lower() == "readme.md"


def check_config_validity() -> list:
    """Discovery-driven, multi-finding: every command/agent/rule .md has valid
    frontmatter + its load-bearing field. (READMEs excluded — not config files.)"""
    root = vault_root()
    inv = build_inventory()
    out = []
    for rel in inv["commands"]:
        if _is_readme(rel):
            continue
        out.append(_judge_config_file(rel, _safe_read(root / rel), "description"))
    for rel in inv["agents"]:
        if _is_readme(rel):
            continue
        out.append(_judge_config_file(rel, _safe_read(root / rel), "name"))
    for rel in inv["rules"]:
        if _is_readme(rel):
            continue
        out.append(_judge_config_file(rel, _safe_read(root / rel), None))
    return [f for f in out if f]


# --- Per-detector selftests (anti-silent-rot) -------------------------
# A detector with a pure _judge proves it can still fire by running it against a
# known-bad fixture. Detectors with no selftest are reported "unverified" in the
# coverage report — the watch surfaces the limits of its own vision rather than
# going quietly blind.

def _selftest_scheduled_tasks() -> bool:
    now = datetime.now(timezone.utc)
    v = _judge_scheduled_tasks(
        [{"name": "X", "state": "Running", "result": 267009,
          "last": (now - timedelta(minutes=90)).isoformat()}], now)
    return bool(v.get("zombies"))


def _selftest_processes() -> bool:
    now = datetime.now(timezone.utc)
    marker = ZOMBIE_CMD_MARKERS[0] if ZOMBIE_CMD_MARKERS else "capture"
    v = _judge_processes(
        [{"name": "cmd.exe", "pid": 1, "creation": (now - timedelta(hours=2)).isoformat(),
          "cmdline": f"cmd /c {marker}.bat"}], now)
    return bool(v.get("zombies"))


def _selftest_token() -> bool:
    return _judge_token_age(30, "x") is not None and _judge_token_age(10, "x") is None


def _selftest_capture() -> bool:
    return _judge_capture_age(48, "x") is not None and _judge_capture_age(2, "x") is None


def _selftest_todo() -> bool:
    return _judge_todo_age(12, "x") is not None and _judge_todo_age(1, "x") is None


def _selftest_error_log() -> bool:
    return _judge_error_log([{"runner": "x"}], []) is not None and _judge_error_log([], []) is None


def _selftest_static() -> bool:
    return (_judge_python_source("x.py", "def (:\n") is not None
            and _judge_python_source("y.py", "x = 1\n") is None
            and _judge_workflow_meta("w.js", "no meta here", "w") is not None)


def _selftest_config() -> bool:
    return (_judge_config_file("c.md", "no frontmatter", "description") is not None
            and _judge_config_file("c.md", "---\ndescription: x\n---\nbody\n", "description") is None)


SELFTESTS: dict = {
    "check_scheduled_task_health": _selftest_scheduled_tasks,
    "check_process_health": _selftest_processes,
    "check_token_age": _selftest_token,
    "check_capture_freshness": _selftest_capture,
    "check_todo_freshness": _selftest_todo,
    "check_error_log_recent": _selftest_error_log,
    "check_static_validity": _selftest_static,
    "check_config_validity": _selftest_config,
}

# Which inventory classes any detector actually inspects (for the blind-spot map).
COVERED_CLASSES = {"workflows", "hooks", "scripts", "mcp_servers", "state_logs",
                   "commands", "agents", "rules"}


def coverage_self_report(inventory: dict, detector_names: list) -> dict:
    """The meta-check: what the watch inventoried, what it has NO detector for
    (blind spots), and which detectors can still prove they fire (selftests)."""
    blind = {cls: n for cls, n in inventory["counts"].items()
             if cls not in COVERED_CLASSES and n > 0}
    selftests = {}
    for name in detector_names:
        fn = SELFTESTS.get(name)
        if fn is None:
            selftests[name] = "unverified"  # no selftest — cannot prove it still fires
        else:
            try:
                selftests[name] = "pass" if fn() else "DEAD"
            except Exception:
                selftests[name] = "ERROR"
    return {
        "inventory_counts": inventory["counts"],
        "blind_spots": blind,
        "selftests": selftests,
        "detectors_verified": sum(1 for v in selftests.values() if v == "pass"),
        "detectors_total": len(detector_names),
    }


# --- Registry ---------------------------------------------------------

# Each entry: (name, fn, takes_phase_arg). fn may return None | dict | list[dict].
SIGNAL_FUNCS: list[tuple[str, Callable, bool]] = [
    ("check_token_age", check_token_age, False),
    ("check_capture_freshness", check_capture_freshness, False),
    ("check_todo_freshness", check_todo_freshness, True),
    ("check_error_log_recent", check_error_log_recent, False),
    ("check_scheduled_task_health", check_scheduled_task_health, False),
    ("check_process_health", check_process_health, False),
    ("check_static_validity", check_static_validity, False),
    ("check_config_validity", check_config_validity, False),
]

# --- Vault note + toast ------------------------------------------------

SEVERITY_RANK = {"deny": 4, "ask": 3, "observe": 2, "allow": 1}
SEVERITY_EMOJI = {"deny": "🔴", "ask": "🟡", "observe": "🟢", "allow": ""}


def write_vault_note(
    phase: str,
    results: list[tuple[str, list]],
    mode: str,
    coverage: Optional[dict] = None,
) -> Path:
    note_dir = vault_path("00-Inbox/_harness")
    note_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d")
    note_path = note_dir / f"{today}-watch-{phase}.md"
    now_str = datetime.now().strftime("%H:%M")

    fired = [(name, s) for name, fl in results for s in fl]
    all_clear = [name for name, fl in results if not fl]
    declared_severities = [s["declared"] for _, s in fired]
    worst = "allow"
    if declared_severities:
        worst = max(declared_severities, key=lambda v: SEVERITY_RANK.get(v, 0))

    fm = (
        "---\n"
        "type: harness-watch\n"
        f"phase: {phase}\n"
        f"date: {today}\n"
        f"time: {now_str}\n"
        f"mode: {mode}\n"
        f"signals_fired: {len(fired)}\n"
        f"declared_severity: {worst}\n"
        "trust: harness-generated\n"  # machine observation, NOT authored fact
        "---\n\n"
    )
    body: list[str] = [f"# Harness watch — {today} {now_str} ({phase}-run)\n\n"]
    mode_note = (
        "(shadow phase — verdicts logged but not enforcing)"
        if mode == MONITOR_MODE
        else "(production)"
    )
    body.append(f"**Mode:** `{mode}` {mode_note}\n\n")

    if fired:
        body.append(f"## Signals fired ({len(fired)})\n\n")
        for _, s in fired:
            emoji = SEVERITY_EMOJI.get(s["declared"], "")
            body.append(f"### {emoji} `{s['rule']}` — declared `{s['declared']}`\n\n")
            body.append(f"{s['reason']}\n\n")
            ctx = s.get("context", {}) or {}
            if ctx.get("remediation"):
                body.append(f"**Remediation:** `{ctx['remediation']}`\n\n")
            other = {k: v for k, v in ctx.items() if k != "remediation"}
            if other:
                body.append("Context:\n")
                for k, v in other.items():
                    body.append(f"- `{k}`: {v}\n")
                body.append("\n")
    else:
        body.append("## All clear ✅\n\nNo signals fired.\n\n")

    if all_clear:
        body.append("## Signals checked (no issue)\n\n")
        for name in all_clear:
            body.append(f"- `{name}`\n")
        body.append("\n")

    if coverage:
        body.append("## Coverage self-report\n\n")
        inv = coverage.get("inventory_counts", {})
        body.append("**Inventoried:** "
                    + ", ".join(f"{k} {v}" for k, v in inv.items() if k != "counts")
                    + "\n\n")
        blind = coverage.get("blind_spots", {})
        if blind:
            body.append("**Blind spots** (discovered but no health detector yet): "
                        + ", ".join(f"{k} ({v})" for k, v in blind.items()) + "\n\n")
        st = coverage.get("selftests", {})
        dead = [n for n, r in st.items() if r in ("DEAD", "ERROR")]
        unver = [n for n, r in st.items() if r == "unverified"]
        body.append(
            f"**Detector selftests:** {coverage.get('detectors_verified', 0)}/"
            f"{coverage.get('detectors_total', 0)} proven fire-capable.\n"
        )
        if dead:
            body.append(f"- 🔴 STRUCTURALLY DEAD (selftest failed — cannot fire): {', '.join(dead)}\n")
        if unver:
            body.append(f"- 🟡 unverified (no selftest — add a pure `_judge` + fixture): {', '.join(unver)}\n")
        body.append("\n")

    body.append(
        "---\n\n"
        "_Harness watch entry. Verdicts also written to "
        "`state/verdict/{YYYY-MM-DD}.jsonl`. The coverage self-report names the watch's own blind spots._\n"
    )

    note_path.write_text(fm + "".join(body), encoding="utf-8")
    return note_path


def show_toast(title: str, message: str) -> None:
    # XML-escape (&,<,> — & FIRST) THEN PowerShell single-quote-escape. Without the
    # XML escape, a reason containing <, > or & makes $doc.LoadXml throw and the
    # toast is silently dropped. No injection risk — the single-quote escape bounds
    # the PS string literal. Windows-only; no-op elsewhere.
    if sys.platform != "win32":
        return

    def _x(s: str) -> str:
        return ((s or "")
                .replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace("'", "''"))
    safe_title = _x(title or "Harness watch")
    safe_msg = _x(message or "")
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
        "::CreateToastNotifier('HarnessWatch').Show($toast)"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
            timeout=5,
            capture_output=True,
        )
    except Exception:
        pass


# --- Main -------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument(
        "--phase",
        choices=["pre", "post"],
        default="post",
        help="pre = before the daily capture batch; post = after it. "
             "Default post (runs every detector). Scheduled runs pass this explicitly.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="don't write vault note or toast — print findings + coverage to stdout",
    )
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="scan-everything-now: run all detectors + print the coverage self-report; still writes the note",
    )
    args = parser.parse_args()

    mode = current_mode()
    inventory = build_inventory()

    results: list[tuple[str, list]] = []
    for name, fn, takes_phase in SIGNAL_FUNCS:
        try:
            r = fn(args.phase) if takes_phase else fn()
        except Exception as e:
            r = {
                "rule": f"{name}-check-error",
                "declared": "observe",
                "reason": f"detector {name} raised: {type(e).__name__}: {str(e)[:80]}",
                "context": {"error_type": type(e).__name__},
            }
        if r is None:
            fl = []
        elif isinstance(r, list):
            fl = r
        else:
            fl = [r]
        results.append((name, fl))

    # Emit a verdict per finding.
    for _, fl in results:
        for r in fl:
            emit_verdict(
                hook=HOOK_NAME,
                rule=r["rule"],
                verdict=r["declared"],
                reason=r["reason"],
                context=r.get("context", {}),
                enforce=r["rule"] in PROMOTED_RULES,
            )

    coverage = coverage_self_report(inventory, [n for n, _, _ in SIGNAL_FUNCS])

    if args.dry_run or args.doctor:
        print(f"phase={args.phase}, mode={mode}")
        for name, fl in results:
            if not fl:
                print(f"  {name}: OK")
            for r in fl:
                print(f"  {name}: {r['declared']} — {r['reason']}")
        print("\n-- coverage self-report --")
        print("  inventory: " + ", ".join(
            f"{k}={v}" for k, v in coverage["inventory_counts"].items() if k != "counts"))
        if coverage["blind_spots"]:
            print("  blind spots: " + ", ".join(
                f"{k}({v})" for k, v in coverage["blind_spots"].items()))
        print(f"  selftests: {coverage['detectors_verified']}/{coverage['detectors_total']} verified fire-capable")
        for n, r in coverage["selftests"].items():
            if r != "pass":
                print(f"    {r}: {n}")

    if args.dry_run:
        return 0  # dry-run never writes

    # Writing the note / toast must never break the always-exit-0 observer
    # contract — a disk-full or permission error must not read to a scheduled
    # caller as "the watch failed to run". Degrade to a printed warning, exit 0.
    try:
        note_path = write_vault_note(args.phase, results, mode, coverage)
        print(f"Wrote {note_path}")
        # Scheduled runs toast on any DECLARED ask/deny (declared, not effective —
        # so monitor mode still surfaces what would have been enforced). --doctor
        # is interactive → no toast.
        if not args.doctor:
            all_findings = [r for _, fl in results for r in fl]
            severe = [r for r in all_findings if r["declared"] in ("ask", "deny")]
            if severe:
                worst = max(severe, key=lambda r: SEVERITY_RANK.get(r["declared"], 0))
                show_toast(
                    title=f"Harness watch ({args.phase}) — {worst['declared']}",
                    message=worst["reason"][:120],
                )
    except Exception as e:
        print(f"note/toast write failed (non-fatal): {type(e).__name__}: {str(e)[:80]}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
