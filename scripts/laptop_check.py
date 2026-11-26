#!/usr/bin/env python3
"""Charon laptop check: one read-only report that says whether this install really works.

    python scripts/laptop_check.py            # text report
    python scripts/laptop_check.py --json     # the same report as JSON

Run it after an install or a /charon-update. It checks, in order:

  1. Which Python the hook launcher (scripts/hook) picks, and its version.
  2. Every hook and MCP server command in .claude/settings.json and .mcp.json goes
     through the launcher, and the script it names exists.
  3. Every wired hook fires: each one is run through the launcher with a harmless
     sample input, HARNESS_HOOK_TEST=1 and a timeout, and its exit code recorded.
  4. Rules load: scripts/load-rules.py delivers every always-fire rule, zeus-first
     included.
  5. Agent Org is registered and the status line is set in your Claude Code user
     settings (through scripts/post_install_wiring.py --check).
  6. Every .claude/agents/*.md has a name and a description.
  7. `git status --porcelain` is clean (a dirty tree blocks /charon-update).

Exit 0 when every check passes, 1 when any fails.

What it enforces, and what it does not:

  - Hooks (checks 1, 3 and 4) run from a temporary copy of scripts/ and .claude/
    (your settings.local.json is left out). Their environment points these at
    folders inside that temporary area: CLAUDE_PROJECT_DIR, HARNESS_VAULT_ROOT,
    CHARON_ROOT, HARNESS_MEMORY_ROOT, CLAUDE_MEMORY_DIR, HARNESS_CAPTURE_ROOT,
    HARNESS_SECRETS_DIR, HOME, USERPROFILE, CLAUDE_CONFIG_DIR, TEMP, TMP, TMPDIR,
    APPDATA, LOCALAPPDATA and the XDG_* folders. Variables whose names look like keys,
    tokens, secrets, passwords or connection strings are removed. PYTHONUSERBASE is
    set to your real Python user folder so packages installed there still import.
  - A hook's script must resolve inside the temporary copy; a rooted (/x),
    drive-relative (D:x) or `..` path is refused, not run. On Windows, an argument
    routed through scripts/hook.cmd that carries a cmd metacharacter is refused.
  - Anything a hook writes in the temporary area is reported (which hook, which
    file) and deleted with it. The repo is compared before and after, and any change
    is a FAIL.
  - This is redirection, not a sandbox: a hook that ignores these variables and
    writes to a hardcoded path is not stopped, only the repo is checked afterwards.
  - Check 5 runs scripts/post_install_wiring.py --check against your real user
    settings (it reads them), and check 7 runs `git status`. Neither writes.

On Windows the Notification hook may show one desktop notification saying it is a
laptop-check test; that is the hook working.

It never prints the values in your settings, only key names and OK / not OK.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import site
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Callable

REPO = Path(__file__).resolve().parents[1]
MIN_PY = (3, 10)
LAUNCHER = "scripts/hook"
LAUNCHER_CMD = "scripts/hook.cmd"
LOAD_RULES = "scripts/load-rules.py"
WIRING = "scripts/post_install_wiring.py"
ZEUS_RULE = "zeus-first.md"
GATE_ALWAYS_RULES = ("confidence-tags.md", "no-assumptions.md", "save-on-mention.md",
                     "session-start-ritual.md")
PROBE_REL = "scripts/_laptop_check_probe.py"
PROBE_NOTE = "00-Inbox/laptop-check-probe.md"

# Backlog rows of the parallel work a FAIL here points at.
ROW_LAUNCHER = "Charon backlog row 2 (hook launcher)"
ROW_WIRING = "Charon backlog rows 3 and 31 (Agent Org pane and status line)"
ROW_ZEUS = "Charon backlog row 4 (zeus-first rule)"

BARE_PYTHON = {"python", "python3", "py", "python.exe", "python3.exe", "py.exe", "pythonw", "pythonw.exe"}
SHELLS = {"sh", "bash", "sh.exe", "bash.exe"}
SKIP_COPY = {"__pycache__", "node_modules", ".git", "settings.local.json"}
# Environment variable NAMES that look like they carry a credential. Matched anywhere in
# the name unless anchored; PAT, SAS, OTP and PIN only as a whole `_`-separated word so
# PATH and PATHEXT survive, and *PWD only with something before it so PWD survives.
SECRET_ENV = re.compile(
    r"KEY|TOKEN|SECRET|PASS|CREDENTIAL|AUTH|COOKIE|SESSION|PRIVATE|BEARER|JWT|SIGNATURE"
    r"|WEBHOOK|DSN|CONN(ECTION)?_?STR|.PWD$|(^|_)(PAT|SAS|OTP|PIN)($|_)"
    r"|(^|_)(DATABASE|DB|REDIS|MONGO|MONGODB|POSTGRES|PG|MYSQL|AMQP|RABBITMQ|BROKER)_UR[LI]$",
    re.I)
# What may pass through scripts/hook.cmd: cmd.exe re-parses its command line, so
# & | < > ^ ( ) % ! " and whitespace in an argument could run something else.
CMD_SAFE_ARG = re.compile(r"[A-Za-z0-9_./\\:=+,@-]+")
# Folders a hook might write to, redirected into the temporary area (relative to it).
REDIRECT_DIRS = {
    "CLAUDE_MEMORY_DIR": "memory",
    "HARNESS_MEMORY_ROOT": "memory",
    "HARNESS_CAPTURE_ROOT": "capture",
    "HARNESS_SECRETS_DIR": "secrets",
    "TEMP": "tmp",
    "TMP": "tmp",
    "TMPDIR": "tmp",
    "APPDATA": "appdata",
    "LOCALAPPDATA": "localappdata",
    "XDG_CONFIG_HOME": "xdg/config",
    "XDG_DATA_HOME": "xdg/data",
    "XDG_CACHE_HOME": "xdg/cache",
    "XDG_STATE_HOME": "xdg/state",
    "XDG_RUNTIME_DIR": "xdg/runtime",
}
ALWAYS_HEADING = re.compile(r"^## `([^`]+)` .{1,3} always-fire rule\s*$", re.M)


@dataclass
class Check:
    num: int
    name: str
    ok: bool = True
    detail: str = ""
    items: list[str] = field(default_factory=list)

    def fail(self, msg: str) -> None:
        self.ok = False
        self.items.append("FAIL: " + msg)

    def note(self, msg: str) -> None:
        self.items.append(msg)

    def to_dict(self) -> dict:
        return {"check": self.num, "name": self.name, "status": "PASS" if self.ok else "FAIL",
                "detail": self.detail, "items": self.items}


@dataclass
class HookCmd:
    source: str          # e.g. "settings.json hooks.PreToolUse[Edit|Write]"
    event: str           # hook event, or "mcp"
    matcher: str
    tokens: list[str]
    kind: str = ""       # "launcher" | "bare-python" | "other" | "unparseable"
    target: str = ""     # repo-relative script
    args: list[str] = field(default_factory=list)
    problem: str = ""


@dataclass
class Ctx:
    repo: Path
    home: Path
    timeout: float
    git_status: Callable[[Path], tuple[int, str]]
    sandbox: Path | None = None
    tmp: Path | None = None
    launcher_ok: bool = False


# ---------- small helpers ----------

def _clean(text: str, limit: int = 160) -> str:
    text = "".join(ch if ch.isprintable() else " " for ch in (text or "")).strip()
    return text if len(text) <= limit else text[: limit - 3] + "..."


def _last_line(text: str) -> str:
    lines = [ln for ln in (text or "").splitlines() if ln.strip()]
    return _clean(lines[-1]) if lines else ""


def _load_json(path: Path) -> tuple[dict | None, str]:
    if not path.is_file():
        return None, f"{path.name} not found"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"{path.name} unreadable ({type(exc).__name__})"
    if not isinstance(data, dict):
        return None, f"{path.name} is not a JSON object"
    return data, ""


def _safe_env(extra: dict[str, str]) -> dict[str, str]:
    """The current environment minus anything credential-shaped, plus `extra`."""
    env = {k: v for k, v in os.environ.items() if not SECRET_ENV.search(k)}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env.update(extra)
    return env


def _run(argv: list[str], *, cwd: Path, env: dict[str, str], stdin: str = "",
         timeout: float) -> tuple[int | None, str, str]:
    """(exit code or None on timeout / launch failure, stdout, stderr). Never raises."""
    try:
        p = subprocess.run(argv, cwd=str(cwd), env=env, input=stdin.encode("utf-8"),
                           capture_output=True, timeout=timeout, shell=False)
    except subprocess.TimeoutExpired:
        return None, "", f"timed out after {timeout:g}s"
    except OSError as exc:
        return None, "", f"could not start ({type(exc).__name__})"
    return (p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace"))


def _snapshot(root: Path) -> dict[str, tuple[int, int]]:
    snap: dict[str, tuple[int, int]] = {}
    if not root.is_dir():
        return snap
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules")]
        for fn in filenames:
            p = Path(dirpath) / fn
            try:
                st = p.lstat()
            except OSError:
                continue
            snap[p.relative_to(root).as_posix()] = (st.st_size, st.st_mtime_ns)
    return snap


def _diff(before: dict, after: dict) -> list[str]:
    out = []
    for rel in sorted(set(before) | set(after)):
        if rel not in before:
            out.append(f"added {rel}")
        elif rel not in after:
            out.append(f"removed {rel}")
        elif before[rel] != after[rel]:
            out.append(f"changed {rel}")
    return out


def _copy_ignore(src: str, names: list[str]) -> set[str]:
    skip = set()
    for n in names:
        if n in SKIP_COPY or n.endswith(".pyc") or os.path.islink(os.path.join(src, n)):
            skip.add(n)
    return skip


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


# ---------- launcher ----------

class UnsafeCmdArg(ValueError):
    """An argument that cmd.exe would re-parse, so it is refused on the hook.cmd route."""


def _cmd_unsafe(tokens: list[str]) -> str:
    """The first token not safe to pass through hook.cmd, or "" when all are safe."""
    for t in tokens:
        if not CMD_SAFE_ARG.fullmatch(t or ""):
            return t or "(empty)"
    return ""


def launcher_argv(root: Path, rel: str, args: list[str]) -> list[str] | None:
    """How Claude Code would run `hook <rel> [args]` in `root`, or None if it cannot.

    Raises UnsafeCmdArg when the only route is hook.cmd and the script or an argument
    carries a cmd metacharacter: cmd.exe re-parses the line, so it is refused, not run.
    """
    sh = shutil.which("sh")
    if (root / LAUNCHER).is_file() and sh:
        return [sh, str(root / LAUNCHER), rel, *args]
    if os.name == "nt" and (root / LAUNCHER_CMD).is_file():
        bad = _cmd_unsafe([rel, *args])
        if bad or any(ch in str(root) for ch in '%!"'):
            shown = _clean(bad, 40) if bad else "the temporary folder path"
            raise UnsafeCmdArg(f"`{shown}` carries a cmd metacharacter, refused on the hook.cmd route")
        return [str(root / LAUNCHER_CMD), rel, *args]
    return None


def _emulate_pick(timeout: float) -> tuple[list[str] | None, str]:
    """The launcher's search order (python3, python, py -3), done here when it is missing."""
    for cand in (["python3"], ["python"], ["py", "-3"]):
        exe = shutil.which(cand[0])
        if not exe:
            continue
        rc, out, err = _run([exe, *cand[1:], "--version"], cwd=Path.cwd(), env=_safe_env({}),
                            timeout=timeout)
        m = re.search(r"Python (\d+)\.(\d+)\.(\d+)", out + err)
        if rc == 0 and m:
            return [exe, *cand[1:]], ".".join(m.groups())
    return None, ""


# ---------- command parsing (check 2) ----------

def _expand(text: str, repo: Path) -> str:
    root = repo.resolve().as_posix()
    return text.replace("${CLAUDE_PROJECT_DIR}", root).replace("$CLAUDE_PROJECT_DIR", root)


def classify(cmd: HookCmd, repo: Path) -> None:
    toks = cmd.tokens
    if not toks:
        cmd.kind, cmd.problem = "unparseable", "empty command"
        return
    first = Path(toks[0].replace("\\", "/")).name.lower()
    if first in BARE_PYTHON:
        cmd.kind = "bare-python"
        cmd.problem = f"starts with bare `{first}`, not the launcher ({ROW_LAUNCHER})"
        py = next((t for t in toks[1:] if t.lower().endswith(".py")), "")
        cmd.target = _rel(py, repo) or ""
        return
    rest = toks[1:] if first in SHELLS else toks
    if not rest:
        cmd.kind, cmd.problem = "other", "runs a shell with nothing after it"
        return
    lpath = rest[0].replace("\\", "/")
    if not (lpath.endswith("/" + LAUNCHER) or lpath.endswith("/" + LAUNCHER_CMD)
            or lpath in (LAUNCHER, LAUNCHER_CMD)):
        cmd.kind, cmd.problem = "other", f"does not go through the launcher (starts with `{_clean(Path(lpath).name, 40)}`)"
        return
    cmd.kind = "launcher"
    if len(rest) < 2:
        cmd.problem = "launcher is given no script"
        return
    rel = _rel(rest[1], repo)
    if rel is None:
        cmd.problem = f"script `{_clean(rest[1], 80)}` is not a path inside the repo"
        return
    cmd.target, cmd.args = rel, rest[2:]


def _rel(token: str, repo: Path) -> str | None:
    """`token` as a repo-relative POSIX path, or None unless it resolves inside `repo`.

    A rooted path (`/x`, which on Windows is not "absolute" and would land on the
    current drive) and a drive-relative path (`D:x`) are refused on every OS, as is
    any `..` step or a path that resolves (through links) outside the repo.
    """
    if not token:
        return None
    t = token.replace("\\", "/")
    p = Path(t)
    if p.is_absolute():
        if not _within(p, repo):
            return None
        return p.resolve().relative_to(repo.resolve()).as_posix()
    win = PureWindowsPath(t)
    if win.drive or win.root or PurePosixPath(t).is_absolute():
        return None
    if ".." in p.parts or not _within(repo / p, repo):
        return None
    return p.as_posix()


def collect_commands(repo: Path) -> tuple[list[HookCmd], list[str]]:
    cmds: list[HookCmd] = []
    problems: list[str] = []
    settings, err = _load_json(repo / ".claude" / "settings.json")
    if settings is None:
        problems.append(f".claude/settings.json: {err}")
        settings = {}
    hooks = settings.get("hooks") if isinstance(settings.get("hooks"), dict) else {}
    for event, groups in hooks.items():
        for group in groups if isinstance(groups, list) else []:
            if not isinstance(group, dict):
                continue
            matcher = str(group.get("matcher") or "")
            for h in group.get("hooks") or []:
                if not isinstance(h, dict) or h.get("type", "command") != "command":
                    continue
                raw = str(h.get("command") or "")
                src = f"settings.json hooks.{event}" + (f"[{matcher}]" if matcher else "")
                try:
                    toks = shlex.split(_expand(raw, repo), posix=True)
                except ValueError:
                    cmds.append(HookCmd(src, event, matcher, [], "unparseable", problem="command does not parse"))
                    continue
                c = HookCmd(src, event, matcher, toks)
                classify(c, repo)
                cmds.append(c)
    mcp_sources = [("settings.json", settings)]
    mcp, err = _load_json(repo / ".mcp.json")
    if mcp is None:
        if (repo / ".mcp.json").exists():
            problems.append(f".mcp.json: {err}")
    else:
        mcp_sources.append((".mcp.json", mcp))
    for label, data in mcp_sources:
        servers = data.get("mcpServers") if isinstance(data.get("mcpServers"), dict) else {}
        for name, spec in servers.items():
            if not isinstance(spec, dict):
                continue
            if spec.get("type", "stdio") != "stdio" or "command" not in spec:
                continue  # remote servers have no local command
            args = spec.get("args") if isinstance(spec.get("args"), list) else []
            toks = [_expand(str(x), repo) for x in [spec.get("command"), *args]]
            c = HookCmd(f"{label} mcpServers.{name}", "mcp", "", toks)
            classify(c, repo)
            cmds.append(c)
    return cmds, problems


# ---------- sandbox ----------

def build_sandbox(ctx: Ctx) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="charon-laptop-check-"))
    ctx.tmp = tmp
    box = tmp / "repo"
    box.mkdir()
    for d in (".claude", "scripts", "cerberus"):
        if (ctx.repo / d).is_dir():
            shutil.copytree(ctx.repo / d, box / d, ignore=_copy_ignore, symlinks=False)
    for f in (".mcp.json", "CLAUDE.md"):
        src = ctx.repo / f
        if src.is_file() and not src.is_symlink():
            shutil.copy2(src, box / f)
    (box / "00-Inbox").mkdir(exist_ok=True)
    (box / PROBE_NOTE).write_text("Charon laptop check probe note.\n", encoding="utf-8")
    (box / PROBE_REL).parent.mkdir(parents=True, exist_ok=True)
    (box / PROBE_REL).write_text(
        "import json, platform, sys\n"
        "print(json.dumps({'exe': sys.executable, 'version': platform.python_version()}))\n",
        encoding="utf-8")
    for d in ("home", *sorted(set(REDIRECT_DIRS.values()))):
        (tmp / d).mkdir(parents=True, exist_ok=True, mode=0o700)
    ctx.sandbox = box


def sandbox_env(ctx: Ctx) -> dict[str, str]:
    """Environment for a hook fired in the temporary copy: every folder it might write to
    points inside the temporary area (see the module docstring for the list)."""
    assert ctx.tmp is not None and ctx.sandbox is not None
    home = str(ctx.tmp / "home")
    extra = {
        "HARNESS_HOOK_TEST": "1",
        "CLAUDE_PROJECT_DIR": str(ctx.sandbox),
        "HARNESS_VAULT_ROOT": str(ctx.sandbox),
        "CHARON_ROOT": str(ctx.sandbox),
        "HOME": home,
        "USERPROFILE": home,
        "CLAUDE_CONFIG_DIR": str(ctx.tmp / "home" / ".claude"),
    }
    for name, sub in REDIRECT_DIRS.items():
        extra[name] = str(ctx.tmp / sub)
    env = _safe_env(extra)
    for name in [k for k in env if k.upper().startswith("XDG_") and k not in REDIRECT_DIRS]:
        del env[name]  # XDG_*_DIRS search lists and the like: the defaults apply instead
    if "PYTHONUSERBASE" not in env:
        try:
            env["PYTHONUSERBASE"] = site.getuserbase()  # APPDATA/HOME moved; keep user packages importable
        except Exception:
            pass
    return env


def _fire_argv(ctx: Ctx, rel: str, args: list[str]) -> tuple[list[str] | None, str]:
    """argv to run a sandbox script through the launcher, or directly if the launcher is missing.

    (None, reason) when it is refused: the script resolves outside the temporary copy,
    or the hook.cmd route would pass a cmd metacharacter.
    """
    assert ctx.sandbox is not None
    r = _rel(rel, ctx.sandbox)
    if r is None or not _within(ctx.sandbox / r, ctx.sandbox):
        return None, f"refused: `{_clean(rel, 80)}` resolves outside the temporary copy"
    try:
        argv = launcher_argv(ctx.sandbox, r, args)
    except UnsafeCmdArg as exc:
        return None, f"refused: {exc}"
    if argv:
        return argv, ""
    return [sys.executable, str(ctx.sandbox / r), *args], "launcher missing, fired with this Python directly"


# ---------- the checks ----------

def check_interpreter(ctx: Ctx) -> Check:
    c = Check(1, "Interpreter the launcher picks")
    missing = [p for p in (LAUNCHER, LAUNCHER_CMD) if not (ctx.repo / p).is_file()]
    for p in missing:
        c.fail(f"{p} is missing ({ROW_LAUNCHER})")
    try:
        argv = launcher_argv(ctx.sandbox, PROBE_REL, []) if ctx.sandbox else None
    except UnsafeCmdArg as exc:
        c.fail(f"the launcher probe was refused: {exc}")
        return c
    if argv:
        rc, out, err = _run(argv, cwd=ctx.sandbox, env=sandbox_env(ctx), timeout=ctx.timeout)
        if rc == 2 and not out.strip():
            c.fail("the launcher found no Python 3 (exit 2); install Python 3.10+")
            return c
        try:
            info = json.loads(out.strip().splitlines()[-1])
        except (ValueError, IndexError):
            c.fail(f"the launcher did not run the probe (exit {rc}): {_last_line(err)}")
            return c
        ctx.launcher_ok = True
        ver = str(info.get("version", ""))
        c.detail = f"launcher runs {info.get('exe', '?')} (Python {ver})"
    else:
        picked, ver = _emulate_pick(ctx.timeout)
        if not picked:
            c.fail("no python3, python or py -3 on PATH")
            return c
        c.detail = f"no runnable launcher; its search order would pick {' '.join(picked)} (Python {ver})"
    try:
        parts = tuple(int(x) for x in ver.split(".")[:2])
    except ValueError:
        parts = (0, 0)
    if parts < MIN_PY:
        c.fail(f"Python {ver} is older than {MIN_PY[0]}.{MIN_PY[1]}")
    return c


def check_commands(ctx: Ctx, cmds: list[HookCmd], problems: list[str]) -> Check:
    c = Check(2, "Hook and MCP commands go through the launcher")
    for p in problems:
        c.fail(p)
    if not (ctx.repo / LAUNCHER).is_file():
        c.fail(f"{LAUNCHER} is missing, so no command can go through it ({ROW_LAUNCHER})")
    bare = 0
    for cmd in cmds:
        label = f"{cmd.source}: {cmd.target or '?'}"
        if cmd.kind == "bare-python":
            bare += 1
        if cmd.problem:
            c.fail(f"{label}: {cmd.problem}")
        if cmd.target and not (ctx.repo / cmd.target).is_file():
            c.fail(f"{label}: target script does not exist")
    good = sum(1 for x in cmds if x.kind == "launcher" and not x.problem
               and x.target and (ctx.repo / x.target).is_file())
    c.detail = f"{good} of {len(cmds)} commands go through the launcher to a script that exists"
    if bare:
        c.detail += f"; {bare} start with bare python"
    return c


def _sample(event: str, matcher: str, ctx: Ctx) -> dict:
    assert ctx.sandbox is not None and ctx.tmp is not None
    base = {"session_id": "laptop-check", "cwd": str(ctx.sandbox), "hook_event_name": event,
            "transcript_path": str(ctx.tmp / "no-transcript.jsonl")}
    tool = (matcher.split("|")[0].strip() if matcher else "") or "Read"
    probe = str(ctx.sandbox / PROBE_NOTE)
    inputs = {
        "Edit": {"file_path": probe, "old_string": "probe", "new_string": "probe"},
        "Write": {"file_path": probe, "content": "Charon laptop check probe note.\n"},
        "MultiEdit": {"file_path": probe, "edits": []},
        "NotebookEdit": {"notebook_path": probe, "new_source": ""},
        "Read": {"file_path": probe},
        "Bash": {"command": "echo laptop-check"},
        "Skill": {"skill": "recall"},
    }
    if event == "UserPromptSubmit":
        return {**base, "prompt": "hi"}  # short on purpose: below every LLM-triage threshold
    if event in ("PreToolUse", "PostToolUse"):
        d = {**base, "tool_name": tool, "tool_input": inputs.get(tool, {})}
        if event == "PostToolUse":
            d["tool_response"] = {"stdout": "laptop-check", "stderr": "", "output": "", "success": True}
        return d
    if event == "Notification":
        return {**base, "title": "Charon laptop check", "message": "Laptop check test notification."}
    if event in ("Stop", "SubagentStop"):
        return {**base, "stop_hook_active": False}
    if event == "SessionStart":
        return {**base, "source": "startup"}
    return base


def check_hooks_fire(ctx: Ctx, cmds: list[HookCmd]) -> Check:
    c = Check(3, "Every wired hook fires")
    assert ctx.sandbox is not None and ctx.tmp is not None
    hooks = [x for x in cmds if x.event != "mcp"]
    if not hooks:
        c.fail("no hooks are wired in .claude/settings.json")
        return c
    env = sandbox_env(ctx)
    repo_before = _snapshot(ctx.repo)
    fired = 0
    direct = False
    for h in hooks:
        label = f"{h.event}" + (f"[{h.matcher}]" if h.matcher else "") + f" {h.target or '?'}"
        if not h.target or not (ctx.sandbox / h.target).is_file():
            c.fail(f"{label}: no script to fire")
            continue
        argv, how = _fire_argv(ctx, h.target, h.args)
        if argv is None:
            c.fail(f"{label}: {how}")
            continue
        direct = direct or bool(how)
        before = _snapshot(ctx.tmp)
        rc, _out, err = _run(argv, cwd=ctx.sandbox, env=env,
                             stdin=json.dumps(_sample(h.event, h.matcher, ctx)), timeout=ctx.timeout)
        writes = _diff(before, _snapshot(ctx.tmp))
        if rc is None:
            c.fail(f"{label}: {err}")
        elif "Traceback (most recent call last)" in err:
            c.fail(f"{label}: exit {rc} but crashed: {_last_line(err)}")
        elif rc not in (0, 2):
            c.fail(f"{label}: exit {rc}: {_last_line(err)}")
        else:
            fired += 1
            c.note(f"{label}: exit {rc}" + (" (blocked the sample)" if rc == 2 else ""))
        for w in writes:
            verb, _, rel = w.partition(" ")
            where = rel[len("repo/"):] if rel.startswith("repo/") else "(temp " + rel + ")"
            marked = "/_test/" in "/" + rel
            c.note(f"  {label} {verb} in the temporary copy: {where}"
                   + (" (test-marked)" if marked else " (NOT test-marked)"))
    changed = _diff(repo_before, _snapshot(ctx.repo))
    for w in changed:
        c.fail(f"the real repo changed while hooks fired: {w}")
    c.detail = f"{fired} of {len(hooks)} hooks fired (exit 0 or 2)"
    if direct:
        c.detail += f"; launcher missing, so they were fired with this Python directly ({ROW_LAUNCHER})"
    return c


def _frontmatter(text: str) -> dict[str, str]:
    m = re.match(r"^---\r?\n(.*?)\r?\n---", text, re.S)
    if not m:
        return {}
    fm: dict[str, str] = {}
    lines = m.group(1).splitlines()
    for i, line in enumerate(lines):
        mm = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if not mm:
            continue
        key, val = mm.group(1), mm.group(2).strip().strip('"').strip("'")
        if val in (">", "|", ">-", "|-", ">+", "|+", ""):
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            val = nxt.strip() if nxt[:1] in (" ", "\t") else ""
        fm[key] = val
    return fm


def check_rules(ctx: Ctx) -> Check:
    c = Check(4, "Always-fire rules load")
    rules_dir = ctx.repo / ".claude" / "rules"
    expected = set(GATE_ALWAYS_RULES) | {ZEUS_RULE}
    if rules_dir.is_dir():
        for p in rules_dir.glob("*.md"):
            try:
                if _frontmatter(p.read_text(encoding="utf-8")).get("always", "").lower() == "true":
                    expected.add(p.name)
            except OSError:
                continue
    for name in sorted(expected):
        p = rules_dir / name
        row = f" ({ROW_ZEUS})" if name == ZEUS_RULE else ""
        if not p.is_file():
            c.fail(f"{name} is missing from .claude/rules{row}")
        elif _frontmatter(p.read_text(encoding="utf-8")).get("always", "").lower() != "true":
            c.fail(f"{name} is not tagged `always: true`{row}")
    if not (ctx.repo / LOAD_RULES).is_file():
        c.fail(f"{LOAD_RULES} is missing")
        return c
    assert ctx.sandbox is not None
    argv, how = _fire_argv(ctx, LOAD_RULES, [])
    if argv is None:
        c.fail(f"{LOAD_RULES}: {how}")
        return c
    stdin =json.dumps({"prompt": "hi", "cwd": str(ctx.sandbox), "session_id": "laptop-check"})
    rc, out, err = _run(argv, cwd=ctx.sandbox, env=sandbox_env(ctx), stdin=stdin, timeout=ctx.timeout)
    if rc != 0:
        c.fail(f"{LOAD_RULES} exit {rc}: {_last_line(err)}")
        return c
    delivered = set(ALWAYS_HEADING.findall(out))
    for name in sorted(expected):
        if name not in delivered:
            row = f" ({ROW_ZEUS})" if name == ZEUS_RULE else ""
            c.fail(f"{name} was not delivered by {LOAD_RULES}{row}")
    c.detail = f"{len(delivered & expected)} of {len(expected)} always-fire rules delivered"
    if how:
        c.detail += f" ({how})"
    return c


def check_wiring(ctx: Ctx) -> Check:
    c = Check(5, "Agent Org registered and status line set")
    home = str(ctx.home)
    script = ctx.repo / WIRING
    if script.is_file():
        argv = [sys.executable, str(script), "--mode", "update", "--check"]
        env = _safe_env({"HOME": home, "USERPROFILE": home})
        rc, out, err = _run(argv, cwd=ctx.repo, env=env, timeout=ctx.timeout)
        for line in out.splitlines():
            m = re.match(r"^\s+(Agent Org|Status line): (OK|NOT WIRED)\b", line)
            if m:
                c.note(f"{m.group(1)}: {m.group(2)}")
        if rc == 0:
            c.detail = f"{WIRING} --check: everything wired"
        elif rc == 1:
            c.detail = f"{WIRING} --check: not wired"
            c.fail(f"not wired; fix with: python {WIRING} --mode update ({ROW_WIRING})")
        else:
            c.fail(f"{WIRING} --check exit {rc}: {_last_line(err)}")
        return c
    # Fallback: read the user settings, report key names only.
    c.fail(f"{WIRING} is missing ({ROW_WIRING})")
    data, err = _load_json(ctx.home / ".claude" / "settings.json")
    if data is None:
        c.fail(f"user settings: {err}")
        return c
    env = data.get("env") if isinstance(data.get("env"), dict) else {}
    plugin = str(env.get("CLAUDE_CODE_PLUGIN_DIRS", "")).replace("\\", "/")
    has_plugin = "plugins/agent-org-reporter" in plugin
    sl = data.get("statusLine")
    has_sl = isinstance(sl, dict) and "scripts/statusline.py" in str(sl.get("command", ""))
    c.note(f"env.CLAUDE_CODE_PLUGIN_DIRS lists the Agent Org plugin: {'yes' if has_plugin else 'no'}")
    c.note(f"statusLine points at Charon's status line: {'yes' if has_sl else 'no'}")
    if not has_plugin:
        c.fail(f"Agent Org is not registered ({ROW_WIRING})")
    if not has_sl:
        c.fail(f"the status line is not set ({ROW_WIRING})")
    return c


def check_agents(ctx: Ctx) -> Check:
    c = Check(6, "Agents parse")
    d = ctx.repo / ".claude" / "agents"
    files = sorted(p for p in d.glob("*.md") if p.name != "README.md") if d.is_dir() else []
    if not files:
        c.fail(".claude/agents has no agent files")
        return c
    good = 0
    for p in files:
        try:
            fm = _frontmatter(p.read_text(encoding="utf-8"))
        except OSError as exc:
            c.fail(f"{p.name}: unreadable ({type(exc).__name__})")
            continue
        missing = [k for k in ("name", "description") if not fm.get(k)]
        if missing:
            c.fail(f"{p.name}: no {' or '.join(missing)} in frontmatter")
        else:
            good += 1
    c.detail = f"{good} of {len(files)} agents have a name and a description"
    return c


def default_git_status(repo: Path) -> tuple[int, str]:
    git = shutil.which("git")
    if not git:
        return 127, "git not found on PATH"
    rc, out, err = _run([git, "-C", str(repo), "status", "--porcelain"], cwd=repo,
                        env=_safe_env({}), timeout=30)
    return (rc if rc is not None else 124), (out if rc == 0 else err)


def check_git_clean(ctx: Ctx) -> Check:
    c = Check(7, "Working tree clean")
    try:
        rc, out = ctx.git_status(ctx.repo)
    except Exception as exc:  # a broken runner is a FAIL, never a crash
        c.fail(f"git status could not run ({type(exc).__name__})")
        return c
    if rc != 0:
        c.fail(f"git status failed (exit {rc}): {_last_line(out)}")
        return c
    lines = [ln for ln in out.splitlines() if ln.strip()]
    if lines:
        c.fail(f"{len(lines)} uncommitted change(s); /charon-update refuses a dirty tree")
        for ln in lines[:10]:
            c.note("  " + _clean(ln, 120))
        if len(lines) > 10:
            c.note(f"  ... and {len(lines) - 10} more")
    c.detail = "clean" if not lines else f"{len(lines)} change(s)"
    return c


# ---------- entry ----------

def run_checks(repo: Path = REPO, home: Path | None = None, timeout: float = 30.0,
               git_status: Callable[[Path], tuple[int, str]] = default_git_status) -> list[Check]:
    ctx = Ctx(repo=repo.resolve(), home=home if home is not None else Path.home(),
              timeout=timeout, git_status=git_status)
    checks: list[Check] = []
    try:
        build_sandbox(ctx)
        cmds, problems = collect_commands(ctx.repo)
        steps: list[tuple[int, str, Callable[[], Check]]] = [
            (1, "Interpreter the launcher picks", lambda: check_interpreter(ctx)),
            (2, "Hook and MCP commands go through the launcher", lambda: check_commands(ctx, cmds, problems)),
            (3, "Every wired hook fires", lambda: check_hooks_fire(ctx, cmds)),
            (4, "Always-fire rules load", lambda: check_rules(ctx)),
            (5, "Agent Org registered and status line set", lambda: check_wiring(ctx)),
            (6, "Agents parse", lambda: check_agents(ctx)),
            (7, "Working tree clean", lambda: check_git_clean(ctx)),
        ]
        for num, name, fn in steps:
            try:
                checks.append(fn())
            except Exception as exc:  # one broken check never hides the others
                bad = Check(num, name)
                bad.fail(f"the check itself failed ({type(exc).__name__}: {_clean(str(exc), 100)})")
                checks.append(bad)
    finally:
        if ctx.tmp is not None:
            shutil.rmtree(ctx.tmp, ignore_errors=True)
    return checks


def render(checks: list[Check], repo: Path) -> str:
    out = [f"Charon laptop check for {repo}", ""]
    for c in checks:
        out.append(f"[{'PASS' if c.ok else 'FAIL'}] {c.num}. {c.name}" + (f": {c.detail}" if c.detail else ""))
        out.extend("      " + it for it in c.items)
    failed = [str(c.num) for c in checks if not c.ok]
    out.append("")
    out.append(f"{len(checks) - len(failed)} of {len(checks)} checks passed."
               + (f" Failed: {', '.join(failed)}." if failed else " This install works."))
    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    ap = argparse.ArgumentParser(
        description="Read-only Charon laptop check: launcher, hook commands, hooks firing, "
                    "always-fire rules, Agent Org and status line, agents, clean tree. "
                    "Exit 0 when every check passes, 1 when any fails.")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    ap.add_argument("--timeout", type=float, default=30.0, help="seconds allowed per hook (default 30)")
    a = ap.parse_args(argv)
    checks = run_checks(REPO, timeout=max(1.0, a.timeout))
    ok = all(c.ok for c in checks)
    if a.json:
        print(json.dumps({"repo": str(REPO), "ok": ok, "checks": [c.to_dict() for c in checks]}, indent=2))
    else:
        print(render(checks, REPO))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
