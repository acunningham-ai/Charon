#!/usr/bin/env python3
"""Move a Charon settings file and .mcp.json onto the scripts/hook launcher.

    python scripts/launcher_migrate.py --settings .claude/settings.json --mcp .mcp.json
    python scripts/launcher_migrate.py --settings .claude/settings.json --mcp .mcp.json --write

Why: a command that starts with a bare `python` runs whichever interpreter the PATH
happens to hold, or none. Linux often has only `python3`, so every hook is dead
there and every PreToolUse gate fails OPEN. `scripts/hook` finds python3, python or
`py -3` at run time and exits 2 (blocks) when there is none. The release gate checks
this as D39 (no bare interpreter) and D40 (the launcher really runs a hook).

What it changes, and nothing else:
  1. Every hook command and the statusLine command that starts with a bare
     interpreter becomes
         sh "${CLAUDE_PROJECT_DIR}/scripts/hook" <repo-relative script> [args]
     The repo-relative script path and every argument are kept exactly. The
     `${CLAUDE_PROJECT_DIR}/` prefix moves onto the launcher, because the launcher
     only runs a repo-relative path (it refuses absolute paths and `..`).
  2. Every MCP server that starts with a bare interpreter becomes
         "command": "sh", "args": ["${CLAUDE_PROJECT_DIR}/scripts/hook", <script>, <args...>]
     Every other key of the server (type, env, ...) is kept.
  3. A Bash allow rule naming a bare interpreter is replaced by the launcher form
     when it names a path under scripts/ (`Bash(python scripts/*)` becomes
     `Bash(sh scripts/hook scripts/*)`, which is narrower: the launcher refuses `..`
     and anything that is not a .py file). Any other such rule (`Bash(python:*)`,
     `Bash(python -m x)`) is dropped: it lets any code run without a prompt.
  4. An mcpServers block in the settings file is moved into .mcp.json, because
     Claude Code reads project MCP servers from .mcp.json only.

Anything it cannot convert without changing what runs (interpreter flags such as
`python -u`, a script outside scripts/, an argument with shell characters or
variables, a .py run by something other than an interpreter, a server defined
differently in both files) is listed as UNRESOLVED; then nothing is written and the
exit code is 1. Prose keys (`$comment`, `$..._note`) are never edited.

Safety: dry run by default (prints a unified diff, writes nothing). `--write`
applies. A second run changes nothing. A path that is, or sits directly in, a
symlink or junction is refused. Files are replaced atomically (temp file in the
same folder, then rename) and read back. Standard library only; no network, no
shell, no subprocess.

Exit codes: 0 done (or nothing to do, or dry run), 1 unresolved items (nothing
written), 2 usage, unreadable or unparseable JSON, or a refused path.
"""
from __future__ import annotations

import argparse
import copy
import difflib
import json
import os
import re
import shlex
import sys
from dataclasses import dataclass, field
from pathlib import Path

LAUNCHER_REL = "scripts/hook"
LAUNCHER_CMD_REL = "scripts/hook.cmd"
PROJECT_VAR = "${CLAUDE_PROJECT_DIR}"
LAUNCHER_ARG = PROJECT_VAR + "/" + LAUNCHER_REL
HOOK_PREFIX = 'sh "' + LAUNCHER_ARG + '"'

# Same interpreter names the release gate (D39) treats as bare.
BARE_INTERPRETER_RE = re.compile(r"^(?:python[0-9.]*w?|py|pypy[0-9.]*)$", re.I)
SHELLS = {"sh", "bash", "dash"}
# A repo-relative script under scripts/, the shape the launcher contract accepts.
SCRIPT_RE = re.compile(r"^scripts/[A-Za-z0-9_./-]+\.py$")
# Arguments copied into a shell command unquoted must not change meaning there:
# no spaces, quotes, $, backticks, globs, redirections or chain operators.
SAFE_ARG_RE = re.compile(r"^[A-Za-z0-9_./:=,+@%-]+$")
PROJECT_PREFIXES = (PROJECT_VAR + "/", "$CLAUDE_PROJECT_DIR/", "./")
BOM = chr(0xFEFF)


class MigrateError(Exception):
    """A refusal that stops the run before anything is written (exit 2)."""


# ---------- small helpers ----------

def _head(token: str) -> str:
    """Basename of a command token, lower case, without .exe."""
    h = str(token).replace("\\", "/").rsplit("/", 1)[-1].lower()
    return h[:-4] if h.endswith(".exe") else h


def _is_launcher_path(token: str) -> bool:
    t = str(token).replace("\\", "/")
    return (t in (LAUNCHER_REL, LAUNCHER_CMD_REL)
            or t.endswith("/" + LAUNCHER_REL) or t.endswith("/" + LAUNCHER_CMD_REL))


def goes_through_launcher(tokens: list) -> bool:
    if not tokens:
        return False
    if _is_launcher_path(tokens[0]):
        return True
    return _head(tokens[0]) in SHELLS and len(tokens) > 1 and _is_launcher_path(tokens[1])


def _repo_relative(script: str) -> str | None:
    """`${CLAUDE_PROJECT_DIR}/scripts/x.py` -> `scripts/x.py`; None if not convertible."""
    s = str(script)
    for prefix in PROJECT_PREFIXES:
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    if ".." in s.split("/") or not SCRIPT_RE.match(s):
        return None
    return s


def _split_interpreter(tokens: list) -> tuple[str | None, list, str]:
    """For tokens that start with a bare interpreter: (script, rest, why-not).

    Returns script=None with a reason when the command cannot be converted
    without changing what runs."""
    head = _head(tokens[0])
    rest = list(tokens[1:])
    if head == "py" and rest and rest[0] == "-3":
        rest = rest[1:]  # `py -3` only selects Python 3, which the launcher already does
    if not rest:
        return None, [], "no script after the interpreter"
    if str(rest[0]).startswith("-"):
        return None, [], f"interpreter option `{rest[0]}` cannot pass through the launcher"
    script = _repo_relative(rest[0])
    if script is None:
        return None, [], (f"script `{rest[0]}` is not a repo-relative path under scripts/ "
                          "(the launcher runs only those)")
    return script, rest[1:], ""


# ---------- the plan ----------

@dataclass
class Plan:
    settings: dict
    mcp: dict
    changes: list = field(default_factory=list)
    unresolved: list = field(default_factory=list)


def migrate_command(cmd: str) -> tuple[str | None, str]:
    """(new command or None if unchanged, problem). problem != '' means unresolved."""
    try:
        tokens = shlex.split(cmd, posix=True)
    except ValueError as exc:
        return None, f"command does not parse ({exc})"
    if not tokens or goes_through_launcher(tokens):
        return None, ""
    if BARE_INTERPRETER_RE.match(_head(tokens[0])):
        script, args, why = _split_interpreter(tokens)
        if script is None:
            return None, why
        bad = [a for a in args if not SAFE_ARG_RE.match(str(a))]
        if bad:
            return None, (f"argument `{bad[0]}` holds a character the shell would read "
                          "(space, quote, $, glob or operator); convert it by hand")
        return " ".join([HOOK_PREFIX, script, *args]), ""
    if any(str(t).lower().endswith(".py") for t in tokens):
        return None, "runs a .py file without an interpreter this tool knows how to replace"
    return None, ""


def migrate_server(spec: dict) -> tuple[dict | None, str]:
    """(new server spec or None if unchanged, problem)."""
    command = spec.get("command")
    if not isinstance(command, str):
        return None, ""
    args = spec.get("args", [])
    if args is None:
        args = []
    if not isinstance(args, list):
        return None, "`args` is not a list"
    tokens = [command, *[str(a) for a in args]]
    if goes_through_launcher(tokens):
        return None, ""
    if BARE_INTERPRETER_RE.match(_head(command)):
        script, rest, why = _split_interpreter(tokens)
        if script is None:
            return None, why
        new = {}
        for k, v in spec.items():
            if k == "command":
                new[k] = "sh"
            elif k == "args":
                new[k] = [LAUNCHER_ARG, script, *args[len(args) - len(rest):]]
            else:
                new[k] = v
        if "args" not in new:
            new["args"] = [LAUNCHER_ARG, script]
        return new, ""
    if any(str(t).lower().endswith(".py") for t in tokens):
        return None, "runs a .py file without an interpreter this tool knows how to replace"
    return None, ""


def migrate_allow_rule(rule) -> tuple[str, str | None]:
    """('keep'|'replace'|'drop', replacement)."""
    if not isinstance(rule, str):
        return "keep", None
    m = re.match(r"^Bash\(\s*([^\s:)]+)(.*)\)\s*$", rule, re.S)
    if not m or not BARE_INTERPRETER_RE.match(_head(m.group(1))):
        return "keep", None
    rest = m.group(2).strip()
    if rest.startswith("scripts/") and ".." not in rest:
        return "replace", f"Bash(sh {LAUNCHER_REL} {rest})"
    return "drop", None


def plan(settings: dict, mcp: dict) -> Plan:
    p = Plan(copy.deepcopy(settings), copy.deepcopy(mcp))
    s, m = p.settings, p.mcp

    hooks = s.get("hooks")
    if isinstance(hooks, dict):
        for event, groups in hooks.items():
            if not isinstance(groups, list):
                continue
            for gi, group in enumerate(groups):
                if not isinstance(group, dict) or not isinstance(group.get("hooks"), list):
                    continue
                for hi, h in enumerate(group["hooks"]):
                    if not isinstance(h, dict) or h.get("type", "command") != "command":
                        continue
                    label = f"hooks.{event}[{gi}].hooks[{hi}]"
                    new, why = migrate_command(str(h.get("command") or ""))
                    if why:
                        p.unresolved.append(f"settings {label}: {why}: {h.get('command')!r}")
                    elif new is not None:
                        h["command"] = new
                        p.changes.append(f"settings {label}: now runs through {LAUNCHER_REL}")

    status = s.get("statusLine")
    if isinstance(status, dict) and isinstance(status.get("command"), str):
        new, why = migrate_command(status["command"])
        if why:
            p.unresolved.append(f"settings statusLine: {why}: {status['command']!r}")
        elif new is not None:
            status["command"] = new
            p.changes.append(f"settings statusLine: now runs through {LAUNCHER_REL}")

    def fix_servers(where: str, servers: dict) -> None:
        for name, spec in list(servers.items()):
            if not isinstance(spec, dict):
                continue
            new, why = migrate_server(spec)
            if why:
                p.unresolved.append(f"{where} mcpServers.{name}: {why}")
            elif new is not None:
                servers[name] = new
                p.changes.append(f"{where} mcpServers.{name}: now starts through {LAUNCHER_REL}")

    mcp_servers = m.get("mcpServers")
    if mcp_servers is not None and not isinstance(mcp_servers, dict):
        p.unresolved.append(".mcp.json mcpServers is not an object")
        mcp_servers = None
    if isinstance(mcp_servers, dict):
        fix_servers(".mcp.json", mcp_servers)

    set_servers = s.get("mcpServers")
    if set_servers is not None and not isinstance(set_servers, dict):
        p.unresolved.append("settings mcpServers is not an object")
    elif isinstance(set_servers, dict):
        fix_servers("settings", set_servers)
        if mcp_servers is None:
            mcp_servers = {}
            m["mcpServers"] = mcp_servers
        conflict = False
        for name, spec in set_servers.items():
            if name in mcp_servers and mcp_servers[name] != spec:
                p.unresolved.append(f"mcpServers.{name} is defined differently in the settings file "
                                    "and .mcp.json; reconcile it by hand")
                conflict = True
        if not conflict:
            for name, spec in set_servers.items():
                if name not in mcp_servers:
                    mcp_servers[name] = spec
                    p.changes.append(f"mcpServers.{name}: moved from the settings file to .mcp.json")
                else:
                    p.changes.append(f"mcpServers.{name}: dropped from the settings file "
                                     "(.mcp.json already has the same server)")
            del s["mcpServers"]
            if not set_servers:
                p.changes.append("settings: empty mcpServers block removed")

    perms = s.get("permissions")
    allow = perms.get("allow") if isinstance(perms, dict) else None
    if isinstance(allow, list):
        new_allow = []
        for rule in allow:
            action, repl = migrate_allow_rule(rule)
            if action == "keep":
                new_allow.append(rule)
            elif action == "replace":
                if repl not in new_allow and repl not in allow:
                    new_allow.append(repl)
                p.changes.append(f"settings permissions.allow: `{rule}` -> `{repl}`")
            else:
                p.changes.append(f"settings permissions.allow: `{rule}` dropped "
                                 "(a bare interpreter with no script path lets any code run)")
        perms["allow"] = new_allow
    return p


# ---------- files ----------

@dataclass
class Style:
    indent: object = 2
    ascii: bool = True
    newline_at_end: bool = True
    crlf: bool = False
    bom: bool = False


def _style_of(raw: str) -> Style:
    st = Style()
    st.bom = raw.startswith(BOM)
    body = raw[1:] if st.bom else raw
    st.crlf = "\r\n" in body
    st.newline_at_end = body.endswith("\n")
    st.ascii = all(ord(c) < 128 for c in body)
    m = re.search(r"\n([ \t]+)\S", body)
    if m:
        ws = m.group(1)
        st.indent = "\t" if ws.startswith("\t") else len(ws)
    return st


def _render(data: dict, st: Style) -> str:
    text = json.dumps(data, indent=st.indent, ensure_ascii=st.ascii)
    if st.newline_at_end:
        text += "\n"
    if st.crlf:
        text = text.replace("\n", "\r\n")
    return (BOM if st.bom else "") + text


def is_link(path: Path) -> bool:
    """True for a symlink or (Windows) junction. A missing path is not a link."""
    try:
        if path.is_symlink():
            return True
    except OSError:
        pass
    isjunction = getattr(os.path, "isjunction", None)  # Python 3.12+
    if isjunction is not None:
        try:
            if isjunction(path):
                return True
        except OSError:
            pass
    if os.name == "nt":
        try:
            os.readlink(path)  # succeeds for symlinks and junctions only (3.8+)
            return True
        except (OSError, ValueError):
            pass
    return False


def check_path(path: Path, label: str, must_exist: bool) -> None:
    for p, what in ((path, "is"), (path.parent, "sits in")):
        if is_link(p):
            raise MigrateError(f"refused: {label} {path} {what} a symlink or junction ({p}). "
                               "Point the tool at the real file.")
    if path.exists() and not path.is_file():
        raise MigrateError(f"refused: {label} {path} is not a regular file")
    if must_exist and not path.is_file():
        raise MigrateError(f"{label} not found: {path}")


def load(path: Path, label: str) -> tuple[dict, str]:
    """(data, raw text). A missing optional file is ({}, '')."""
    if not path.exists():
        return {}, ""
    try:
        raw = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise MigrateError(f"cannot read {label} {path}: {type(exc).__name__}: {exc}")
    try:
        data = json.loads(raw[1:] if raw.startswith(BOM) else raw)
    except json.JSONDecodeError as exc:
        raise MigrateError(f"{label} {path} is not valid JSON (line {exc.lineno}, column {exc.colno}: "
                           f"{exc.msg}). Nothing was changed; fix the file and run again.")
    if not isinstance(data, dict):
        raise MigrateError(f"{label} {path} must hold a JSON object at the top level")
    return data, raw


def write_atomic(path: Path, text: str, label: str) -> None:
    check_path(path, label, must_exist=False)  # re-check right before the write
    tmp = path.with_name("." + path.name + ".launcher-migrate.tmp")
    if tmp.exists() or is_link(tmp):
        raise MigrateError(f"refused: leftover temp file {tmp}; remove it and run again")
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    os.replace(tmp, path)


# ---------- entry point ----------

def run(argv: list | None = None, out=print, err=None) -> int:
    err = err or (lambda s: print(s, file=sys.stderr))
    ap = argparse.ArgumentParser(
        description="Rewrite hook, statusLine and MCP server commands to start through scripts/hook. "
                    "Dry run by default; --write applies.")
    ap.add_argument("--settings", required=True, type=Path, help="Claude Code settings JSON to migrate")
    ap.add_argument("--mcp", required=True, type=Path,
                    help=".mcp.json to migrate (created if the settings file has servers to move into it)")
    ap.add_argument("--write", action="store_true", help="apply the changes (default: print a diff only)")
    a = ap.parse_args(argv)

    try:
        s_path, m_path = a.settings, a.mcp
        check_path(s_path, "settings file", must_exist=True)
        check_path(m_path, ".mcp.json", must_exist=False)
        if m_path.exists() and os.path.samefile(s_path, m_path):
            raise MigrateError("refused: --settings and --mcp are the same file")
        settings, s_raw = load(s_path, "settings file")
        mcp, m_raw = load(m_path, ".mcp.json")
    except MigrateError as exc:
        err(f"launcher_migrate: {exc}")
        return 2

    p = plan(settings, mcp)
    if p.unresolved:
        err(f"launcher_migrate: {len(p.unresolved)} item(s) cannot be converted without changing what runs. "
            "Nothing was written.")
        for u in p.unresolved:
            err(f"  UNRESOLVED {u}")
        return 1

    outputs = []  # (path, old raw, new text, label); .mcp.json first so a server is never in neither
    if p.mcp != mcp:
        st = _style_of(m_raw) if m_raw else Style()
        outputs.append((m_path, m_raw, _render(p.mcp, st), ".mcp.json"))
    if p.settings != settings:
        outputs.append((s_path, s_raw, _render(p.settings, _style_of(s_raw)), "settings file"))

    if not outputs:
        out("launcher_migrate: no changes: every command already starts through scripts/hook.")
        return 0

    for c in p.changes:
        out(f"  change: {c}")
    for path, old, new, _label in outputs:
        out("".join(difflib.unified_diff(
            old.splitlines(keepends=True), new.splitlines(keepends=True),
            fromfile=f"{path} (before)", tofile=f"{path} (after)")))

    if not a.write:
        out(f"launcher_migrate: dry run: {len(p.changes)} change(s) in {len(outputs)} file(s); "
            "nothing written. Run again with --write to apply.")
        return 0

    try:
        for path, _old, new, label in outputs:
            write_atomic(path, new, label)
        for path, _old, _new, label in outputs:
            back, _ = load(path, label)
            want = p.mcp if label == ".mcp.json" else p.settings
            if back != want:
                raise MigrateError(f"wrote {path}, but reading it back does not match")
    except (MigrateError, OSError) as exc:
        err(f"launcher_migrate: {exc}")
        return 2
    out(f"launcher_migrate: wrote {len(outputs)} file(s), {len(p.changes)} change(s). "
        "Restart Claude Code to load them.")
    return 0


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass
    return run()


if __name__ == "__main__":
    sys.exit(main())
