#!/usr/bin/env python3
"""Tests for laptop_check.py.

Every case runs against a stand-in repo and a HOME built in a temporary folder
outside this repo. The real user settings are never read or written (the stand-in
HOME is passed in, and every subprocess gets HOME and USERPROFILE pointed at it),
and git is never run (a fake `git status` is passed in). One case reads a temporary
COPY of this repo's .claude/ and scripts/ to prove the checks cope with the real
config; it fires no hooks.

    python scripts/test_laptop_check.py
"""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.dont_write_bytecode = True  # importing laptop_check must not drop a .pyc into the repo
HERE = Path(__file__).resolve().parent
REAL_REPO = HERE.parent
sys.path.insert(0, str(HERE))
import laptop_check as L  # noqa: E402

SENTINEL = "SENTINEL-VALUE-DO-NOT-PRINT"
results: list[tuple[str, bool]] = []


def check(name: str, cond: bool) -> None:
    results.append((name, bool(cond)))


def _forbidden_git(_repo: Path) -> tuple[int, str]:
    raise AssertionError("test reached for real git")


L.default_git_status = _forbidden_git  # type: ignore[assignment]


def clean_git(_repo: Path) -> tuple[int, str]:
    return 0, ""


OK_HOOK = "import sys, json\njson.load(sys.stdin)\nsys.exit(0)\n"
LOGGER_HOOK = (
    "import os, sys, json\n"
    "from pathlib import Path\n"
    "json.load(sys.stdin)\n"
    "d = Path(os.environ['CLAUDE_PROJECT_DIR']) / 'state' / 'verdict' / '_test'\n"
    "d.mkdir(parents=True, exist_ok=True)\n"
    "(d / 'probe.jsonl').write_text('{\"test\": true}\\n', encoding='utf-8')\n"
)
CRASH_HOOK = "raise RuntimeError('boom')\n"
WIRING_STUB = (
    "import json, sys\n"
    "from pathlib import Path\n"
    "assert '--check' in sys.argv\n"
    "p = Path.home() / '.claude' / 'settings.json'\n"
    "try:\n"
    "    d = json.loads(p.read_text(encoding='utf-8'))\n"
    "except Exception:\n"
    "    d = {}\n"
    "a = 'CLAUDE_CODE_PLUGIN_DIRS' in (d.get('env') or {})\n"
    "s = 'statusLine' in d\n"
    "print('Charon wiring (check) for ' + str(p))\n"
    "print('  Agent Org: ' + ('OK' if a else 'NOT WIRED') + ' - ' + json.dumps(d.get('env')))\n"
    "print('  Status line: ' + ('OK' if s else 'NOT WIRED') + ' - ' + json.dumps(d.get('statusLine')))\n"
    "sys.exit(0 if a and s else 1)\n"
)


def launcher_cmd(rel: str) -> str:
    return f'sh "${{CLAUDE_PROJECT_DIR}}/scripts/hook" {rel}'


def make_fixture(root: Path, *, launcher: bool = True, zeus: bool = True, wiring: bool = True,
                 settings_home: bool = True, hook_cmds: dict | None = None) -> tuple[Path, Path]:
    repo = root / "repo"
    home = root / "home"
    (repo / "scripts" / "hooks").mkdir(parents=True)
    (repo / "scripts" / "mcp").mkdir()
    (repo / ".claude" / "rules").mkdir(parents=True)
    (repo / ".claude" / "agents").mkdir()
    home.mkdir()
    shutil.copy2(HERE / "load-rules.py", repo / "scripts" / "load-rules.py")
    (repo / "scripts" / "hooks" / "ok_hook.py").write_text(OK_HOOK, encoding="utf-8")
    (repo / "scripts" / "hooks" / "test_logger.py").write_text(LOGGER_HOOK, encoding="utf-8")
    (repo / "scripts" / "hooks" / "crash_hook.py").write_text(CRASH_HOOK, encoding="utf-8")
    (repo / "scripts" / "mcp" / "server.py").write_text("# stand-in MCP server\n", encoding="utf-8")
    if launcher:
        py = Path(sys.executable).as_posix()
        sh = ('#!/bin/sh\nroot="$(cd "$(dirname "$0")/.." && pwd)"\nrel="$1"; shift\n'
              f'exec "{py}" "$root/$rel" "$@"\n')
        (repo / "scripts" / "hook").write_bytes(sh.encode("utf-8"))
        cmd = f'@echo off\r\n"{sys.executable}" "%~dp0..\\%~1"\r\n'
        (repo / "scripts" / "hook.cmd").write_bytes(cmd.encode("utf-8"))
    if wiring:
        (repo / "scripts" / "post_install_wiring.py").write_text(WIRING_STUB, encoding="utf-8")
    rules = list(L.GATE_ALWAYS_RULES) + ([L.ZEUS_RULE] if zeus else [])
    for r in rules:
        (repo / ".claude" / "rules" / r).write_text(f"---\nalways: true\n---\n\nRule {r}.\n", encoding="utf-8")
    (repo / ".claude" / "rules" / "keyword-only.md").write_text(
        "---\nkeywords:\n  - something\n---\n\nKeyword rule.\n", encoding="utf-8")
    (repo / ".claude" / "agents" / "README.md").write_text("# Agents\n", encoding="utf-8")
    (repo / ".claude" / "agents" / "alpha.md").write_text(
        "---\nname: alpha\ndescription: Does alpha things.\ntools: Read\n---\n\nBody.\n", encoding="utf-8")
    (repo / ".claude" / "agents" / "beta.md").write_text(
        "---\nname: beta\ndescription: >\n  Folded description.\n---\n\nBody.\n", encoding="utf-8")
    cmds = hook_cmds or {
        "UserPromptSubmit": [(None, launcher_cmd("scripts/load-rules.py"))],
        "PreToolUse": [("Edit|Write", launcher_cmd("scripts/hooks/ok_hook.py"))],
        "Stop": [(None, launcher_cmd("scripts/hooks/test_logger.py"))],
    }
    hooks = {}
    for event, rows in cmds.items():
        hooks[event] = []
        for matcher, command in rows:
            group = {"hooks": [{"type": "command", "command": command}]}
            if matcher:
                group["matcher"] = matcher
            hooks[event].append(group)
    (repo / ".claude" / "settings.json").write_text(json.dumps({"hooks": hooks}, indent=2), encoding="utf-8")
    (repo / ".mcp.json").write_text(json.dumps({"mcpServers": {"stand-in": {
        "type": "stdio", "command": "sh",
        "args": ["${CLAUDE_PROJECT_DIR}/scripts/hook", "scripts/mcp/server.py"]}}}), encoding="utf-8")
    if settings_home:
        (home / ".claude").mkdir()
        (home / ".claude" / "settings.json").write_text(json.dumps({
            "env": {"CLAUDE_CODE_PLUGIN_DIRS": f"/x/plugins/agent-org-reporter:{SENTINEL}"},
            "statusLine": {"type": "command", "command": f"sh /x/scripts/hook scripts/statusline.py {SENTINEL}"},
            "apiKeyHelper": SENTINEL}), encoding="utf-8")
    return repo, home


def by_num(checks: list) -> dict:
    return {c.num: c for c in checks}


def text_of(c) -> str:
    return " | ".join([c.detail, *c.items])


def run(repo: Path, home: Path, git=clean_git) -> dict:
    return by_num(L.run_checks(repo, home=home, timeout=30, git_status=git))


def case(fn) -> None:
    tmp = Path(tempfile.mkdtemp(prefix="test-laptop-check-"))
    try:
        fn(tmp)
    except Exception as exc:  # an exception is a failed case, never a silent pass
        check(f"{fn.__name__} raised {type(exc).__name__}: {exc}", False)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ---------- positive ----------

def test_all_good(tmp: Path) -> None:
    repo, home = make_fixture(tmp)
    before = L._snapshot(repo)
    home_before = L._snapshot(home)
    checks = L.run_checks(repo, home=home, timeout=30, git_status=clean_git)
    c = by_num(checks)
    check("positive: 7 checks returned", sorted(c) == [1, 2, 3, 4, 5, 6, 7])
    for n in range(1, 8):
        check(f"positive: check {n} passes ({text_of(c[n])[:200]})", c[n].ok)
    check("positive: interpreter detail names the launcher run", "launcher runs" in c[1].detail)
    check("positive: 4 commands counted", c[2].detail.startswith("4 of 4"))
    check("positive: 3 of 3 hooks fired", c[3].detail.startswith("3 of 3"))
    check("positive: 5 always-fire rules delivered", c[4].detail.startswith("5 of 5"))
    check("positive: Agent Org OK and Status line OK reported",
          "Agent Org: OK" in c[5].items and "Status line: OK" in c[5].items)
    check("positive: 2 agents parse (folded description counts)", c[6].detail.startswith("2 of 2"))
    wrote = [it for it in c[3].items if "test_logger.py" in it and "state/verdict/_test/probe.jsonl" in it]
    check("positive: a hook writing a test log is named, with where", len(wrote) == 1 and "(test-marked)" in wrote[0])
    check("positive: the repo itself is unchanged", L._snapshot(repo) == before)
    check("positive: the stand-in HOME is unchanged", L._snapshot(home) == home_before)
    report = L.render(checks, repo)
    as_json = json.dumps([x.to_dict() for x in checks])
    check("positive: no settings value is printed (text)", SENTINEL not in report)
    check("positive: no settings value is printed (json)", SENTINEL not in as_json)
    check("positive: report ends with the all-pass line", report.rstrip().endswith("This install works."))


# ---------- negatives ----------

def test_broken_hook_path(tmp: Path) -> None:
    repo, home = make_fixture(tmp, hook_cmds={
        "UserPromptSubmit": [(None, launcher_cmd("scripts/load-rules.py"))],
        "PreToolUse": [("Edit", launcher_cmd("scripts/hooks/does-not-exist.py"))]})
    c = run(repo, home)
    check("broken path: check 2 fails", not c[2].ok)
    check("broken path: check 2 names the script and the reason",
          any("does-not-exist.py" in it and "target script does not exist" in it for it in c[2].items))
    check("broken path: check 3 fails, naming the hook",
          not c[3].ok and any("does-not-exist.py" in it and "no script to fire" in it for it in c[3].items))
    check("broken path: unrelated checks still pass", c[4].ok and c[6].ok and c[7].ok)


def test_bare_python(tmp: Path) -> None:
    repo, home = make_fixture(tmp, hook_cmds={
        "UserPromptSubmit": [(None, launcher_cmd("scripts/load-rules.py"))],
        "Stop": [(None, 'python "${CLAUDE_PROJECT_DIR}/scripts/hooks/ok_hook.py"')]})
    c = run(repo, home)
    check("bare python: check 2 fails", not c[2].ok)
    check("bare python: reason names bare python and row 2",
          any("ok_hook.py" in it and "bare `python`" in it and "row 2" in it for it in c[2].items))
    check("bare python: the hook itself still fires", c[3].ok)


def test_mcp_bare_python(tmp: Path) -> None:
    repo, home = make_fixture(tmp)
    (repo / ".mcp.json").write_text(json.dumps({"mcpServers": {"s": {
        "command": "python3", "args": ["${CLAUDE_PROJECT_DIR}/scripts/mcp/server.py"]}}}), encoding="utf-8")
    c = run(repo, home)
    check("mcp bare python: check 2 fails naming the server",
          not c[2].ok and any(".mcp.json mcpServers.s" in it and "bare `python3`" in it for it in c[2].items))


def test_missing_always_rule(tmp: Path) -> None:
    repo, home = make_fixture(tmp)
    (repo / ".claude" / "rules" / "no-assumptions.md").unlink()
    c = run(repo, home)
    check("missing rule: check 4 fails", not c[4].ok)
    check("missing rule: reason names the file",
          any("no-assumptions.md is missing" in it for it in c[4].items))
    check("missing rule: and says it was not delivered",
          any("no-assumptions.md was not delivered" in it for it in c[4].items))


def test_untagged_always_rule(tmp: Path) -> None:
    repo, home = make_fixture(tmp)
    (repo / ".claude" / "rules" / "confidence-tags.md").write_text("---\nkeywords:\n  - x\n---\n\nBody\n",
                                                                     encoding="utf-8")
    c = run(repo, home)
    check("untagged rule: check 4 fails, naming the tag",
          not c[4].ok and any("confidence-tags.md is not tagged `always: true`" in it for it in c[4].items))


def test_crashing_hook(tmp: Path) -> None:
    repo, home = make_fixture(tmp, hook_cmds={
        "UserPromptSubmit": [(None, launcher_cmd("scripts/load-rules.py"))],
        "SessionStart": [(None, launcher_cmd("scripts/hooks/crash_hook.py"))]})
    c = run(repo, home)
    check("crashing hook: check 3 fails, naming hook and error",
          not c[3].ok and any("crash_hook.py" in it and "RuntimeError" in it for it in c[3].items))


def test_missing_contract_pieces(tmp: Path) -> None:
    repo, home = make_fixture(tmp, launcher=False, zeus=False, wiring=False, settings_home=False)
    checks = L.run_checks(repo, home=home, timeout=30, git_status=clean_git)  # must not raise
    c = by_num(checks)
    check("missing pieces: all 7 checks still returned", sorted(c) == [1, 2, 3, 4, 5, 6, 7])
    check("missing pieces: no check crashed",
          not any("the check itself failed" in it for x in checks for it in x.items))
    check("missing pieces: check 1 FAIL names row 2",
          not c[1].ok and any("scripts/hook is missing" in it and "row 2" in it for it in c[1].items))
    check("missing pieces: check 2 FAIL names row 2", not c[2].ok and "row 2" in text_of(c[2]))
    check("missing pieces: check 3 still fires hooks directly, says so",
          "fired with this Python directly" in c[3].detail)
    check("missing pieces: check 4 FAIL names zeus-first and row 4",
          not c[4].ok and any("zeus-first.md is missing" in it and "row 4" in it for it in c[4].items))
    check("missing pieces: check 5 FAIL names rows 3 and 31",
          not c[5].ok and any("post_install_wiring.py is missing" in it and "rows 3 and 31" in it
                              for it in c[5].items))
    check("missing pieces: check 6 and 7 unaffected", c[6].ok and c[7].ok)


def test_fallback_wiring_reads_keys_only(tmp: Path) -> None:
    repo, home = make_fixture(tmp, wiring=False)
    c = run(repo, home)
    check("fallback wiring: reports both keys as yes",
          any("CLAUDE_CODE_PLUGIN_DIRS lists the Agent Org plugin: yes" in it for it in c[5].items)
          and any("statusLine points at Charon's status line: yes" in it for it in c[5].items))
    check("fallback wiring: no value printed", SENTINEL not in text_of(c[5]))


def test_not_wired(tmp: Path) -> None:
    repo, home = make_fixture(tmp, settings_home=False)
    c = run(repo, home)
    check("not wired: check 5 fails with the fix command",
          not c[5].ok and any("post_install_wiring.py --mode update" in it for it in c[5].items))


def test_bad_agent(tmp: Path) -> None:
    repo, home = make_fixture(tmp)
    (repo / ".claude" / "agents" / "gamma.md").write_text("---\nname: gamma\n---\n\nBody\n", encoding="utf-8")
    c = run(repo, home)
    check("bad agent: check 6 fails naming description",
          not c[6].ok and any("gamma.md: no description" in it for it in c[6].items))


def test_git_dirty_and_broken(tmp: Path) -> None:
    repo, home = make_fixture(tmp)
    c = run(repo, home, git=lambda _r: (0, " M CLAUDE.md\n?? new.txt\n"))
    check("dirty tree: check 7 fails with the count", not c[7].ok and "2 change(s)" in c[7].detail)

    def boom(_r):
        raise OSError("no git")
    c = run(repo, home, git=boom)
    check("broken git runner: check 7 FAIL, not an exception",
          not c[7].ok and any("could not run" in it for it in c[7].items))


# ---------- negatives for the W2g review (M1, M2, M3, secret filter) ----------

EVIL_HOOK = (
    "from pathlib import Path\n"
    "Path(__file__).with_name('fired.txt').write_text('fired', encoding='utf-8')\n"
)
ENV_VARS_REDIRECTED = ("CLAUDE_MEMORY_DIR", "HARNESS_CAPTURE_ROOT", "CHARON_ROOT", "TEMP", "TMP",
                       "TMPDIR", "APPDATA", "LOCALAPPDATA", "XDG_CONFIG_HOME", "XDG_DATA_HOME",
                       "XDG_CACHE_HOME", "XDG_STATE_HOME", "XDG_RUNTIME_DIR")
ENV_WRITER_HOOK = (
    "import os, sys, json\n"
    "from pathlib import Path\n"
    "json.load(sys.stdin)\n"
    f"names = {list(ENV_VARS_REDIRECTED)!r}\n"
    "missing = [n for n in names if not os.environ.get(n)]\n"
    "if missing:\n"
    "    print('not set: ' + ' '.join(missing), file=sys.stderr)\n"
    "    sys.exit(4)\n"
    "for n in names:\n"
    "    d = Path(os.environ[n])\n"
    "    d.mkdir(parents=True, exist_ok=True)\n"
    "    (d / ('laptop-check-' + n.lower() + '.txt')).write_text('x', encoding='utf-8')\n"
)
SECRET_SNIFF_HOOK = (
    "import os, sys, json\n"
    "json.load(sys.stdin)\n"
    f"leaked = sorted(k for k, v in os.environ.items() if {SENTINEL!r} in v)\n"
    "if leaked:\n"
    "    print('leaked: ' + ' '.join(leaked), file=sys.stderr)\n"
    "    sys.exit(3)\n"
)
SECRET_NAMES = ("GITHUB_PAT", "DB_PASS", "MYSQL_PWD", "SENTRY_DSN", "SLACK_WEBHOOK_URL",
                "DATABASE_URL", "AZURE_STORAGE_SAS", "MY_CONNECTION_STRING", "SERVICE_API_KEY",
                "SIGNING_PRIVATE", "BEARER_VALUE", "SOME_JWT")


class _env:
    """Set environment variables for one case, and put the old values back after."""

    def __init__(self, values: dict[str, str]):
        self.values, self.old = values, {}

    def __enter__(self):
        for k, v in self.values.items():
            self.old[k] = os.environ.get(k)
            os.environ[k] = v
        return self

    def __exit__(self, *_exc):
        for k, old in self.old.items():
            if old is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = old


def _rooted_no_drive(p: Path) -> str:
    """`/x/y` form of an absolute path: on Windows the drive is dropped, so it is rooted but not absolute."""
    s = p.resolve().as_posix()
    return s[2:] if len(s) > 1 and s[1] == ":" else s


def _other_drive(p: Path) -> str:
    d = (p.resolve().drive[:1] or "C").upper()
    return "Q" if d != "Q" else "R"


def test_rel_rooted_escape(tmp: Path) -> None:
    """M1: a rooted script path like `/x` must not escape the temp copy in the launcher-missing fallback."""
    outside = tmp / "outside"
    outside.mkdir()
    (outside / "evil.py").write_text(EVIL_HOOK, encoding="utf-8")
    rooted = _rooted_no_drive(outside / "evil.py")
    repo, home = make_fixture(tmp, launcher=False, hook_cmds={
        "UserPromptSubmit": [(None, launcher_cmd("scripts/load-rules.py"))],
        "Stop": [(None, launcher_cmd(rooted))]})
    c = run(repo, home)
    check("M1 rooted: the outside script never ran", not (outside / "fired.txt").exists())
    check("M1 rooted: _rel refuses `/x`", L._rel("/x", repo) is None)
    check("M1 rooted: check 2 says the script is not inside the repo",
          not c[2].ok and any("is not a path inside the repo" in it for it in c[2].items))
    check("M1 rooted: check 3 fails, it did not fire", not c[3].ok)


def test_rel_drive_relative(tmp: Path) -> None:
    """M1: a drive-relative path like `D:x` must be refused, by _rel and by the fallback runner."""
    repo, home = make_fixture(tmp, launcher=False)
    drv = _other_drive(tmp)
    check("M1 drive-relative: _rel refuses `D:x`", L._rel(f"{drv}:x.py", repo) is None)
    check("M1 drive-relative: _rel refuses `D:/x`", L._rel(f"{drv}:/x.py", repo) is None)
    check("M1 drive-relative: _rel still accepts a plain repo path",
          L._rel("scripts/hooks/ok_hook.py", repo) == "scripts/hooks/ok_hook.py")
    ctx = L.Ctx(repo=repo, home=home, timeout=30, git_status=clean_git)
    try:
        L.build_sandbox(ctx)
        argv_d, why_d = L._fire_argv(ctx, f"{drv}:x.py", [])
        argv_r, why_r = L._fire_argv(ctx, "/x.py", [])
        argv_ok, _ = L._fire_argv(ctx, "scripts/hooks/ok_hook.py", [])
    finally:
        if ctx.tmp is not None:
            shutil.rmtree(ctx.tmp, ignore_errors=True)
    check("M1 drive-relative: fallback runner refuses `D:x`", argv_d is None and "outside" in why_d)
    check("M1 drive-relative: fallback runner refuses `/x`", argv_r is None and "outside" in why_r)
    check("M1 drive-relative: fallback runner still runs a repo script", argv_ok is not None)


def test_cmd_metachar_args(tmp: Path) -> None:
    """M2: on the hook.cmd route, an argument carrying a cmd metacharacter is refused, not run."""
    if os.name == "nt":
        marker = tmp / "pwned.txt"
        repo, home = make_fixture(tmp, hook_cmds={
            "UserPromptSubmit": [(None, launcher_cmd("scripts/load-rules.py"))],
            "Stop": [(None, launcher_cmd("scripts/hooks/ok_hook.py") + " x&cd.>" + marker.resolve().as_posix())]})
        (repo / "scripts" / "hook").unlink()  # force the hook.cmd route
        c = run(repo, home)
        check("M2 end to end: check 3 refuses the metacharacter argument",
              not c[3].ok and any("ok_hook.py" in it and "cmd metacharacter" in it for it in c[3].items))
        check("M2 end to end: the injected command never ran", not marker.exists())
    else:
        check("M2 end to end: skipped (hook.cmd route is Windows only)", True)
    for bad in ("x&echo", "a|b", "a>b", "a<b", "a^b", "%PATH%", "!x!", "a(b)", 'a"b', "a b", "a\nb"):
        check(f"M2 helper: `{bad!r}` is unsafe for hook.cmd", bool(L._cmd_unsafe([bad])))
    check("M2 helper: plain arguments are safe",
          not L._cmd_unsafe(["scripts/hooks/ok_hook.py", "--part", "1", "a=b", "x.y,z"]))


def test_cmd_metachar_script(tmp: Path) -> None:
    """M2: the script name itself goes through hook.cmd too, so `%VAR%` there is refused."""
    if os.name == "nt":
        repo, home = make_fixture(tmp)
        (repo / "scripts" / "hook").unlink()
        raised, argv = "", None
        try:
            argv = L.launcher_argv(repo, "scripts/%COMSPEC%.py", [])
        except Exception as exc:  # before the fix nothing is raised and argv comes back
            raised = str(exc)
        check("M2 script end to end: launcher_argv refuses it on the hook.cmd route",
              argv is None and "cmd metacharacter" in raised)
    else:
        check("M2 script end to end: skipped (Windows only)", True)
    check("M2 script: `%` in the script name is unsafe", bool(L._cmd_unsafe(["scripts/%COMSPEC%.py"])))


def test_env_redirected_to_sandbox(tmp: Path) -> None:
    """M3: memory, capture, Charon root, temp, appdata and XDG folders point into the temp sandbox."""
    real = tmp / "real"
    fake = {n: str(real / n.lower()) for n in ENV_VARS_REDIRECTED}
    repo, home = make_fixture(tmp, hook_cmds={
        "UserPromptSubmit": [(None, launcher_cmd("scripts/load-rules.py"))],
        "Stop": [(None, launcher_cmd("scripts/hooks/env_writer.py"))]})
    (repo / "scripts" / "hooks" / "env_writer.py").write_text(ENV_WRITER_HOOK, encoding="utf-8")
    with _env(fake):
        c = run(repo, home)
    landed = sorted(p.relative_to(real).as_posix() for p in real.rglob("*") if p.is_file()) if real.exists() else []
    check(f"M3: nothing landed in the real folders ({landed[:4]})", not landed)
    check(f"M3: the env-writing hook fired ({text_of(c[3])[:200]})", c[3].ok)
    check("M3: its writes are reported in the temporary copy",
          sum(1 for it in c[3].items if "env_writer.py" in it and "temporary copy" in it) >= len(ENV_VARS_REDIRECTED))
    check("M3: the repo is unchanged", not any("real repo changed" in it for it in c[3].items))


def test_secret_env_widened(tmp: Path) -> None:
    """Secret filter: names that look like keys, tokens, secrets or passwords never reach a hook."""
    for n in SECRET_NAMES:
        check(f"secret env: {n} is stripped", bool(L.SECRET_ENV.search(n)))
    for n in ("PATH", "PWD", "PATHEXT", "SYSTEMROOT", "HOME", "LANG", "TERM"):
        check(f"secret env: {n} is kept", not L.SECRET_ENV.search(n))
    repo, home = make_fixture(tmp, hook_cmds={
        "UserPromptSubmit": [(None, launcher_cmd("scripts/load-rules.py"))],
        "Stop": [(None, launcher_cmd("scripts/hooks/sniff.py"))]})
    (repo / "scripts" / "hooks" / "sniff.py").write_text(SECRET_SNIFF_HOOK, encoding="utf-8")
    with _env({n: SENTINEL for n in SECRET_NAMES}):
        env = L._safe_env({})
        c = run(repo, home)
    check("secret env: _safe_env drops every secret-shaped name", not any(n in env for n in SECRET_NAMES))
    check(f"secret env: no secret value reached the hook ({text_of(c[3])[:200]})", c[3].ok)


def test_real_repo_copy(tmp: Path) -> None:
    """The checks cope with this repo's real config (copied; no hook is fired)."""
    copy = tmp / "repo"
    copy.mkdir()
    shutil.copytree(REAL_REPO / ".claude", copy / ".claude", ignore=L._copy_ignore)
    shutil.copytree(REAL_REPO / "scripts", copy / "scripts", ignore=L._copy_ignore)
    if (REAL_REPO / ".mcp.json").is_file():
        shutil.copy2(REAL_REPO / ".mcp.json", copy / ".mcp.json")
    home = tmp / "home"
    home.mkdir()
    ctx = L.Ctx(repo=copy, home=home, timeout=30, git_status=clean_git)
    try:
        L.build_sandbox(ctx)
        cmds, problems = L.collect_commands(copy)
        c2 = L.check_commands(ctx, cmds, problems)
        c4 = L.check_rules(ctx)
        c6 = L.check_agents(ctx)
    finally:
        if ctx.tmp is not None:
            shutil.rmtree(ctx.tmp, ignore_errors=True)
    check(f"real copy: commands found ({len(cmds)})", len(cmds) > 0)
    bare = [x for x in cmds if x.kind == "bare-python"]
    check("real copy: check 2 FAILs exactly when a bare-python command exists",
          c2.ok == (not bare and all(x.kind == "launcher" and not x.problem for x in cmds)))
    check("real copy: check 4 always-fire list includes zeus-first",
          L.ZEUS_RULE in text_of(c4) or c4.ok)
    check(f"real copy: check 6 passes ({c6.detail})", c6.ok)


def main() -> int:
    for fn in (test_all_good, test_broken_hook_path, test_bare_python, test_mcp_bare_python,
               test_missing_always_rule, test_untagged_always_rule, test_crashing_hook,
               test_missing_contract_pieces, test_fallback_wiring_reads_keys_only, test_not_wired,
               test_bad_agent, test_git_dirty_and_broken, test_rel_rooted_escape,
               test_rel_drive_relative, test_cmd_metachar_args, test_cmd_metachar_script,
               test_env_redirected_to_sandbox, test_secret_env_widened, test_real_repo_copy):
        case(fn)
    failed = [n for n, ok in results if not ok]
    for n, ok in results:
        print(("PASS " if ok else "FAIL ") + n)
    print(f"\n{len(results) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
