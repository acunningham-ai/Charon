#!/usr/bin/env python3
"""Tests for scripts/launcher_migrate.py (release blocker D39: no bare interpreter).

What it proves, driving the real tool through its command line (sys.executable):

  positive
    - copies of this repo's real .claude/settings.json and .mcp.json, migrated with
      --write, pass the release gate's own D39 check (imported from
      test-scenarios/run-deterministic-checks.py, not reimplemented): PASS, no
      findings, no warnings; every hook also matches the gate's D40 launcher shape;
    - every repo-relative script path and every argument is unchanged, hook by
      hook and server by server; keys the tool does not own are unchanged;
    - mcpServers moved out of the settings copy into the .mcp.json copy;
    - the allow list equals the copy's own pre-run list with only the bare-python
      scripts rule changed. The real settings carry no scripts allow rule at all
      since the v0.38.0 release review (it let any scripts/*.py run unprompted), so
      on the real copy the list must come out unchanged with no rule added (the
      already-migrated and unmigrated states are still checked if they occur);
    - a copy of the real settings with Bash(python scripts/*) put back between two
      rules: the rule is converted in place to the launcher form, and a dropped,
      swapped, added or still-bare allow rule all fail the kept-in-order check;
    - statusLine, `py -3`, `python3.exe`, arguments and extra server keys convert;
    - a second --write run changes nothing (bytes and mtime), and says so.
  negative
    - the unmigrated copies FAIL the same gate check (the check can see the fault);
    - dry run (the default) writes nothing and prints a diff;
    - unparseable JSON in either file: exit 2, a clear message, nothing written;
    - a symlinked file and a file inside a junction (Windows) are refused, exit 2;
    - interpreter flags, a script outside scripts/, shell characters in an
      argument, a .py run by node, and a conflicting server: exit 1, nothing written.
  mutation
    - a copy of the tool edited to leave MCP servers on bare python, to drop
      hook arguments, or to leave the scripts allow rule bare, is caught by the
      same assertions.

Never touches the real files: they are only read and copied, and their bytes and
mtimes are compared before and after. Everything else is under a temp folder,
removed at the end. No network, no git, no shell: the only subprocess is
sys.executable running the tool with a fixed argument list.

Run from the repo root:  python scripts/test_launcher_migrate.py
Exit 0 when every check passes, 1 otherwise.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO = Path(__file__).resolve().parent.parent
TOOL = REPO / "scripts" / "launcher_migrate.py"
GATE = REPO / "test-scenarios" / "run-deterministic-checks.py"
REAL_SETTINGS = REPO / ".claude" / "settings.json"
REAL_MCP = REPO / ".mcp.json"
PROJECT_VAR = "${CLAUDE_PROJECT_DIR}"

results: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))


def load_gate():
    spec = importlib.util.spec_from_file_location("charon_release_gate_launcher_migrate", GATE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def run_tool(*args, tool: Path = TOOL):
    return subprocess.run([sys.executable, str(tool), *[str(a) for a in args]], capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=120, cwd=str(REPO))


def state(*paths: Path) -> dict:
    out = {}
    for p in paths:
        if p.exists():
            st = p.stat()
            out[str(p)] = (p.read_bytes(), st.st_mtime_ns)
        else:
            out[str(p)] = None
    return out


def gate_check(gate, s: Path, m: Path):
    gate.SETTINGS_FILE, gate.MCP_FILE = s, m
    return gate.check_no_bare_interpreter()


# ---- what must survive: the repo-relative script and its arguments ----

def _rel(script: str) -> str:
    for prefix in (PROJECT_VAR + "/", "$CLAUDE_PROJECT_DIR/", "./"):
        if script.startswith(prefix):
            return script[len(prefix):]
    return script


def _strip_runner(tokens: list) -> list:
    """Drop the interpreter (or sh + launcher) and return [script, args...]."""
    head = tokens[0].replace("\\", "/").rsplit("/", 1)[-1].lower()
    if head == "sh" and len(tokens) > 1 and tokens[1].replace("\\", "/").endswith("scripts/hook"):
        rest = tokens[2:]
    else:
        rest = tokens[1:]
        if head in ("py", "py.exe") and rest[:1] == ["-3"]:
            rest = rest[1:]
    return [_rel(rest[0]), *rest[1:]] if rest else []


def hook_payloads(settings: dict) -> list:
    out = []
    for event, groups in (settings.get("hooks") or {}).items():
        for gi, g in enumerate(groups):
            for hi, h in enumerate(g.get("hooks", [])):
                out.append(((event, gi, hi), _strip_runner(shlex.split(h["command"]))))
    st = settings.get("statusLine")
    if isinstance(st, dict) and st.get("command"):
        out.append((("statusLine",), _strip_runner(shlex.split(st["command"]))))
    return out


def server_payloads(*docs: dict) -> dict:
    out = {}
    for d in docs:
        for name, spec in (d.get("mcpServers") or {}).items():
            out[name] = _strip_runner([spec["command"], *spec.get("args", [])])
    return out


def unowned(settings: dict) -> dict:
    """Everything in a settings dict the tool must leave alone."""
    d = {k: v for k, v in settings.items() if k not in ("hooks", "statusLine", "mcpServers", "permissions")}
    perms = dict(settings.get("permissions") or {})
    perms.pop("allow", None)
    d["permissions-minus-allow"] = perms
    return d


# The one allow rule the migration changes, and what it becomes.
OLD_ALLOW = "Bash(python scripts/*)"
NEW_ALLOW = "Bash(sh scripts/hook scripts/*)"


def expected_allow(old_allow: list) -> list:
    """The pre-run allow list with only the interpreter rule changed (in place, once)."""
    out = []
    for x in old_allow:
        if x == OLD_ALLOW:
            if NEW_ALLOW not in old_allow and NEW_ALLOW not in out:
                out.append(NEW_ALLOW)
        else:
            out.append(x)
    return out


def allow_kept(old_allow: list, new_allow: list) -> bool:
    return new_allow == expected_allow(old_allow)


def allow_checks(tag: str, old_allow: list, new_allow: list, require_scripts_rule: bool) -> None:
    """The allow-list assertions, for any pre-run state of the list.

    Three pre-run states are handled, each strictly:
      - the bare rule Bash(python scripts/*) is present: it must be replaced in
        place by the launcher rule, and the bare rule must be gone;
      - only the launcher rule is present (already migrated): both left as they were;
      - neither is present (the real settings since the v0.38.0 review removed the
        broad rule): the list must come out identical, with neither rule added.
    require_scripts_rule=True demands the first state, so the still-bare negative
    is exercised (the fixture case below)."""
    if OLD_ALLOW in old_allow:
        i = old_allow.index(OLD_ALLOW)
        record(f"{tag}: allow rule {OLD_ALLOW} replaced in place by {NEW_ALLOW}",
               new_allow[i:i + 1] == [NEW_ALLOW] and OLD_ALLOW not in new_allow, str(new_allow))
    elif require_scripts_rule:
        record(f"{tag}: pre-run allow list holds {OLD_ALLOW}", False, str(old_allow))
    elif NEW_ALLOW in old_allow:
        # Already migrated: the launcher rule must be there, the bare one must
        # not, and the run must leave both where they are.
        record(f"{tag}: already migrated: {NEW_ALLOW} present, {OLD_ALLOW} absent, both left as they were",
               NEW_ALLOW in new_allow and OLD_ALLOW not in new_allow
               and old_allow.index(NEW_ALLOW) == new_allow.index(NEW_ALLOW), str(new_allow))
    else:
        # No scripts allow rule at all: the tool must not invent one.
        record(f"{tag}: no scripts allow rule before the run: list unchanged, "
               f"neither {NEW_ALLOW} nor {OLD_ALLOW} added",
               new_allow == old_allow and NEW_ALLOW not in new_allow and OLD_ALLOW not in new_allow,
               str(new_allow))
    # Expected = the copy's own pre-run list with only the interpreter rule changed,
    # so this holds whatever state the list was in before the test ran.
    record(f"{tag}: other allow rules kept in order", allow_kept(old_allow, new_allow),
           f"{new_allow} vs expected {expected_allow(old_allow)}")
    # The check can see the fault: a dropped, reordered or added rule fails it, and
    # so does a bare interpreter rule (left bare where the launcher rule should be,
    # or slipped back in when the list holds no launcher rule).
    broken = {
        "a rule dropped": new_allow[:-1],
        "two rules swapped": new_allow[1:2] + new_allow[:1] + new_allow[2:],
        "a rule added": new_allow + ["Bash(curl *)"],
    }
    if NEW_ALLOW in new_allow:
        broken["the interpreter rule left bare"] = [OLD_ALLOW if x == NEW_ALLOW else x for x in new_allow]
        name = "a dropped, swapped, added or still-bare allow rule"
    else:
        broken["a bare interpreter rule slipped back in"] = new_allow[:1] + [OLD_ALLOW] + new_allow[1:]
        name = "a dropped, swapped, added or reintroduced bare allow rule"
    caught = [k for k, v in broken.items() if v != new_allow and not allow_kept(old_allow, v)]
    record(f"{tag}: negative: {name} FAILS the kept-in-order check",
           len(new_allow) >= 2 and len(caught) == len(broken) == 4
           and (NEW_ALLOW in new_allow or not require_scripts_rule),
           f"caught={caught}")


def scripts_rule_fixture_case(gate, tmp: Path) -> None:
    """The real settings with the broad rule put back, to prove the conversion.

    The real file no longer carries Bash(python scripts/*) (removed on purpose in
    the v0.38.0 release review), so the in-place conversion and the still-bare
    negative are proven here, on a copy of the real settings with the bare rule
    inserted between two other rules."""
    case = tmp / "scripts-rule"
    (case / ".claude").mkdir(parents=True)
    s, m = case / ".claude" / "settings.json", case / ".mcp.json"
    data = json.loads(REAL_SETTINGS.read_text(encoding="utf-8-sig"))
    perms = data.get("permissions") if isinstance(data.get("permissions"), dict) else {}
    others = [x for x in perms.get("allow", []) if x not in (OLD_ALLOW, NEW_ALLOW)]
    if len(others) < 2:
        others = ["Read", "Bash(git status)"]
    pre_allow = others[:1] + [OLD_ALLOW] + others[1:]
    perms["allow"] = pre_allow
    data["permissions"] = perms
    s.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    shutil.copy2(REAL_MCP, m)
    record("scripts-rule fixture: bare rule sits between two other rules before the run",
           pre_allow[1:2] == [OLD_ALLOW] and len(pre_allow) >= 3 and NEW_ALLOW not in pre_allow, str(pre_allow))
    r = run_tool("--settings", s, "--mcp", m, "--write")
    record("scripts-rule fixture: --write exit 0", r.returncode == 0, f"rc={r.returncode} {r.stderr.strip()[:300]}")
    new_s = json.loads(s.read_text(encoding="utf-8"))
    new_allow = (new_s.get("permissions") or {}).get("allow", [])
    record("scripts-rule fixture: the launcher rule is exactly where the bare rule was",
           new_allow == others[:1] + [NEW_ALLOW] + others[1:], str(new_allow))
    allow_checks("scripts-rule fixture", pre_allow, new_allow, require_scripts_rule=True)
    record("scripts-rule fixture: gate D39 PASS on the result", gate_check(gate, s, m).status == "PASS")


# ---- the end to end case on copies of the real files ----

def real_files_case(gate, tmp: Path) -> None:
    case = tmp / "real"
    (case / ".claude").mkdir(parents=True)
    s, m = case / ".claude" / "settings.json", case / ".mcp.json"
    shutil.copy2(REAL_SETTINGS, s)
    shutil.copy2(REAL_MCP, m)
    orig_s = json.loads(s.read_text(encoding="utf-8"))
    orig_m = json.loads(m.read_text(encoding="utf-8"))

    # Formatting survives: the tool's renderer reproduces each real file byte for
    # byte when nothing changes, so a migration diff shows only the real changes.
    spec = importlib.util.spec_from_file_location("charon_launcher_migrate_under_test", TOOL)
    tool = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = tool
    spec.loader.exec_module(tool)
    for f in (REAL_SETTINGS, REAL_MCP):
        raw = f.read_bytes().decode("utf-8")
        data = json.loads(raw[1:] if raw.startswith(chr(0xFEFF)) else raw)
        record(f"renderer round-trips {f.relative_to(REPO).as_posix()} byte for byte",
               tool._render(data, tool._style_of(raw)) == raw)
    odd = chr(0xFEFF) + json.dumps({"a": [1, {"b": "x" + chr(0xE9)}]}, indent=4, ensure_ascii=False).replace("\n", "\r\n")
    record("renderer keeps a BOM, CRLF, 4-space indent and literal non-ASCII",
           tool._render(json.loads(odd[1:]), tool._style_of(odd)) == odd)

    before = gate_check(gate, s, m)
    already = before.status == "PASS"
    record("unmigrated copies: the gate's D39 check FAILS (it can see the fault)",
           before.status == "FAIL" or already, f"{before.status}: {before.detail}")

    snap = state(s, m)
    r = run_tool("--settings", s, "--mcp", m)
    record("dry run: exit 0", r.returncode == 0, f"rc={r.returncode} {r.stderr.strip()[:200]}")
    record("dry run: writes nothing", state(s, m) == snap)
    record("dry run: prints a unified diff (or says no changes)",
           ("+++" in r.stdout and "@@" in r.stdout) or (already and "no changes" in r.stdout),
           r.stdout[:200])

    r = run_tool("--settings", s, "--mcp", m, "--write")
    record("--write: exit 0", r.returncode == 0, f"rc={r.returncode} {r.stderr.strip()[:300]}")
    new_s = json.loads(s.read_text(encoding="utf-8"))
    new_m = json.loads(m.read_text(encoding="utf-8"))

    after = gate_check(gate, s, m)
    record("migrated copies: the gate's D39 check PASSES", after.status == "PASS",
           f"{after.status}: {after.detail} {after.findings[:3]}")
    findings, warnings, seen = gate.bare_interpreter_findings(new_s, new_m)
    record("migrated copies: no findings, no warnings, commands inspected",
           not findings and not warnings and seen > 0, f"{findings[:2]} {warnings[:2]} seen={seen}")
    cmds = [h["command"] for gs in new_s.get("hooks", {}).values() for g in gs for h in g.get("hooks", [])]
    bad_shape = [c for c in cmds if not gate.LAUNCHER_HOOK_RE.match(c)]
    record(f"all {len(cmds)} hook commands match the gate's D40 launcher shape", cmds and not bad_shape,
           str(bad_shape[:2]))

    record("hook scripts and arguments unchanged, hook by hook",
           hook_payloads(orig_s) == hook_payloads(new_s),
           f"{hook_payloads(orig_s)[:2]} vs {hook_payloads(new_s)[:2]}")
    record("MCP server scripts and arguments unchanged, server by server",
           server_payloads(orig_s, orig_m) == server_payloads(new_m) and server_payloads(new_m),
           f"{server_payloads(orig_s, orig_m)} vs {server_payloads(new_m)}")
    moved = set((orig_s.get("mcpServers") or {}))
    record("mcpServers moved: none left in settings, all present in .mcp.json",
           "mcpServers" not in new_s and moved <= set(new_m.get("mcpServers", {})),
           f"moved={sorted(moved)} mcp={sorted(new_m.get('mcpServers', {}))}")
    record("keys the tool does not own are unchanged (settings, incl. deny list)", unowned(orig_s) == unowned(new_s))
    record(".mcp.json keys other than mcpServers unchanged",
           {k: v for k, v in orig_m.items() if k != "mcpServers"} == {k: v for k, v in new_m.items() if k != "mcpServers"})
    old_allow = (orig_s.get("permissions") or {}).get("allow", [])
    new_allow = (new_s.get("permissions") or {}).get("allow", [])
    allow_checks("real copy", old_allow, new_allow, require_scripts_rule=False)
    pre = ["Read", OLD_ALLOW, "Bash(git status)"]
    record("expected list for an unmigrated file: only the interpreter rule changes, in place",
           expected_allow(pre) == ["Read", NEW_ALLOW, "Bash(git status)"]
           and expected_allow(["Read", NEW_ALLOW]) == ["Read", NEW_ALLOW]
           and expected_allow(["Read", "Bash(git status)"]) == ["Read", "Bash(git status)"],
           str(expected_allow(pre)))

    snap = state(s, m)
    r = run_tool("--settings", s, "--mcp", m, "--write")
    record("second --write: exit 0 and says no changes", r.returncode == 0 and "no changes" in r.stdout,
           f"rc={r.returncode} {r.stdout[:160]}")
    record("second --write: bytes and mtimes unchanged (idempotent)", state(s, m) == snap)


# ---- fixtures for the conversions and refusals ----

def fixtures_case(gate, tmp: Path) -> None:
    d = tmp / "fx"
    d.mkdir()
    s, m = d / "settings.json", d / "mcp.json"

    def put(settings, mcp=None):
        s.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
        if mcp is None:
            if m.exists():
                m.unlink()
        else:
            m.write_text(json.dumps(mcp, indent=2) + "\n", encoding="utf-8")

    # positive: statusLine, py -3, python3.exe, arguments, extra server keys, no .mcp.json yet
    settings = {
        "hooks": {"UserPromptSubmit": [{"hooks": [
            {"type": "command", "command": 'python3 "${CLAUDE_PROJECT_DIR}/scripts/hooks/a.py" --part 1', "timeout": 9},
            {"type": "command", "command": "py -3 scripts/b.py x=y"},
            {"type": "command", "command": "C:/Python312/python.exe ./scripts/c.py"},
            {"type": "command", "command": "echo hi"},
        ]}]},
        "statusLine": {"type": "command", "command": "python scripts/statusline.py"},
        "mcpServers": {"srv": {"type": "stdio", "command": "python3",
                               "args": ["${CLAUDE_PROJECT_DIR}/scripts/mcp/s.py", "--flag", "two words"],
                               "env": {"K": "V"}}},
        "permissions": {"allow": ["Read", "Bash(python:*)", "Bash(python3 scripts/x.py *)", "Bash(git status)"]},
    }
    put(settings)
    pre = gate_check(gate, s, d / "none.json")
    record("fixture before migration: gate D39 FAILS", pre.status == "FAIL", f"{pre.status}: {pre.detail}")
    r = run_tool("--settings", s, "--mcp", m, "--write")
    ok = r.returncode == 0 and m.is_file()
    record("fixture: converts and creates .mcp.json", ok, f"rc={r.returncode} {r.stderr.strip()[:200]}")
    if ok:
        ns, nm = json.loads(s.read_text(encoding="utf-8")), json.loads(m.read_text(encoding="utf-8"))
        hk = ns["hooks"]["UserPromptSubmit"][0]["hooks"]
        record("fixture: hook args kept, other hook keys kept",
               hk[0] == {"type": "command", "timeout": 9,
                         "command": 'sh "${CLAUDE_PROJECT_DIR}/scripts/hook" scripts/hooks/a.py --part 1'},
               str(hk[0]))
        record("fixture: py -3 and python.exe converted, echo untouched",
               [h["command"] for h in hk[1:]] == ['sh "${CLAUDE_PROJECT_DIR}/scripts/hook" scripts/b.py x=y',
                                                 'sh "${CLAUDE_PROJECT_DIR}/scripts/hook" scripts/c.py', "echo hi"],
               str([h["command"] for h in hk[1:]]))
        record("fixture: statusLine converted",
               ns["statusLine"]["command"] == 'sh "${CLAUDE_PROJECT_DIR}/scripts/hook" scripts/statusline.py')
        record("fixture: MCP server moved, args (with a space) and env kept",
               nm == {"mcpServers": {"srv": {"type": "stdio", "command": "sh",
                                             "args": ["${CLAUDE_PROJECT_DIR}/scripts/hook", "scripts/mcp/s.py",
                                                      "--flag", "two words"], "env": {"K": "V"}}}}
               and "mcpServers" not in ns, json.dumps(nm)[:200])
        record("fixture: Bash(python:*) dropped, scripts rule replaced, others kept",
               ns["permissions"]["allow"] == ["Read", "Bash(sh scripts/hook scripts/x.py *)", "Bash(git status)"],
               str(ns["permissions"]["allow"]))
        record("fixture: gate D39 PASS on the result", gate_check(gate, s, m).status == "PASS")
        snap = state(s, m)
        r = run_tool("--settings", s, "--mcp", m, "--write")
        record("fixture: second run changes nothing", r.returncode == 0 and state(s, m) == snap)

    # unresolved: exit 1, nothing written
    def hook(cmd):
        return {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": cmd}]}]}}
    good = 'python "${CLAUDE_PROJECT_DIR}/scripts/hooks/ok.py"'
    unresolved = {
        "interpreter flag (python -u)": (hook("python -u scripts/x.py"), None),
        "script outside scripts/": (hook("python tools/x.py"), None),
        "script with .. steps": (hook("python scripts/../x.py"), None),
        "argument holding $HOME": (hook('python scripts/x.py "$HOME/a"'), None),
        "argument holding a chain operator": (hook("python scripts/x.py && curl x"), None),
        ".py run by node": (hook("node x.js scripts/x.py"), None),
        "python -m module server": (hook(good), {"mcpServers": {"s": {"command": "python", "args": ["-m", "x"]}}}),
        "server defined differently in both files": (
            dict(hook(good), mcpServers={"s": {"command": "python", "args": ["scripts/mcp/a.py"]}}),
            {"mcpServers": {"s": {"command": "python", "args": ["scripts/mcp/b.py"]}}}),
    }
    for label, (st, mc) in unresolved.items():
        put(st, mc)
        snap = state(s, m)
        r = run_tool("--settings", s, "--mcp", m, "--write")
        record(f"unresolved '{label}': exit 1, UNRESOLVED named, nothing written",
               r.returncode == 1 and "UNRESOLVED" in r.stderr and state(s, m) == snap,
               f"rc={r.returncode} {r.stderr.strip()[:200]}")

    # bad JSON in either file: exit 2, clear message, nothing written
    for which in ("settings", "mcp"):
        put(hook(good), {"mcpServers": {}})
        (s if which == "settings" else m).write_text('{"hooks": {', encoding="utf-8")
        snap = state(s, m)
        r = run_tool("--settings", s, "--mcp", m, "--write")
        record(f"bad JSON in {which}: exit 2, 'not valid JSON' with line and column, nothing written",
               r.returncode == 2 and "not valid JSON" in r.stderr and "line 1" in r.stderr and state(s, m) == snap,
               f"rc={r.returncode} {r.stderr.strip()[:200]}")
    put(hook(good))
    s.write_text("[1, 2]", encoding="utf-8")
    r = run_tool("--settings", s, "--mcp", m)
    record("top-level JSON that is not an object: exit 2", r.returncode == 2, f"rc={r.returncode}")
    r = run_tool("--settings", d / "missing.json", "--mcp", m)
    record("missing settings file: exit 2", r.returncode == 2 and "not found" in r.stderr, r.stderr.strip()[:120])


def links_case(tmp: Path) -> None:
    d = tmp / "links"
    real = d / "real"
    real.mkdir(parents=True)
    target = real / "settings.json"
    target.write_text(json.dumps({"hooks": {"Stop": [{"hooks": [
        {"type": "command", "command": "python scripts/x.py"}]}]}}), encoding="utf-8")
    m = d / "mcp.json"
    tested = 0

    # a file symlink (needs Developer Mode or admin on Windows)
    link = d / "settings-link.json"
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError) as exc:
        print(f"    note: file symlink not creatable here ({type(exc).__name__}); junction case covers Windows")
    else:
        tested += 1
        snap = state(target)
        r = run_tool("--settings", link, "--mcp", m, "--write")
        record("settings path that is a symlink: refused, exit 2, nothing written",
               r.returncode == 2 and "symlink or junction" in r.stderr and state(target) == snap and not m.exists(),
               f"rc={r.returncode} {r.stderr.strip()[:160]}")
        r = run_tool("--settings", target, "--mcp", link, "--write")
        record("mcp path that is a symlink: refused, exit 2", r.returncode == 2 and "symlink or junction" in r.stderr,
               f"rc={r.returncode}")

    # a directory junction on Windows, made with the standard library's _winapi (no shell)
    if os.name == "nt":
        try:
            import _winapi
            junction = d / "junction"
            _winapi.CreateJunction(str(real), str(junction))
        except Exception as exc:  # noqa: BLE001
            record("junction created for the refusal test", False, f"{type(exc).__name__}: {exc}")
        else:
            tested += 1
            snap = state(target)
            r = run_tool("--settings", junction / "settings.json", "--mcp", junction / "mcp.json", "--write")
            record("settings file inside a junction: refused, exit 2, nothing written",
                   r.returncode == 2 and "symlink or junction" in r.stderr and state(target) == snap
                   and not (real / "mcp.json").exists(), f"rc={r.returncode} {r.stderr.strip()[:160]}")
            os.rmdir(junction)  # removes the junction only, never its target
    record("at least one link refusal was exercised", tested > 0, "no symlink or junction could be made")


def mutation_case(gate, tmp: Path) -> None:
    """Break the tool; the assertions used above must notice."""
    src = TOOL.read_text(encoding="utf-8")
    mutants = {
        "MCP servers left on bare python": ('new[k] = "sh"', "new[k] = command"),
        "hook arguments dropped": ('" ".join([HOOK_PREFIX, script, *args])', '" ".join([HOOK_PREFIX, script])'),
        "scripts allow rule left bare": ('return "replace", f"Bash(sh {LAUNCHER_REL} {rest})"',
                                         'return "keep", None'),
    }
    for label, (old, new) in mutants.items():
        d = tmp / ("mut-" + label.split()[0])
        (d / "scripts").mkdir(parents=True)
        (d / ".claude").mkdir()
        tool = d / "scripts" / "launcher_migrate.py"
        tool.write_text(src.replace(old, new), encoding="utf-8")
        s, m = d / ".claude" / "settings.json", d / ".mcp.json"
        # A fixed bare-python fixture (not the real files, which may already be
        # migrated): one hook with an argument to lose, one server to leave bare.
        orig_s = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
            {"type": "command", "command": 'python "${CLAUDE_PROJECT_DIR}/scripts/hooks/deny-destructive.py" --probe 1'}]}]},
            "mcpServers": {"v": {"type": "stdio", "command": "python",
                                 "args": ["${CLAUDE_PROJECT_DIR}/scripts/mcp/v.py"]}},
            "permissions": {"allow": ["Read", OLD_ALLOW, "Bash(git status)"]}}
        s.write_text(json.dumps(orig_s, indent=2), encoding="utf-8")
        m.write_text(json.dumps({"mcpServers": {"w": {"command": "python", "args": ["scripts/mcp/w.py"]}}}),
                     encoding="utf-8")
        r = run_tool("--settings", s, "--mcp", m, "--write", tool=tool)
        new_s = json.loads(s.read_text(encoding="utf-8"))
        old_allow = orig_s["permissions"]["allow"]
        new_allow = (new_s.get("permissions") or {}).get("allow", [])
        caught = (gate_check(gate, s, m).status != "PASS"
                  or hook_payloads(orig_s) != hook_payloads(new_s)
                  or not allow_kept(old_allow, new_allow))
        record(f"mutation caught: {label}", old in src and caught, f"rc={r.returncode}")


def main() -> int:
    for f in (TOOL, GATE, REAL_SETTINGS, REAL_MCP):
        if not f.is_file():
            record(f"exists: {f.relative_to(REPO)}", False)
            return report()
    real_before = state(REAL_SETTINGS, REAL_MCP)
    gate = load_gate()
    saved = (gate.SETTINGS_FILE, gate.MCP_FILE)
    tmp = Path(tempfile.mkdtemp(prefix="charon-test-launcher-migrate-"))
    try:
        real_files_case(gate, tmp)
        scripts_rule_fixture_case(gate, tmp)
        fixtures_case(gate, tmp)
        links_case(tmp)
        mutation_case(gate, tmp)
    finally:
        gate.SETTINGS_FILE, gate.MCP_FILE = saved
        shutil.rmtree(tmp, ignore_errors=True)
    record("temp folder removed", not tmp.exists())
    record("the real .claude/settings.json and .mcp.json were not touched",
           state(REAL_SETTINGS, REAL_MCP) == real_before)
    return report()


def report() -> int:
    passed = sum(1 for _, ok, _ in results if ok)
    failed = len(results) - passed
    for name, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    print(f"\n{passed} passed, {failed} failed ({len(results)} checks)")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
