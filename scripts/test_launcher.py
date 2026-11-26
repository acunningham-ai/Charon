#!/usr/bin/env python3
"""Tests for the interpreter launcher, scripts/hook (sh) and scripts/hook.cmd (cmd.exe),
and for the release gate's no-bare-interpreter check (install hole rows 2, 5a, 5d, 5g).

What it proves, driving the real launcher files:

  positive
    - a script runs through the launcher; its stdin reaches it and its exit code
      comes back unchanged (0 and non-zero), args included;
    - with ONLY python3 on PATH, ONLY python, or ONLY a `py` launcher, it still runs;
    - a `python3` that is not Python 3 is skipped (the probe), the next one is used;
    - the real PreToolUse gate scripts/hooks/deny-destructive.py runs through the
      launcher with only python3 on PATH: a harmless command passes (0), a write to
      the Agent Org approvals file is blocked (2);
    - the staged settings and .mcp.json pass the gate check (when staged).
  negative
    - no interpreter on PATH: exit 2 and ONE stderr line naming the fix;
    - absolute, `..` and non-.py script paths are refused with exit 2;
    - a settings fixture whose hook starts with bare python FAILS the gate check, as
      do a bare-python MCP server, statusLine and allow rule;
    - mutation: a launcher edited to exit 0 when nothing is found, or to swallow the
      script's exit code, is caught by the same assertions.
  hygiene
    - the launcher writes nothing into the repo it serves; it has no CR bytes.
  Charon's private venv (~/.charon-venv, %USERPROFILE%\\.charon-venv)
    - a real venv (python -m venv --without-pip) in the home folder is used before
      PATH, by sh and by hook.cmd, and still with an empty PATH;
    - venv absent, or a venv folder with no interpreter in it: PATH is searched
      exactly as before (same interpreter, same exit 2 line on an empty PATH);
    - sh layout order: bin/python3, then bin/python, then Scripts/python.exe;
    - links: a venv folder that is a symlink or junction to a real venv is used;
      one to a folder holding a fake interpreter, or a dangling one, is not; a
      venv python that exits 0 for anything (like /bin/true) is NOT taken for
      Python, because the venv probe must print a marker;
    - mutation: a launcher with the venv step removed, or with the venv probe
      reduced to "exit 0 is enough", is caught.

PATH is controlled with a temp folder of tiny sh shims (`python3`, `python`, `py`,
`sh`) that exec this Python or the real sh, so no real interpreter leaks in through
PATH. HOME and USERPROFILE point at temp folders, so a real ~/.charon-venv on the
machine running the tests never leaks in either. Everything is written under a
temp folder, removed at the end. No network (the test venv is made with
--without-pip), no git. It runs `sh` (and `cmd.exe` for hook.cmd on Windows) with
fixed argument lists, never a shell string built from input.

Run from the repo root:  python scripts/test_launcher.py
Exit 0 when every check passes, 1 otherwise.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO = Path(__file__).resolve().parent.parent
LAUNCHER = REPO / "scripts" / "hook"
LAUNCHER_CMD = REPO / "scripts" / "hook.cmd"
GATE = REPO / "test-scenarios" / "run-deterministic-checks.py"
STAGING = REPO / "state" / "daedalus-staging" / "w2-launcher"
NO_PY = "no Python 3 found"

ECHO_SCRIPT = (
    "import sys\n"
    "data = sys.stdin.read()\n"
    "sys.stdout.write('stdin=' + data + '|args=' + ','.join(sys.argv[2:]) + '|major=' + str(sys.version_info[0]))\n"
    "sys.exit(int(sys.argv[1]))\n"
)

# Which interpreter ran: its real sys.prefix (a venv's own folder, for a venv) and
# the CHARON_TEST_VIA a shim exported, if any.
PREFIX_SCRIPT = (
    "import os, sys\n"
    "sys.stdout.write('prefix=' + os.path.normcase(os.path.realpath(sys.prefix)) + '|via='"
    " + os.environ.get('CHARON_TEST_VIA', '') + '|stdin=' + sys.stdin.read() + '|')\n"
    "sys.exit(int(sys.argv[1]))\n"
)

results: list[tuple[str, bool, str]] = []
skipped: list[tuple[str, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, bool(ok), detail))


def skip(name: str, why: str) -> None:
    skipped.append((name, why))


def norm(p) -> str:
    return os.path.normcase(os.path.realpath(str(p)))


def make_venv(dest: Path) -> tuple[bool, str]:
    """A real venv, no pip (so no network)."""
    r = subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(dest)], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=300)
    found = any((dest / rel).is_file() for rel in ("bin/python3", "bin/python", "Scripts/python.exe"))
    return r.returncode == 0 and found, (r.stderr or r.stdout).strip()[:160]


def dir_link(link: Path, target: Path) -> bool:
    """A symlink to a folder, or on Windows without symlink rights a junction."""
    try:
        os.symlink(str(target), str(link), target_is_directory=True)
        return True
    except (OSError, NotImplementedError):
        pass
    if os.name == "nt":
        try:
            import _winapi
            _winapi.CreateJunction(str(target), str(link))
            return True
        except Exception:
            return False
    return False


def shim(path: Path, body: str) -> None:
    path.write_text("#!/bin/sh\n" + body + "\n", encoding="utf-8", newline="\n")
    path.chmod(0o755)


def q(target: str) -> str:
    return "'" + target.replace("'", "'\"'\"'") + "'"


def snapshot(root: Path) -> dict:
    snap = {}
    for p in root.rglob("*"):
        if p.is_file():
            st = p.stat()
            snap[p.relative_to(root).as_posix()] = (st.st_size, st.st_mtime_ns)
    return snap


def run(argv, env, stdin="", cwd=None):
    return subprocess.run(argv, input=stdin, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", env=env, cwd=str(cwd) if cwd else None, timeout=120)


def load_gate():
    spec = importlib.util.spec_from_file_location("charon_release_gate_launcher", GATE)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    sh = shutil.which("sh")
    record("launcher files exist", LAUNCHER.is_file() and LAUNCHER_CMD.is_file())
    record("scripts/hook has no CR bytes (sh would break)", LAUNCHER.is_file() and b"\r" not in LAUNCHER.read_bytes())
    if not sh or not LAUNCHER.is_file():
        record("sh available to run the launcher", False, "no sh on PATH" if not sh else "launcher missing")
        return report()

    py = Path(sys.executable).as_posix()
    tmp = Path(tempfile.mkdtemp(prefix="charon-test-launcher-"))
    try:
        # A throwaway repo: the real launcher bytes plus a probe script.
        fake = tmp / "repo"
        (fake / "scripts").mkdir(parents=True)
        shutil.copy2(LAUNCHER, fake / "scripts" / "hook")
        shutil.copy2(LAUNCHER_CMD, fake / "scripts" / "hook.cmd")
        (fake / "scripts" / "echo_exit.py").write_text(ECHO_SCRIPT, encoding="utf-8", newline="\n")
        (fake / "scripts" / "echo_prefix.py").write_text(PREFIX_SCRIPT, encoding="utf-8", newline="\n")
        empty = tmp / "empty"
        empty.mkdir()
        # A home folder with no .charon-venv: every PATH test below runs with it, so
        # the venv step is a no-op there and the PATH search is tested as before.
        home_none = tmp / "home-none"
        home_none.mkdir()

        def bindir(name: str, **progs: str) -> Path:
            d = tmp / name
            d.mkdir()
            shim(d / "sh", f'exec {q(Path(sh).as_posix())} "$@"')
            for prog, body in progs.items():
                shim(d / prog, body)
            return d

        only_py3 = bindir("py3", python3=f'exec {q(py)} "$@"')
        only_python = bindir("python", python=f'exec {q(py)} "$@"')
        # `py -3 ...`: drop the -3 and run this Python, as the real py launcher would.
        only_pylauncher = bindir("pylauncher",
                                 py=f'[ "$1" = "-3" ] && shift\nexec {q(py)} "$@"')
        # A python3 that is not Python 3 (exits 1 on the probe, 3 on anything else).
        fake_py3 = bindir("fakepy3", python3='case "$*" in *version_info*) exit 1;; esac\necho WRONG; exit 3',
                          python=f'exec {q(py)} "$@"')

        base = dict(os.environ, HOME=str(home_none), USERPROFILE=str(home_none))
        base.pop("HARNESS_UNATTENDED_ALLOWLIST", None)
        before = snapshot(fake)
        launcher = str(fake / "scripts" / "hook")

        # ---- positive: stdin, args and exit code pass through ------------------------
        for label, d in (("only python3", only_py3), ("only python", only_python),
                         ("only py -3", only_pylauncher)):
            r = run([sh, launcher, "scripts/echo_exit.py", "7", "a", "b c"], dict(base, PATH=str(d)), "hello-stdin")
            record(f"{label}: exit code 7 passes through", r.returncode == 7, f"rc={r.returncode} {r.stderr.strip()[:120]}")
            record(f"{label}: stdin and args reach the script",
                   "stdin=hello-stdin|args=a,b c|major=3" in r.stdout, r.stdout[:120])
        # The launcher path as forward slashes too (the settings form passes it so).
        r = run([sh, Path(launcher).as_posix(), "scripts/echo_exit.py", "4"], dict(base, PATH=str(only_py3)), "fw")
        record("launcher path with forward slashes finds the repo root", r.returncode == 4 and "stdin=fw" in r.stdout,
               f"rc={r.returncode} {r.stderr.strip()[:120]}")
        r = run([sh, launcher, "scripts/echo_exit.py", "0"], dict(base, PATH=str(only_py3)), "x")
        record("exit code 0 passes through", r.returncode == 0, f"rc={r.returncode}")
        r = run([sh, launcher, "scripts/echo_exit.py", "5"], dict(base, PATH=str(fake_py3)), "y")
        record("a python3 that is not Python 3 is skipped; python is used",
               r.returncode == 5 and "WRONG" not in r.stdout and "stdin=y" in r.stdout,
               f"rc={r.returncode} out={r.stdout[:80]}")

        # ---- negative: no interpreter -> exit 2, one line, names the fix ------------
        r = run([sh, launcher, "scripts/echo_exit.py", "0"], dict(base, PATH=""), "z", cwd=empty)
        lines = [ln for ln in r.stderr.splitlines() if ln.strip()]
        record("empty PATH: exit 2 (a PreToolUse gate blocks, never 127 or 0)", r.returncode == 2, f"rc={r.returncode}")
        record("empty PATH: exactly one stderr line naming the fix",
               len(lines) == 1 and NO_PY in lines[0] and "Install Python 3" in lines[0], r.stderr.strip()[:200])
        record("empty PATH: the script did not run", "stdin=" not in r.stdout)

        for bad in ("../echo_exit.py", "scripts/../scripts/echo_exit.py", "/tmp/x.py", "scripts/hook"):
            r = run([sh, launcher, bad], dict(base, PATH=str(only_py3)), "")
            record(f"refused script path `{bad}` -> exit 2", r.returncode == 2 and "refused" in r.stderr,
                   f"rc={r.returncode}")
        r = run([sh, launcher], dict(base, PATH=str(only_py3)), "")
        record("no script given -> exit 2 with usage", r.returncode == 2 and "usage" in r.stderr)

        # ---- mutation: break the launcher, the assertions above must catch it -------
        src = LAUNCHER.read_text(encoding="utf-8")
        mutants = {
            "exit 0 when no Python": src.rsplit("exit 2", 1)[0] + "exit 0\n",
            "swallows the exit code": src.replace('exec "$_hook_py" "$_hook_root/$_hook_script" "$@"',
                                                  '"$_hook_py" "$_hook_root/$_hook_script" "$@"; exit 0'),
        }
        for label, text in mutants.items():
            mdir = tmp / ("mut-" + label.split()[0] + label.split()[-1])
            (mdir / "scripts").mkdir(parents=True)
            (mdir / "scripts" / "hook").write_text(text, encoding="utf-8", newline="\n")
            shutil.copy2(fake / "scripts" / "echo_exit.py", mdir / "scripts" / "echo_exit.py")
            m = str(mdir / "scripts" / "hook")
            r_empty = run([sh, m, "scripts/echo_exit.py", "7"], dict(base, PATH=""), "", cwd=empty)
            r_py3 = run([sh, m, "scripts/echo_exit.py", "7"], dict(base, PATH=str(only_py3)), "")
            caught = not (r_empty.returncode == 2 and r_py3.returncode == 7)
            record(f"mutation caught: {label}", text != src and caught,
                   f"empty rc={r_empty.returncode}, py3 rc={r_py3.returncode}")

        # ---- Charon's private venv ------------------------------------------------
        sys_prefix = "prefix=" + norm(sys.prefix) + "|"

        def run_home(launcher_path, home, path_dir, code="7", stdin="v"):
            env = dict(base, HOME=str(home), USERPROFILE=str(home), PATH=str(path_dir) if path_dir else "")
            return run([sh, launcher_path, "scripts/echo_prefix.py", code], env, stdin, cwd=empty)

        # A real venv, as the installers make it.
        home_venv = tmp / "home-venv"
        home_venv.mkdir()
        real_venv = home_venv / ".charon-venv"
        made, why = make_venv(real_venv)
        record("setup: a real venv was made (python -m venv --without-pip)", made, why)
        venv_prefix = "prefix=" + norm(real_venv) + "|"

        r = run_home(launcher, home_venv, only_py3)
        record("venv present: sh runs the script with ~/.charon-venv's python, not PATH's python3",
               r.returncode == 7 and venv_prefix in r.stdout and "stdin=v|" in r.stdout,
               f"rc={r.returncode} out={r.stdout[:160]} err={r.stderr.strip()[:120]}")
        r = run_home(launcher, home_venv, None)
        record("venv present, empty PATH: sh still runs it with the venv's python",
               r.returncode == 7 and venv_prefix in r.stdout, f"rc={r.returncode} out={r.stdout[:160]}")
        r = run_home(launcher, home_venv, only_py3, code="0")
        record("venv present: exit code 0 passes through", r.returncode == 0 and venv_prefix in r.stdout,
               f"rc={r.returncode}")

        # Venv absent: exactly the PATH search of before.
        r = run_home(launcher, home_none, only_py3)
        record("venv absent: PATH python3 is used, as before",
               r.returncode == 7 and sys_prefix in r.stdout, f"rc={r.returncode} out={r.stdout[:160]}")
        home_hollow = tmp / "home-hollow"
        (home_hollow / ".charon-venv" / "bin").mkdir(parents=True)
        (home_hollow / ".charon-venv" / "Scripts").mkdir()
        r = run_home(launcher, home_hollow, only_py3)
        record("venv folder with no interpreter in it: PATH python3 is used",
               r.returncode == 7 and sys_prefix in r.stdout, f"rc={r.returncode} out={r.stdout[:160]}")
        r = run_home(launcher, home_hollow, None)
        lines = [ln for ln in r.stderr.splitlines() if ln.strip()]
        record("venv folder with no interpreter, empty PATH: exit 2, the same one line naming the fix",
               r.returncode == 2 and len(lines) == 1 and NO_PY in lines[0] and "Install Python 3" in lines[0],
               f"rc={r.returncode} {r.stderr.strip()[:200]}")

        # Layout order with shims that say which one ran.
        def venv_home(name: str, **rels: str) -> Path:
            h = tmp / name
            for rel, body in rels.items():
                p = h / ".charon-venv" / rel.replace("__", "/")
                p.parent.mkdir(parents=True, exist_ok=True)
                shim(p, body)
            return h

        def tagged(tag: str) -> str:
            return f"CHARON_TEST_VIA={tag}\nexport CHARON_TEST_VIA\nexec {q(py)} \"$@\""

        layouts = (
            ("bin/python3 wins over bin/python and Scripts/python.exe", "venv-bin-python3",
             {"bin__python3": tagged("venv-bin-python3"), "bin__python": tagged("venv-bin-python"),
              "Scripts__python.exe": tagged("venv-scripts")}),
            ("bin/python is next", "venv-bin-python",
             {"bin__python": tagged("venv-bin-python"), "Scripts__python.exe": tagged("venv-scripts")}),
            ("Scripts/python.exe (Windows layout under Git Bash) is last", "venv-scripts",
             {"Scripts__python.exe": tagged("venv-scripts")}),
        )
        for i, (label, tag, rels) in enumerate(layouts):
            h = venv_home(f"home-layout{i}", **rels)
            r = run_home(launcher, h, only_py3)
            record(f"sh venv order: {label}", r.returncode == 7 and f"|via={tag}|" in r.stdout,
                   f"rc={r.returncode} out={r.stdout[:160]} err={r.stderr.strip()[:120]}")

        # Not a Python 3 interpreter: skipped, PATH used.
        h_notpy = venv_home("home-notpy", bin__python3='case "$*" in *version_info*) exit 1;; esac\necho WRONG; exit 3')
        r = run_home(launcher, h_notpy, only_py3)
        record("venv python that is not Python 3: skipped, PATH python3 used",
               r.returncode == 7 and sys_prefix in r.stdout and "WRONG" not in r.stdout,
               f"rc={r.returncode} out={r.stdout[:160]}")
        # Exits 0 for anything (a link to /bin/true, say). An exit-code-only probe
        # would take it, and a gate run through it would "pass" without checking.
        h_true = venv_home("home-true", bin__python3="exit 0")
        r = run_home(launcher, h_true, only_py3)
        record("venv python that exits 0 for anything (like /bin/true): NOT used, PATH python3 used",
               r.returncode == 7 and sys_prefix in r.stdout, f"rc={r.returncode} out={r.stdout[:160]}")
        # Plain text, not a program.
        h_text = tmp / "home-text"
        (h_text / ".charon-venv" / "bin").mkdir(parents=True)
        (h_text / ".charon-venv" / "bin" / "python3").write_text("not a program\n", encoding="utf-8")
        r = run_home(launcher, h_text, only_py3)
        record("venv python that is a text file: skipped, PATH python3 used",
               r.returncode == 7 and sys_prefix in r.stdout, f"rc={r.returncode} out={r.stdout[:160]}")

        # Links. Decision: a link (symlink or junction) is followed, and what it
        # leads to must pass the marker probe. Links are not refused: a POSIX venv
        # links bin/python3 to the base Python by default, and anyone who can plant
        # a link in your home folder can already edit your shell profile and PATH.
        link_cases = []
        h_link_real = tmp / "home-link-real"
        h_link_real.mkdir()
        if made and dir_link(h_link_real / ".charon-venv", real_venv):
            link_cases.append(("venv folder is a link/junction to a real venv elsewhere: used",
                               h_link_real, venv_prefix))
        else:
            skip("venv folder link to a real venv", "could not make a folder link here" if made else "no venv")
        fake_target = venv_home("fake-venv-target", **{"bin__python3": "exit 0", "Scripts__python.exe": "exit 0"})
        h_link_fake = tmp / "home-link-fake"
        h_link_fake.mkdir()
        if dir_link(h_link_fake / ".charon-venv", fake_target / ".charon-venv"):
            link_cases.append(("venv folder is a link/junction to a folder of fake interpreters: NOT used",
                               h_link_fake, sys_prefix))
        else:
            skip("venv folder link to fakes", "could not make a folder link here")
        h_dangle = tmp / "home-dangle"
        h_dangle.mkdir()
        gone = tmp / "gone-venv"
        (gone / "bin").mkdir(parents=True)
        if dir_link(h_dangle / ".charon-venv", gone):
            shutil.rmtree(gone)
            link_cases.append(("venv folder is a dangling link/junction: NOT used", h_dangle, sys_prefix))
        else:
            skip("dangling venv folder link", "could not make a folder link here")
        if os.name != "nt" and made and (real_venv / "bin" / "python3").is_file():
            h_flink = tmp / "home-filelink"
            (h_flink / ".charon-venv" / "bin").mkdir(parents=True)
            os.symlink("/bin/true" if Path("/bin/true").exists() else "/usr/bin/true",
                       str(h_flink / ".charon-venv" / "bin" / "python3"))
            link_cases.append(("venv bin/python3 is a symlink to `true`: NOT used", h_flink, sys_prefix))
            h_fdang = tmp / "home-filedangle"
            (h_fdang / ".charon-venv" / "bin").mkdir(parents=True)
            os.symlink(str(tmp / "nowhere" / "python3"), str(h_fdang / ".charon-venv" / "bin" / "python3"))
            link_cases.append(("venv bin/python3 is a dangling symlink: NOT used", h_fdang, sys_prefix))
        for label, h, want in link_cases:
            r = run_home(launcher, h, only_py3)
            record(f"sh: {label}", r.returncode == 7 and want in r.stdout,
                   f"rc={r.returncode} out={r.stdout[:160]} err={r.stderr.strip()[:120]}")

        # Mutation: break the venv step; the assertions above must catch it.
        vsrc = LAUNCHER.read_text(encoding="utf-8")
        venv_mutants = {
            "venv step removed": (vsrc.replace('if [ -n "${HOME-}" ]; then', "if false; then"), home_venv,
                                  venv_prefix),
            "venv probe reduced to exit code": (vsrc.replace('if [ "$_hook_out" = "charon-py3" ]; then',
                                                             "if true; then"), h_true, sys_prefix),
        }
        for label, (text, h, want) in venv_mutants.items():
            mdir = tmp / ("vmut-" + label.split()[1])
            (mdir / "scripts").mkdir(parents=True)
            (mdir / "scripts" / "hook").write_text(text, encoding="utf-8", newline="\n")
            shutil.copy2(fake / "scripts" / "echo_prefix.py", mdir / "scripts" / "echo_prefix.py")
            r = run_home(str(mdir / "scripts" / "hook"), h, only_py3)
            caught = not (r.returncode == 7 and want in r.stdout)
            record(f"mutation caught: {label}", text != vsrc and caught, f"rc={r.returncode} out={r.stdout[:120]}")

        # ---- hygiene: nothing written into the served repo -------------------------
        record("launcher wrote nothing into the repo it serves", snapshot(fake) == before)

        # ---- the real gate hook through the real launcher, python3-only PATH --------
        hook_env = dict(base, PATH=str(only_py3), HARNESS_HOOK_TEST="1", CLAUDE_PROJECT_DIR=str(REPO))

        def hook_payload(p):
            return json.dumps(dict(p, hook_event_name="PreToolUse", session_id="test-launcher", cwd=str(REPO)))

        r = run([sh, str(LAUNCHER), "scripts/hooks/deny-destructive.py"], hook_env,
                hook_payload({"tool_name": "Bash", "tool_input": {"command": "ls"}}), cwd=REPO)
        record("real hook deny-destructive.py: harmless command passes (0) with only python3",
               r.returncode == 0, f"rc={r.returncode} {r.stderr.strip()[:160]}")
        r = run([sh, str(LAUNCHER), "scripts/hooks/deny-destructive.py"], hook_env,
                hook_payload({"tool_name": "Write", "tool_input": {
                    "file_path": str(REPO / "state" / "agent-org" / "approvals.json"), "content": "{}"}}), cwd=REPO)
        # Exit 2 alone is not proof: Python's own "can't open file" is also 2. The
        # hook's block message is.
        record("real hook deny-destructive.py: approvals write blocked (2) by the hook itself",
               r.returncode == 2 and "BLOCKED" in r.stderr and NO_PY not in r.stderr,
               f"rc={r.returncode} {r.stderr.strip()[:160]}")

        # ---- hook.cmd, Windows only ------------------------------------------------
        if os.name == "nt":
            cmd = str(fake / "scripts" / "hook.cmd")
            pydir = str(Path(sys.executable).parent)
            env_cmd = dict(base, PATH=pydir)
            r = run([cmd, "scripts/echo_exit.py", "7", "a"], env_cmd, "cmd-stdin")
            record("hook.cmd: exit code 7, stdin and args pass through",
                   r.returncode == 7 and "stdin=cmd-stdin|args=a|major=3" in r.stdout,
                   f"rc={r.returncode} out={r.stdout[:100]} err={r.stderr.strip()[:120]}")
            r = run([cmd, "scripts/echo_exit.py", "0"], env_cmd, "")
            record("hook.cmd: exit code 0 passes through", r.returncode == 0, f"rc={r.returncode}")
            r = run([cmd, "scripts/echo_exit.py", "0"], dict(base, PATH=""), "", cwd=empty)
            lines = [ln for ln in r.stderr.splitlines() if ln.strip()]
            record("hook.cmd: empty PATH -> exit 2, one line naming the fix",
                   r.returncode == 2 and len(lines) == 1 and NO_PY in lines[0],
                   f"rc={r.returncode} {r.stderr.strip()[:160]}")
            for bad in ("..\\echo_exit.py", "C:\\x.py", "scripts\\hook"):
                r = run([cmd, bad], env_cmd, "")
                record(f"hook.cmd: refused `{bad}` -> exit 2", r.returncode == 2, f"rc={r.returncode}")

            # Charon's private venv, %USERPROFILE%\.charon-venv\Scripts\python.exe.
            def run_cmd_home(cmd_path, profile, path_dir, code="7"):
                env = dict(base, HOME=str(profile), USERPROFILE=str(profile),
                           PATH=str(path_dir) if path_dir else "")
                return run([cmd_path, "scripts/echo_prefix.py", code], env, "w", cwd=empty)

            r = run_cmd_home(cmd, home_venv, pydir)
            record("hook.cmd: venv present: the script runs with the venv's python.exe, not PATH's",
                   r.returncode == 7 and venv_prefix in r.stdout and "stdin=w|" in r.stdout,
                   f"rc={r.returncode} out={r.stdout[:160]} err={r.stderr.strip()[:120]}")
            r = run_cmd_home(cmd, home_venv, None)
            record("hook.cmd: venv present, empty PATH: still runs with the venv's python.exe",
                   r.returncode == 7 and venv_prefix in r.stdout, f"rc={r.returncode} out={r.stdout[:160]}")
            r = run_cmd_home(cmd, home_none, pydir)
            record("hook.cmd: venv absent: PATH python is used, as before",
                   r.returncode == 7 and sys_prefix in r.stdout, f"rc={r.returncode} out={r.stdout[:160]}")
            r = run_cmd_home(cmd, home_hollow, None)
            lines = [ln for ln in r.stderr.splitlines() if ln.strip()]
            record("hook.cmd: venv folder with no python.exe, empty PATH: exit 2, one line naming the fix",
                   r.returncode == 2 and len(lines) == 1 and NO_PY in lines[0],
                   f"rc={r.returncode} {r.stderr.strip()[:160]}")
            h_cmdtext = tmp / "home-cmdtext"
            (h_cmdtext / ".charon-venv" / "Scripts").mkdir(parents=True)
            (h_cmdtext / ".charon-venv" / "Scripts" / "python.exe").write_text("not a program\n", encoding="utf-8")
            r = run_cmd_home(cmd, h_cmdtext, pydir)
            record("hook.cmd: venv python.exe that is a text file: skipped, PATH python used",
                   r.returncode == 7 and sys_prefix in r.stdout, f"rc={r.returncode} out={r.stdout[:160]}")
            h_cmddir = tmp / "home-cmddir"
            (h_cmddir / ".charon-venv" / "Scripts" / "python.exe").mkdir(parents=True)
            r = run_cmd_home(cmd, h_cmddir, pydir)
            record("hook.cmd: venv python.exe that is a folder: skipped, PATH python used",
                   r.returncode == 7 and sys_prefix in r.stdout, f"rc={r.returncode} out={r.stdout[:160]}")
            for label, h, want in link_cases:
                r = run_cmd_home(cmd, h, pydir)
                record(f"hook.cmd: {label}", r.returncode == 7 and want in r.stdout,
                       f"rc={r.returncode} out={r.stdout[:160]} err={r.stderr.strip()[:120]}")
            csrc = LAUNCHER_CMD.read_text(encoding="utf-8")
            cmut = csrc.replace("if defined HOOK_VENV_PY if exist", "if defined HOOK_NOPE if exist")
            cdir = tmp / "vmut-cmd"
            (cdir / "scripts").mkdir(parents=True)
            (cdir / "scripts" / "hook.cmd").write_text(cmut, encoding="utf-8", newline="\r\n")
            shutil.copy2(fake / "scripts" / "echo_prefix.py", cdir / "scripts" / "echo_prefix.py")
            r = run_cmd_home(str(cdir / "scripts" / "hook.cmd"), home_venv, pydir)
            record("mutation caught: hook.cmd venv step removed",
                   cmut != csrc and not (r.returncode == 7 and venv_prefix in r.stdout),
                   f"rc={r.returncode} out={r.stdout[:120]}")

        # ---- gate check (a): bare interpreter fixtures fail, staged copies pass -----
        gate = load_gate()
        bare_hook = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
            {"type": "command", "command": 'python "${CLAUDE_PROJECT_DIR}/scripts/hooks/deny-destructive.py"'}]}]}}
        good_hook = {"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
            {"type": "command", "command": 'sh "${CLAUDE_PROJECT_DIR}/scripts/hook" scripts/hooks/deny-destructive.py'}]}]}}
        fixtures = {
            "bare python hook": (bare_hook, None, True),
            "bare python3.exe MCP server": (good_hook, {"mcpServers": {"s": {
                "command": "C:/Python312/python3.exe", "args": ["x.py"]}}}, True),
            "bare python statusLine": (dict(good_hook, statusLine={"type": "command", "command": "python3 s.py"}),
                                       None, True),
            "py file run by node, no launcher": ({"hooks": {"Stop": [{"hooks": [
                {"type": "command", "command": "node x.js scripts/x.py"}]}]}}, None, True),
            "allow rule Bash(python scripts/*)": (dict(good_hook, permissions={"allow": ["Bash(python scripts/*)"]}),
                                                  None, True),
            "launcher hook + launcher MCP": (good_hook, {"mcpServers": {"s": {
                "command": "sh", "args": ["${CLAUDE_PROJECT_DIR}/scripts/hook", "scripts/mcp/x.py"]}}}, False),
        }
        fx = tmp / "fixtures"
        fx.mkdir()
        for label, (settings, mcp, should_fail) in fixtures.items():
            s_path, m_path = fx / "settings.json", fx / "mcp.json"
            s_path.write_text(json.dumps(settings), encoding="utf-8")
            m_path.write_text(json.dumps(mcp or {}), encoding="utf-8")
            gate.SETTINGS_FILE, gate.MCP_FILE = s_path, m_path
            res = gate.check_no_bare_interpreter()
            want = "FAIL" if should_fail else "PASS"
            record(f"gate check (a) on fixture '{label}' -> {want}", res.status == want,
                   f"{res.status}: {res.detail}")
        gate.SETTINGS_FILE, gate.MCP_FILE = fx / "settings.json", fx / "none.json"
        (fx / "settings.json").write_text(json.dumps({"mcpServers": {"v": {
            "command": "sh", "args": ["${CLAUDE_PROJECT_DIR}/scripts/hook", "scripts/mcp/v.py"]}}}), encoding="utf-8")
        res = gate.check_no_bare_interpreter()
        record("gate check (a): mcpServers in settings.json is flagged (WARN)", res.status == "WARN",
               f"{res.status}: {res.detail}")

        staged_s, staged_m = STAGING / "settings.json.staged", STAGING / "mcp.json.staged"
        if staged_s.is_file() and staged_m.is_file():
            gate.SETTINGS_FILE, gate.MCP_FILE = staged_s, staged_m
            res = gate.check_no_bare_interpreter()
            record("gate check (a) on the staged settings + .mcp.json -> PASS", res.status == "PASS",
                   f"{res.status}: {res.detail} {res.findings[:3]}")
            staged_mcp = json.loads(staged_m.read_text(encoding="utf-8")).get("mcpServers", {})
            staged_set = json.loads(staged_s.read_text(encoding="utf-8"))
            record("staged: vault-ops moved to .mcp.json, none left in settings.json",
                   "vault-ops" in staged_mcp and "mcpServers" not in staged_set, ", ".join(sorted(staged_mcp)))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    record("temp folder removed", not tmp.exists())
    return report()


def report() -> int:
    passed = sum(1 for _, ok, _ in results if ok)
    failed = len(results) - passed
    for name, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  ({detail})" if detail and not ok else ""))
    for name, why in skipped:
        print(f"  SKIP  {name}  ({why})")
    print(f"\n{passed} passed, {failed} failed, {len(skipped)} skipped ({len(results)} checks)")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
