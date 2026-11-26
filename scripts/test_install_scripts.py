#!/usr/bin/env python3
"""End-to-end checks for install.sh and install.ps1.

Drives the real installer scripts through their real entry points (bash and
PowerShell), with fake interpreters ("shims") first on PATH, inside throwaway
temp folders. Nothing here installs a package, touches the real home folder,
reaches the network or starts the real first-run wizard:

- every shim answers `-m pip ...` and `-m venv ...` itself (pip install never
  really runs; a shim "venv" is a folder holding another shim) and answers a
  call to first-run.py / backup-brain.py by logging it and exiting;
- the only calls a shim passes to the real interpreter are `-c` import probes,
  run against stub modules on PYTHONPATH;
- HOME / USERPROFILE / TMPDIR point into the temp folder, and Obsidian, Node
  and (for bash) the Python install step are skipped unless a check needs
  them, in which case `winget` is a shim too, so no package manager is ever
  reached;
- the Windows shims are .exe files (install.ps1 accepts .exe only, as
  scripts/hook.cmd does). Each is pip's own console-script launcher stub with
  a small Python program appended, built in the temp folder; nothing is
  downloaded or compiled.

What it proves (see each check's name for the detail):
  - PEP 668 and pip failures are reported, never swallowed, and a protected
    Python gets a private venv at ~/.charon-venv instead;
  - a required package still missing makes the exit status 3;
  - --dry-run never runs pip, creates nothing and starts no wizard;
  - interpreter choice follows the hook launcher (python3, python, py -3),
    Python 3 only, and install.ps1 takes .exe files only;
  - import probes never load a module planted in the current folder;
  - winget failures are failures, and a fresh Python install exits 3;
  - the secrets folder ACL: icacls exit code checked, SID grant, no /T;
  - root / elevated and piped runs are refused;
  - restore passes --from with the backup it found;
  - remedies quote paths and make no user-site claim;
  - a leading ~ in the secrets answer is expanded;
  - --answers FILE / -AnswersFile reaches first-run, and is validated.

Usage:  python scripts/test_install_scripts.py
Exit:   0 all ran checks passed (skips allowed, each with a reason), 1 otherwise.
"""
from __future__ import annotations

import base64
import importlib.util
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
INSTALL_SH = REPO / "install.sh"
INSTALL_PS1 = REPO / "install.ps1"
REAL_PY = Path(sys.executable).resolve()
TIMEOUT = 180

RESULTS: list[tuple[str, str, str]] = []  # (status, name, detail)


def record(status: str, name: str, detail: str = "") -> None:
    RESULTS.append((status, name, detail))
    line = f"  [{status}] {name}"
    if detail:
        line += f"  ({detail})"
    print(line, flush=True)


def tempdir():
    # Some checks leave a folder the current user may not change (that is the
    # point of the check), so cleanup errors are not test failures.
    return tempfile.TemporaryDirectory(ignore_cleanup_errors=True)


# --------------------------------------------------------------------------
# Locating the shells
# --------------------------------------------------------------------------

def find_bash() -> tuple[str | None, str]:
    """A POSIX bash that understands this machine's paths, or (None, reason)."""
    if os.name != "nt":
        b = shutil.which("bash")
        return (b, "") if b else (None, "bash not found on PATH")
    # On Windows, System32\bash.exe is WSL: it cannot run Windows interpreters
    # by their Windows paths, so prefer Git for Windows' bash.
    candidates = []
    git = shutil.which("git")
    if git:
        git_root = Path(git).resolve().parent.parent
        candidates += [git_root / "bin" / "bash.exe", git_root / "usr" / "bin" / "bash.exe"]
    b = shutil.which("bash")
    if b and "system32" not in b.lower():
        candidates.insert(0, Path(b))
    for c in candidates:
        if Path(c).is_file():
            return str(c), ""
    return None, "no Git-for-Windows bash found (System32 bash is WSL and is not used)"


def find_powershell() -> tuple[str | None, str]:
    for name in ("powershell", "pwsh"):
        p = shutil.which(name)
        if p:
            return p, ""
    return None, "PowerShell (powershell or pwsh) not found on PATH"


# --------------------------------------------------------------------------
# Stub modules for the import probe
# --------------------------------------------------------------------------

def make_stubs(root: Path, missing: tuple[str, ...] = ()) -> Path:
    """A folder of stand-in modules: importable, or raising ImportError."""
    d = root / "stubs"
    d.mkdir(parents=True, exist_ok=True)
    for name in ("yaml", "mcp", "anthropic"):
        body = (f'raise ImportError("test stub: {name} deliberately missing")\n'
                if name in missing else "# test stub\n")
        (d / f"{name}.py").write_text(body, encoding="utf-8")
    return d


def plant_module(folder: Path, name: str) -> Path:
    """A module in the working folder that leaves a marker file if imported."""
    marker = folder / f"PLANTED-{name}-WAS-IMPORTED"
    (folder / f"{name}.py").write_text(
        f"open({str(marker)!r}, 'w').close()\n", encoding="utf-8")
    return marker


def check(name: str, conds: list[tuple[bool, str]], out: str) -> None:
    failed = [why for ok, why in conds if not ok]
    if failed:
        record("FAIL", name, "; ".join(failed))
        tail = "\n".join(out.splitlines()[-25:])
        print("      --- installer output (last 25 lines) ---")
        for ln in tail.splitlines():
            print("      " + ln)
    else:
        record("PASS", name)


# --------------------------------------------------------------------------
# bash shims
# --------------------------------------------------------------------------

def bash_shim(name: str, version: str, pip_mode: str, managed_marker: str, log: Path,
              venv_template: str = "", wizard_rc: int = 0) -> str:
    """A fake interpreter for install.sh.

    version        what the version probe prints ("3.12", "2.7", ...)
    pip_mode       ok | managed | missing | fake-ok   (pip install never really
                   runs; fake-ok pretends it worked, every other mode fails)
    managed_marker 1 | 0   what the PEP 668 marker probe prints
    venv_template  a shim file copied in as <venv>/bin/python by `-m venv`;
                   empty means `-m venv` fails
    """
    real = REAL_PY.as_posix()
    logp = log.as_posix()
    return f"""#!/usr/bin/env bash
# Test shim standing in for '{name}'. Never installs anything.
printf '%s\\n' "{name} $*" >> "{logp}"
case "$*" in
    *version_info*)       echo "{version}"; exit 0 ;;
    *EXTERNALLY-MANAGED*) echo "{managed_marker}"; exit 0 ;;
    *first-run.py*)       exit {wizard_rc} ;;
    *backup-brain.py*)    exit 0 ;;
esac
if [ "${{1:-}}" = "-m" ] && [ "${{2:-}}" = "venv" ]; then
    for last in "$@"; do :; done
    if [ -z "{venv_template}" ]; then echo "Error: test shim cannot make a venv" >&2; exit 1; fi
    mkdir -p "$last/bin" && cp "{venv_template}" "$last/bin/python" \\
        && chmod 755 "$last/bin/python" && printf 'home = test-shim\\n' > "$last/pyvenv.cfg"
    exit $?
fi
if [ "${{1:-}}" = "-m" ] && [ "${{2:-}}" = "pip" ]; then
    if [ "{pip_mode}" = "missing" ]; then echo "No module named pip" >&2; exit 1; fi
    if [ "${{3:-}}" = "--version" ]; then echo "pip 24.0 (test shim)"; exit 0; fi
    if [ "{pip_mode}" = "fake-ok" ]; then echo "test shim: pretending pip install worked"; exit 0; fi
    if [ "{pip_mode}" = "managed" ]; then
        echo "error: externally-managed-environment" >&2
        echo "This environment is externally managed" >&2
        exit 1
    fi
    echo "test shim: pip install is never run for real" >&2
    exit 1
fi
if [ "${{1:-}}" = "-c" ]; then
    exec "{real}" "$@"
fi
echo "test shim: unexpected call: $*" >&2
exit 97
"""


ID_SHIM_ROOT = """#!/usr/bin/env bash
# Test shim for `id`: reports uid 0 (root). Never changes anything.
if [ "${1:-}" = "-u" ]; then echo 0; exit 0; fi
exit 0
"""


def write_bash_shims(shim_dir: Path, specs: dict[str, dict], log: Path, tmp: Path) -> None:
    shim_dir.mkdir(parents=True, exist_ok=True)
    for name, spec in specs.items():
        tmpl = ""
        if spec.get("venv"):
            tdir = tmp / "venv-template"
            tdir.mkdir(exist_ok=True)
            t = tdir / "python"
            t.write_text(bash_shim("venv-python", spec["version"], "fake-ok", "0", log),
                         encoding="utf-8", newline="\n")
            t.chmod(0o755)
            tmpl = t.as_posix()
        p = shim_dir / name
        p.write_text(bash_shim(name, spec["version"], spec.get("pip", "ok"),
                               spec.get("marker", "0"), log, tmpl,
                               spec.get("wizard_rc", 0)),
                     encoding="utf-8", newline="\n")
        p.chmod(0o755)


def run_bash(bash: str, tmp: Path, shims: dict[str, dict], args: list[str],
             missing: tuple[str, ...] = (), extra_env: dict | None = None,
             stdin_text: str | None = None, extra_shims: dict | None = None,
             piped: bool = False) -> tuple[int, str, str, Path]:
    shim_dir = tmp / "shims"
    log = tmp / "shim.log"
    log.write_text("", encoding="utf-8")
    write_bash_shims(shim_dir, shims, log, tmp)
    for name, text in (extra_shims or {}).items():
        p = shim_dir / name
        p.write_text(text, encoding="utf-8", newline="\n")
        p.chmod(0o755)
    stubs = make_stubs(tmp, missing)
    home = tmp / "home"
    home.mkdir(exist_ok=True)
    env = dict(os.environ)
    for k in ("ACCEPT_DEFAULTS", "SKIP_FIRST_RUN", "PYTHONHOME", "VIRTUAL_ENV",
              "BACKUP_SEARCH_DIR"):
        env.pop(k, None)
    env.update({
        "PATH": str(shim_dir) + os.pathsep + env.get("PATH", ""),
        "PYTHONPATH": str(stubs),
        "HOME": str(home),
        "TMPDIR": str(tmp),
        "SKIP_PYTHON": "1",
        "SKIP_OBSIDIAN": "1",
        "SKIP_NODE": "1",
    })
    env.update(extra_env or {})
    if piped:
        # `curl ... | bash`: the script text arrives on stdin.
        cmd = [bash, "-s", "--", *args]
        kw = {"input": INSTALL_SH.read_text(encoding="utf-8")}
    else:
        cmd = [bash, str(INSTALL_SH), *args]
        kw = {"input": stdin_text} if stdin_text is not None else {"stdin": subprocess.DEVNULL}
    p = subprocess.run(cmd, cwd=str(tmp), env=env, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=TIMEOUT, **kw)
    out = p.stdout + p.stderr
    return p.returncode, out, log.read_text(encoding="utf-8"), home


WIZ_NI = 'first-run.py" --non-interactive'   # how a dry run prints the wizard command


def bash_tests(bash: str) -> None:
    ok3 = {"version": "3.12", "pip": "managed", "marker": "0"}

    # 1. pip refuses (PEP 668) and no venv can be made: warns, carries on to
    #    first-run, prints remedies with quoted paths.
    with tempdir() as t:
        tmp = Path(t)
        rc, out, log, home = run_bash(bash, tmp, {"python3": ok3}, ["--non-interactive"])
        check("bash: PEP 668 pip refusal, venv unavailable -> warns, continues, quoted remedy, exit 0", [
            (rc == 0, f"exit {rc}, expected 0"),
            ("externally managed" in out.lower(), "no externally-managed warning"),
            ("python3 -m venv \"" in out, "venv remedy missing or its path is not quoted"),
            ("~/.venvs" not in out, "remedy still names an unquoted ~ path"),
            ("python3-yaml" in out or "PyYAML" in out, "distro-package remedy not printed"),
            ("first-run.py --non-interactive" in log, "first-run not started with --non-interactive"),
            ("-m pip install --user" in log, "pip install was not attempted"),
            ("-m venv" in log, "no venv was attempted after the PEP 668 refusal"),
            ("--break-system-packages" not in log, "--break-system-packages was passed to pip"),
            ((home / ".secrets").is_dir(), "real run did not create HOME/.secrets in the temp home"),
        ], out)

    # 2. A required package is still missing -> exit 3, wizard still reached.
    with tempdir() as t:
        tmp = Path(t)
        rc, out, log, _ = run_bash(bash, tmp, {"python3": ok3}, ["--non-interactive"],
                                   missing=("mcp",))
        check("bash: required package missing -> exit 3, wizard still reached", [
            (rc == 3, f"exit {rc}, expected 3"),
            ("mcp" in out and "still missing" in out, "missing-package summary not printed"),
            ("first-run.py --non-interactive" in log, "first-run not reached"),
        ], out)

    # 3. No pip at all.
    with tempdir() as t:
        tmp = Path(t)
        rc, out, log, _ = run_bash(bash, tmp,
                                   {"python3": {"version": "3.12", "pip": "missing"}},
                                   ["--non-interactive"])
        check("bash: no pip -> warns, continues, exit 0 when packages import", [
            (rc == 0, f"exit {rc}, expected 0"),
            ("pip is not available" in out, "no-pip warning not printed"),
            ("-m pip install" not in log, "pip install attempted without pip"),
            ("first-run.py --non-interactive" in log, "first-run not reached"),
        ], out)

    # 4. Dry run, marker says externally managed: nothing installed, created
    #    or started; the venv it would make is named.
    with tempdir() as t:
        tmp = Path(t)
        managed = {"version": "3.12", "pip": "managed", "marker": "1", "venv": True}
        rc, out, log, home = run_bash(bash, tmp, {"python3": managed},
                                      ["--dry-run", "--non-interactive"], missing=("mcp",))
        check("bash: --dry-run is side-effect free and reports exit 3 for a missing package", [
            (rc == 3, f"exit {rc}, expected 3"),
            ("pip install was NOT run" in out, "PEP 668 marker not detected"),
            (".charon-venv" in out, "dry run did not name the venv it would create"),
            ("-m pip install" not in log, "dry run invoked pip install"),
            ("-m venv" not in log, "dry run created a venv"),
            ("first-run.py" not in log, "dry run started the wizard"),
            ("would run: python3 " in out and WIZ_NI in out,
             "dry run did not print the wizard command with --non-interactive"),
            (not (home / ".secrets").exists(), "dry run created HOME/.secrets"),
            (not (home / ".charon-venv").exists(), "dry run created the venv folder"),
        ], out)

    # 5. Interpreter order: launcher order, Python 3 only.
    with tempdir() as t:
        tmp = Path(t)
        rc, out, log, _ = run_bash(bash, tmp, {
            "python3": {"version": "2.7"},
            "python": {"version": "3.11"},
        }, ["--dry-run", "--non-interactive"])
        check("bash: python3 reporting Python 2 is skipped -> 'python' chosen", [
            ("Interpreter: python (Python 3.11)" in out, "did not choose 'python'"),
            ("would run: python " in out, "wizard not run with 'python'"),
        ], out)
    with tempdir() as t:
        tmp = Path(t)
        rc, out, log, _ = run_bash(bash, tmp, {
            "python3": {"version": "3.9"},
            "python": {"version": "3.12"},
        }, ["--dry-run", "--non-interactive"])
        check("bash: python3 3.9 is the launcher's pick -> reported too old, never skipped", [
            ("Python 3.9 via 'python3' is older than 3.10" in out, "did not report python3 as too old"),
            ("Interpreter: python " not in out, "silently switched to 'python'"),
            (rc != 0, "exit 0 although the launcher's Python is too old"),
        ], out)
    with tempdir() as t:
        tmp = Path(t)
        rc, out, log, _ = run_bash(bash, tmp, {
            "python3": {"version": "3.12"},
            "python": {"version": "3.11"},
        }, ["--dry-run", "--non-interactive"])
        check("bash: python3 and python both Python 3 -> python3 chosen", [
            ("Interpreter: python3 (Python 3.12)" in out, "did not choose python3"),
            (rc == 0, f"exit {rc}, expected 0"),
        ], out)

    # 6. Bad option is refused, not ignored.
    with tempdir() as t:
        tmp = Path(t)
        rc, out, log, _ = run_bash(bash, tmp, {"python3": ok3}, ["--no-such-flag"])
        check("bash: unknown option -> exit 64, nothing run", [
            (rc == 64, f"exit {rc}, expected 64"),
            (log.strip() == "", "an interpreter was called"),
        ], out)

    # 7. (row 50 item 1) A yaml.py / mcp.py in the current folder is never
    #    imported by a probe: mcp is missing, a planted mcp.py must not hide it.
    with tempdir() as t:
        tmp = Path(t)
        marker = plant_module(tmp, "mcp")
        plant_module(tmp, "yaml")
        rc, out, log, _ = run_bash(bash, tmp, {"python3": ok3}, ["--non-interactive"],
                                   missing=("mcp",))
        check("bash: import probes ignore a planted mcp.py / yaml.py in the current folder", [
            (not marker.exists(), "a probe imported mcp.py from the current folder"),
            (not (tmp / "PLANTED-yaml-WAS-IMPORTED").exists(), "a probe imported yaml.py from the current folder"),
            (rc == 3, f"exit {rc}, expected 3 (mcp is really missing)"),
        ], out)

    # 8. (item 5) root is refused before anything runs.
    with tempdir() as t:
        tmp = Path(t)
        rc, out, log, home = run_bash(bash, tmp, {"python3": ok3}, ["--non-interactive"],
                                      extra_shims={"id": ID_SHIM_ROOT})
        check("bash: running as root is refused (exit 77), nothing run", [
            (rc == 77, f"exit {rc}, expected 77"),
            ("root" in out.lower(), "no refusal message naming root"),
            (log.strip() == "", "an interpreter was called"),
            (not (home / ".secrets").exists(), "the secrets folder was created"),
        ], out)

    # 9. (item 5) a piped run (`curl ... | bash`) is refused.
    with tempdir() as t:
        tmp = Path(t)
        rc, out, log, home = run_bash(bash, tmp, {"python3": ok3},
                                      ["--dry-run", "--non-interactive"], piped=True)
        check("bash: piped run (script on stdin) is refused (exit 66), nothing run", [
            (rc == 66, f"exit {rc}, expected 66"),
            ("pipe" in out.lower(), "no refusal message naming the pipe"),
            (log.strip() == "", "an interpreter was called"),
        ], out)

    # 10. (item 6) restore passes --from with the backup it found.
    def make_backup_volume(tmp: Path) -> Path:
        vol = tmp / "mnt" / "usbdrive"
        (vol / "Charon-Backup").mkdir(parents=True)
        (vol / ".charon-backup-target").write_text("", encoding="utf-8")
        return vol
    with tempdir() as t:
        tmp = Path(t)
        make_backup_volume(tmp)
        rc, out, log, _ = run_bash(bash, tmp, {"python3": ok3}, [],
                                   extra_env={"ACCEPT_DEFAULTS": "1",
                                              "BACKUP_SEARCH_DIR": (tmp / "mnt").as_posix()})
        restore = [ln for ln in log.splitlines() if "backup-brain.py" in ln]
        check("bash: restore runs with --from <the found backup folder>", [
            (len(restore) == 1, f"backup-brain.py called {len(restore)} time(s), expected 1"),
            (bool(restore) and "--restore --from" in restore[0]
             and restore[0].rstrip().endswith("usbdrive/Charon-Backup"),
             f"restore call was {restore[:1]!r}"),
        ], out)
    with tempdir() as t:
        tmp = Path(t)
        make_backup_volume(tmp)
        rc, out, log, _ = run_bash(bash, tmp, {"python3": ok3}, ["--non-interactive"],
                                   extra_env={"BACKUP_SEARCH_DIR": (tmp / "mnt").as_posix()})
        check("bash: non-interactive restore hint names --from, restore not run", [
            ("--restore --from \"" in out and "usbdrive/Charon-Backup\"" in out,
             "restore hint lacks a quoted --from path"),
            ("backup-brain.py" not in log, "restored without a person to confirm"),
        ], out)

    # 11. (item 8) a leading ~ in the secrets answer means the home folder.
    with tempdir() as t:
        tmp = Path(t)
        rc, out, log, home = run_bash(bash, tmp, {"python3": ok3}, [],
                                      stdin_text="~/charon-test-secrets\n")
        check("bash: '~/x' typed at the secrets prompt -> HOME/x, no literal ~ folder", [
            ((home / "charon-test-secrets").is_dir(), "HOME/charon-test-secrets not created"),
            (not (tmp / "~").exists(), "a literal '~' folder was created in the current folder"),
        ], out)

    # 12. (venv decision) a protected Python gets ~/.charon-venv, the
    #     requirements go into it, and the wizard runs with it.
    with tempdir() as t:
        tmp = Path(t)
        managed = {"version": "3.12", "pip": "managed", "marker": "1", "venv": True}
        rc, out, log, home = run_bash(bash, tmp, {"python3": managed}, ["--non-interactive"])
        venv = home / ".charon-venv"
        check("bash: PEP 668 -> creates ~/.charon-venv, installs into it, wizard runs with it", [
            ((venv / "pyvenv.cfg").is_file(), "~/.charon-venv was not created"),
            ("python3 -m venv" in log and ".charon-venv" in log, "venv not created with the found Python"),
            ("venv-python -m pip install -r" in log, "requirements not installed into the venv"),
            ("venv-python " in log and "first-run.py --non-interactive" in log,
             "wizard not run with the venv's python"),
            ("python3 -m pip install" not in log, "pip install was run against the protected Python"),
            ("--break-system-packages" not in log, "--break-system-packages was passed to pip"),
            (rc == 0, f"exit {rc}, expected 0"),
        ], out)

    # 13. (row 47) --answers FILE reaches first-run; a bad one is refused.
    with tempdir() as t:
        tmp = Path(t)
        answers = tmp / "answers.yaml"
        answers.write_text("identity_name: Test User\n", encoding="utf-8")
        rc, out, log, _ = run_bash(bash, tmp, {"python3": ok3},
                                   ["--non-interactive", "--answers", answers.as_posix()])
        wiz = [ln for ln in log.splitlines() if "first-run.py" in ln]
        check("bash: --answers FILE is passed to first-run", [
            (len(wiz) == 1 and "--non-interactive" in wiz[0] and "--answers" in wiz[0]
             and "answers.yaml" in wiz[0], f"wizard call was {wiz[:1]!r}"),
            (rc == 0, f"exit {rc}, expected 0"),
        ], out)
    for label, target in (("missing file", "nope.yaml"), ("a folder", ".")):
        with tempdir() as t:
            tmp = Path(t)
            rc, out, log, home = run_bash(bash, tmp, {"python3": ok3},
                                          ["--non-interactive", "--answers", (tmp / target).as_posix()])
            check(f"bash: --answers naming {label} -> exit 64, nothing run", [
                (rc == 64, f"exit {rc}, expected 64"),
                (log.strip() == "", "an interpreter was called"),
                (not (home / ".secrets").exists(), "the secrets folder was created"),
            ], out)

    # 14. (row 47) a non-interactive wizard that stops leaves a loud message.
    with tempdir() as t:
        tmp = Path(t)
        rc, out, log, _ = run_bash(bash, tmp, {"python3": dict(ok3, wizard_rc=2)},
                                   ["--non-interactive"])
        check("bash: non-interactive wizard stop -> loud 'profile not set', its exit status", [
            (rc == 2, f"exit {rc}, expected 2"),
            ("profile is not set" in out, "no 'profile is not set' message"),
            ("--answers" in out, "the message does not name --answers"),
        ], out)


# --------------------------------------------------------------------------
# PowerShell: .exe shims built from pip's launcher stub
# --------------------------------------------------------------------------

EXE_SHIM_MAIN = r'''
import json, os, shutil, subprocess, sys
CFG = json.loads(@@CFG@@)
args = sys.argv[1:]
with open(CFG["log"], "a", encoding="utf-8") as f:
    f.write(CFG["name"] + " " + " ".join(args) + "\n")
if CFG["kind"] == "winget":
    sys.exit(CFG["rc"])
if CFG["kind"] == "py":
    if args[:1] != ["-3"]:
        sys.stderr.write("test shim: py needs -3\n")
        sys.exit(98)
    args = args[1:]
if args[:1] == ["--version"]:
    (sys.stderr if CFG["version_to_stderr"] else sys.stdout).write(CFG["version"] + "\n")
    sys.exit(0)
if args[:1] == ["-c"]:
    if len(args) > 1 and "EXTERNALLY-MANAGED" in args[1] and CFG["marker"] is not None:
        print(CFG["marker"])
        sys.exit(0)
    sys.exit(subprocess.run([CFG["real"]] + args).returncode)
if args[:2] == ["-m", "pip"]:
    if args[2:3] == ["--version"]:
        print("pip 24.0 test shim")
        sys.exit(0)
    if CFG["pip"] == "fake-ok":
        print("test shim: pretending pip install worked")
        sys.exit(0)
    if CFG["pip"] == "managed":
        sys.stderr.write("error: externally-managed-environment\n")
        sys.exit(1)
    sys.stderr.write("ERROR: test shim pip install failed\n")
    sys.exit(1)
if args[:2] == ["-m", "venv"] and len(args) >= 3:
    if not CFG["venv_template"]:
        sys.stderr.write("Error: test shim cannot make a venv\n")
        sys.exit(1)
    d = args[-1]
    os.makedirs(os.path.join(d, "Scripts"), exist_ok=True)
    shutil.copyfile(CFG["venv_template"], os.path.join(d, "Scripts", "python.exe"))
    with open(os.path.join(d, "pyvenv.cfg"), "w", encoding="utf-8") as f:
        f.write("home = test-shim\n")
    sys.exit(0)
if args and os.path.basename(args[0]) == "first-run.py":
    sys.exit(CFG["wizard_rc"])
if args and os.path.basename(args[0]) == "backup-brain.py":
    sys.exit(0)
sys.stderr.write("test shim: unexpected call\n")
sys.exit(97)
'''


def launcher_stub() -> tuple[bytes | None, str]:
    """pip's console-script launcher (distlib), read from the installed pip.

    find_spec on the top-level package locates it without importing pip."""
    spec = importlib.util.find_spec("pip")
    if spec is None or not spec.submodule_search_locations:
        return None, "pip is not installed for this Python, so no .exe launcher stub is available"
    base = Path(list(spec.submodule_search_locations)[0]) / "_vendor" / "distlib"
    arm = platform.machine().lower() in ("arm64", "aarch64")
    for name in (["t64-arm.exe"] if arm else ["t64.exe"]):
        p = base / name
        if p.is_file():
            return p.read_bytes(), ""
    return None, f"no launcher stub found in {base}"


def build_exe_shim(path: Path, stub: bytes, cfg: dict) -> None:
    """launcher stub + shebang + zip(__main__.py): pip's own console-script layout."""
    full = {"real": str(REAL_PY), "kind": "python", "version": "Python 3.12.0",
            "version_to_stderr": False, "marker": None, "pip": "fail",
            "venv_template": "", "wizard_rc": 0, "rc": 0}
    full.update(cfg)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("__main__.py", EXE_SHIM_MAIN.replace("@@CFG@@", repr(json.dumps(full))))
    shebang = b'#!"' + str(REAL_PY).encode("utf-8") + b'"\n'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(stub + shebang + buf.getvalue())


def cmd_shim(name: str, version_line: str, log: Path) -> str:
    """An old-style .cmd interpreter shim: install.ps1 must ignore it."""
    return "\r\n".join([
        "@echo off",
        f'>>"{log}" echo {name}.cmd %*',
        f'if "%~1"=="--version" (echo {version_line}& exit /b 0)',
        "exit /b 0",
    ]) + "\r\n"


def run_ps(ps: str, stub: bytes, tmp: Path, shims: dict[str, dict], args: list[str],
           missing: tuple[str, ...] = (), skip_node: bool = True,
           command: str | None = None, cmd_shims: dict[str, str] | None = None
           ) -> tuple[int, str, str, Path]:
    shim_dir = tmp / "shims"
    shim_dir.mkdir(parents=True, exist_ok=True)
    log = tmp / "shim.log"
    log.write_text("", encoding="utf-8")
    for name, spec in shims.items():
        cfg = {"name": name, "log": str(log)}
        if name == "winget":
            cfg.update({"kind": "winget", "rc": spec.get("rc", 0)})
        else:
            cfg.update({
                "kind": "py" if name == "py" else "python",
                "version": spec["version"],
                "version_to_stderr": spec.get("stderr", False),
                "marker": spec.get("marker"),
                "pip": spec.get("pip", "fail"),
                "wizard_rc": spec.get("wizard_rc", 0),
            })
            if spec.get("venv"):
                tmpl = tmp / "venv-template" / "python.exe"
                build_exe_shim(tmpl, stub, {"name": "venv-python", "log": str(log),
                                            "version": spec["version"], "marker": "0",
                                            "pip": "fake-ok"})
                cfg["venv_template"] = str(tmpl)
        build_exe_shim(shim_dir / f"{name}.exe", stub, cfg)
    for name, version in (cmd_shims or {}).items():
        (shim_dir / f"{name}.cmd").write_text(cmd_shim(name, version, log),
                                              encoding="ascii", newline="")
    stubs = make_stubs(tmp, missing)
    profile = tmp / "profile"
    profile.mkdir(exist_ok=True)
    sysroot = os.environ.get("SystemRoot", r"C:\Windows")
    env = dict(os.environ)
    for k in ("PYTHONHOME", "VIRTUAL_ENV"):
        env.pop(k, None)
    # Only the shims and the OS folders: no real python3/python/py/winget is visible.
    env.update({
        "PATH": os.pathsep.join([
            str(shim_dir),
            os.path.join(sysroot, "System32"),
            os.path.join(sysroot, "System32", "WindowsPowerShell", "v1.0"),
        ]),
        "PYTHONPATH": str(stubs),
        "USERPROFILE": str(profile),
        "TEMP": str(tmp),
        "TMP": str(tmp),
    })
    if command is not None:
        enc = base64.b64encode(command.encode("utf-16-le")).decode("ascii")
        cmd = [ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "RemoteSigned",
               "-EncodedCommand", enc]
    else:
        extra = ["-SkipObsidian"] + (["-SkipNode"] if skip_node else [])
        cmd = [ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "RemoteSigned",
               "-File", str(INSTALL_PS1), *args, *extra]
    p = subprocess.run(cmd, cwd=str(tmp), env=env, stdin=subprocess.DEVNULL,
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=TIMEOUT)
    return p.returncode, p.stdout + p.stderr, log.read_text(encoding="utf-8", errors="replace"), profile


def icacls_exe() -> str:
    return os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "System32", "icacls.exe")


def acl_entries(path: Path) -> list[str]:
    """The access entries icacls lists for path (read only)."""
    p = subprocess.run([icacls_exe(), str(path)], capture_output=True, text=True,
                       errors="replace", timeout=60, stdin=subprocess.DEVNULL)
    entries = []
    for ln in p.stdout.splitlines():
        s = ln.strip()
        if s.startswith(str(path)):
            s = s[len(str(path)):].strip()
        if ":(" in s:
            entries.append(s)
    return entries


def set_acl(path: Path, *icacls_args: str) -> bool:
    """Set a test fixture's ACL inside the temp folder."""
    p = subprocess.run([icacls_exe(), str(path), *icacls_args], capture_output=True,
                       text=True, errors="replace", timeout=60, stdin=subprocess.DEVNULL)
    return p.returncode == 0


def ps_tests(ps: str) -> None:
    # Parse check (no execution): the PowerShell parser over the file.
    script = (
        "$errs = $null; $tokens = $null; "
        f"[void][System.Management.Automation.Language.Parser]::ParseFile('{INSTALL_PS1}', "
        "[ref]$tokens, [ref]$errs); "
        "if ($errs.Count -gt 0) { $errs | ForEach-Object { $_.ToString() }; exit 1 } "
        "else { 'PARSE-OK' }"
    )
    enc = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    p = subprocess.run([ps, "-NoProfile", "-NonInteractive", "-EncodedCommand", enc],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=TIMEOUT, stdin=subprocess.DEVNULL)
    out = p.stdout + p.stderr
    check("ps1: parses with no errors", [
        (p.returncode == 0 and "PARSE-OK" in out, f"parser reported: {out.strip()[:300]}"),
    ], out)

    if os.name != "nt":
        record("SKIP", "ps1: runtime checks",
               "the .exe shims need Windows; PowerShell on this OS only parses the file")
        return
    stub, why = launcher_stub()
    if stub is None:
        record("SKIP", "ps1: runtime checks", why)
        return

    cases = [
        ("python3 and python both Python 3 -> python3",
         {"python3": {"version": "Python 3.12.0"}, "python": {"version": "Python 3.11.0"}},
         "python3"),
        ("python3 reporting Python 2 is skipped -> python",
         {"python3": {"version": "Python 2.7.18", "stderr": True},
          "python": {"version": "Python 3.11.0"}},
         "python"),
        ("only the py launcher -> py -3",
         {"py": {"version": "Python 3.12.0"}},
         "py -3"),
    ]
    for label, shims, expect in cases:
        with tempdir() as t:
            tmp = Path(t)
            rc, out, log, profile = run_ps(ps, stub, tmp, shims, ["-DryRun", "-NonInteractive"])
            check(f"ps1: {label}", [
                (f"Interpreter: {expect} (" in out, f"did not choose '{expect}'"),
                (f"would run: {expect} " in out and WIZ_NI in out,
                 "wizard command not printed with the same interpreter and --non-interactive"),
                ("-m pip install" not in log, "dry run invoked pip install"),
                ("first-run.py" not in log, "dry run started the wizard"),
                (not (profile / ".secrets").exists(), "dry run created the secrets folder"),
                (rc == 0, f"exit {rc}, expected 0"),
            ], out)

    # (item 3) a python3.cmd earlier on PATH is not an interpreter: .exe only.
    with tempdir() as t:
        tmp = Path(t)
        rc, out, log, _ = run_ps(ps, stub, tmp, {"python": {"version": "Python 3.11.0"}},
                                 ["-DryRun", "-NonInteractive"],
                                 cmd_shims={"python3": "Python 3.12.0"})
        check("ps1: a python3.cmd on PATH is ignored (.exe only) -> python", [
            ("Interpreter: python (" in out, "did not choose python.exe"),
            ("python3.cmd" not in log, "python3.cmd was run"),
        ], out)

    # Row 5n plus items 4 and 7: a pip failure is not swallowed; the remedy
    # makes no user-site claim and quotes paths; the new secrets folder is
    # restricted to one explicit, non-inherited entry.
    with tempdir() as t:
        tmp = Path(t)
        rc, out, log, profile = run_ps(
            ps, stub, tmp, {"python3": {"version": "Python 3.12.0"}},
            ["-NonInteractive"], missing=("mcp",))
        acl = acl_entries(profile / ".secrets")
        check("ps1: pip failure is reported, wizard reached, exit 3 for missing package", [
            ("pip install failed (exit 1)" in out, "pip failure not reported"),
            ("-m pip install -r" in log, "pip install was not attempted"),
            ("first-run.py --non-interactive" in log, "first-run not started with --non-interactive"),
            ("still missing" in out and "mcp" in out, "missing-package summary not printed"),
            (rc == 3, f"exit {rc}, expected 3"),
        ], out)
        check("ps1: remedy makes no user-site claim and quotes its paths", [
            ("user site-packages" not in out, "remedy claims user site-packages"),
            ('-m pip install -r "' in out, "requirements path not quoted in the remedy"),
            ('-m venv "' in out and ".charon-venv" in out, "venv remedy path missing or unquoted"),
        ], out)
        check("ps1: new secrets folder has one explicit full-control entry, nothing inherited", [
            (len(acl) == 1, f"{len(acl)} entries: {acl}"),
            (all("(I)" not in a for a in acl), f"inherited entries remain: {acl}"),
            (any("(OI)(CI)(F)" in a for a in acl), f"no (OI)(CI)(F) grant: {acl}"),
            ("Permissions restricted" in out, "no confirmation printed"),
        ], out)

    # (item 1) probes never import a module planted in the current folder.
    with tempdir() as t:
        tmp = Path(t)
        marker = plant_module(tmp, "mcp")
        rc, out, log, _ = run_ps(ps, stub, tmp, {"python3": {"version": "Python 3.12.0"}},
                                 ["-NonInteractive"], missing=("mcp",))
        check("ps1: import probes ignore a planted mcp.py in the current folder", [
            (not marker.exists(), "a probe imported mcp.py from the current folder"),
            (rc == 3, f"exit {rc}, expected 3 (mcp is really missing)"),
        ], out)

    # (item 2) a failed winget is a failure.
    with tempdir() as t:
        tmp = Path(t)
        rc, out, log, _ = run_ps(ps, stub, tmp, {"winget": {"rc": 1}}, ["-NonInteractive"])
        check("ps1: failed winget install is reported as a failure", [
            ("winget install --id Python.Python.3.12" in log, "winget was not called"),
            ("failed (exit 1)" in out, "winget failure not reported with its exit code"),
            ("Python installed" not in out, "a failed winget was reported as installed"),
            (rc != 0, "exit 0 after a failed Python install"),
        ], out)
    # (item 2) a fresh Python install cannot continue in this shell: exit 3, loudly.
    with tempdir() as t:
        tmp = Path(t)
        rc, out, log, _ = run_ps(ps, stub, tmp, {"winget": {"rc": 0}}, ["-NonInteractive"])
        check("ps1: -NonInteractive Python install via winget -> loud stop, exit 3 (not 0)", [
            (rc == 3, f"exit {rc}, expected 3"),
            ("did NOT run" in out, "no message that deps and the wizard did not run"),
        ], out)
    # (item 2) a Node install no longer ends the run: deps and wizard still happen.
    with tempdir() as t:
        tmp = Path(t)
        rc, out, log, _ = run_ps(ps, stub, tmp,
                                 {"winget": {"rc": 0}, "python3": {"version": "Python 3.12.0"}},
                                 ["-NonInteractive"], skip_node=False)
        check("ps1: -NonInteractive Node install via winget -> deps and wizard still run", [
            ("winget install --id OpenJS.NodeJS.LTS" in log, "Node was not installed via winget"),
            ("-m pip install -r" in log, "deps step skipped after the Node install"),
            ("first-run.py --non-interactive" in log, "wizard skipped after the Node install"),
            (rc == 0, f"exit {rc}, expected 0"),
        ], out)

    # (item 4) icacls failing is reported, not claimed as success.
    with tempdir() as t:
        tmp = Path(t)
        locked = tmp / "profile" / ".secrets"
        locked.mkdir(parents=True)
        # OWNER RIGHTS read-only: the owner loses its implicit right to change the ACL.
        if not set_acl(locked, "/inheritance:r", "/grant:r", "*S-1-3-4:(R)"):
            record("SKIP", "ps1: icacls failure is reported", "could not set up the locked folder")
        else:
            rc, out, log, _ = run_ps(ps, stub, tmp, {"python3": {"version": "Python 3.12.0"}},
                                     ["-NonInteractive"])
            check("ps1: icacls failure is reported with its exit code, never claimed", [
                ("icacls exit" in out, "icacls failure not reported with its exit code"),
                ("Permissions restricted" not in out, "claimed the folder was restricted"),
            ], out)
    # (item 4) no /T: a file already in the folder keeps its own entries.
    with tempdir() as t:
        tmp = Path(t)
        secrets = tmp / "profile" / ".secrets"
        secrets.mkdir(parents=True)
        child = secrets / "keep.txt"
        child.write_text("x", encoding="utf-8")
        if not set_acl(child, "/inheritance:r", "/grant:r", "*S-1-5-32-545:(R)"):
            record("SKIP", "ps1: no /T", "could not set up the child file")
        else:
            rc, out, log, _ = run_ps(ps, stub, tmp, {"python3": {"version": "Python 3.12.0"}},
                                     ["-NonInteractive"])
            acl = acl_entries(child)
            check("ps1: icacls is not recursive (no /T): an existing file's ACL is untouched", [
                (len(acl) == 1 and "(R)" in acl[0], f"child ACL changed: {acl}"),
            ], out)

    # (item 5) a run with no script folder (iex / scriptblock) is refused.
    with tempdir() as t:
        tmp = Path(t)
        command = (f"& ([scriptblock]::Create([IO.File]::ReadAllText('{INSTALL_PS1}'))) "
                   "-DryRun -NonInteractive -SkipObsidian -SkipNode; exit $LASTEXITCODE")
        rc, out, log, _ = run_ps(ps, stub, tmp, {"python3": {"version": "Python 3.12.0"}},
                                 [], command=command)
        check("ps1: run without its own folder (piped / iex) is refused (exit 66)", [
            (rc == 66, f"exit {rc}, expected 66"),
            ("refusing" in out.lower(), "no refusal message"),
            (log.strip() == "", "an interpreter was called"),
        ], out)

    # (item 6) restore passes --from with the backup it found.
    with tempdir() as t:
        tmp = Path(t)
        vol = tmp / "usbdrive"
        (vol / "Charon-Backup").mkdir(parents=True)
        (vol / ".charon-backup-target").write_text("", encoding="utf-8")
        command = (f"New-PSDrive -Name AAACharonTestVol -PSProvider FileSystem -Root '{vol}' | Out-Null; "
                   f"& '{INSTALL_PS1}' -AcceptDefaults -SkipObsidian -SkipNode; exit $LASTEXITCODE")
        rc, out, log, _ = run_ps(ps, stub, tmp, {"python3": {"version": "Python 3.12.0"}},
                                 [], command=command)
        restore = [ln for ln in log.splitlines() if "backup-brain.py" in ln]
        check("ps1: restore runs with --from <the found backup folder>", [
            (len(restore) == 1, f"backup-brain.py called {len(restore)} time(s), expected 1"),
            (bool(restore) and "--restore --from" in restore[0]
             and restore[0].rstrip().endswith("usbdrive\\Charon-Backup"),
             f"restore call was {restore[:1]!r}"),
        ], out)

    # (venv decision) a protected Python gets %USERPROFILE%\.charon-venv.
    with tempdir() as t:
        tmp = Path(t)
        rc, out, log, profile = run_ps(
            ps, stub, tmp,
            {"python3": {"version": "Python 3.12.0", "marker": "1", "venv": True, "pip": "managed"}},
            ["-NonInteractive"])
        check("ps1: PEP 668 -> creates .charon-venv, installs into it, wizard runs with it", [
            ((profile / ".charon-venv" / "pyvenv.cfg").is_file(), ".charon-venv was not created"),
            ("python3 -m venv" in log, "venv not created with the found Python"),
            ("venv-python -m pip install -r" in log, "requirements not installed into the venv"),
            ("venv-python " in log and "first-run.py --non-interactive" in log,
             "wizard not run with the venv's python"),
            ("python3 -m pip install" not in log, "pip install was run against the protected Python"),
            (rc == 0, f"exit {rc}, expected 0"),
        ], out)

    # (row 47) -AnswersFile reaches first-run; a missing one is refused.
    with tempdir() as t:
        tmp = Path(t)
        answers = tmp / "answers.yaml"
        answers.write_text("identity_name: Test User\n", encoding="utf-8")
        rc, out, log, _ = run_ps(ps, stub, tmp, {"python3": {"version": "Python 3.12.0"}},
                                 ["-NonInteractive", "-AnswersFile", str(answers)])
        wiz = [ln for ln in log.splitlines() if "first-run.py" in ln]
        check("ps1: -AnswersFile is passed to first-run", [
            (len(wiz) == 1 and "--answers" in wiz[0] and "answers.yaml" in wiz[0],
             f"wizard call was {wiz[:1]!r}"),
        ], out)
    for label, target in (("missing file", "nope.yaml"), ("a folder", "")):
        with tempdir() as t:
            tmp = Path(t)
            rc, out, log, profile = run_ps(ps, stub, tmp, {"python3": {"version": "Python 3.12.0"}},
                                           ["-NonInteractive", "-AnswersFile", str(tmp / target)])
            check(f"ps1: -AnswersFile naming {label} -> exit 64, nothing run", [
                (rc == 64, f"exit {rc}, expected 64"),
                (log.strip() == "", "an interpreter was called"),
                (not (profile / ".secrets").exists(), "the secrets folder was created"),
            ], out)

    # (row 47) a non-interactive wizard that stops leaves a loud message.
    with tempdir() as t:
        tmp = Path(t)
        rc, out, log, _ = run_ps(ps, stub, tmp,
                                 {"python3": {"version": "Python 3.12.0", "wizard_rc": 2}},
                                 ["-NonInteractive"])
        check("ps1: non-interactive wizard stop -> loud 'profile not set', its exit status", [
            (rc == 2, f"exit {rc}, expected 2"),
            ("profile is not set" in out, "no 'profile is not set' message"),
            ("-AnswersFile" in out, "the message does not name -AnswersFile"),
        ], out)


# --------------------------------------------------------------------------
# The probe strings themselves, against the real interpreter
# --------------------------------------------------------------------------

def extract(path: Path, prefix: str, ps: bool) -> str | None:
    """The single-quoted probe assigned on the line starting with prefix."""
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s.startswith(prefix):
            body = s[len(prefix):]
            if body.startswith("'") and body.endswith("'"):
                body = body[1:-1]
                return body.replace("''", "'") if ps else body
    return None


def probe_tests() -> None:
    """The shims answer the version and PEP 668 probes themselves, so run the
    real probe text from each installer through the real interpreter here,
    from a folder holding a planted module the probe must not see."""
    for path, ps in ((INSTALL_SH, False), (INSTALL_PS1, True)):
        tag = "ps1" if ps else "bash"
        dep = extract(path, "$DepProbe = " if ps else "DEP_PROBE=", ps)
        pep = extract(path, "$Pep668Probe = " if ps else "PEP668_PROBE=", ps)
        if dep is None or pep is None:
            record("FAIL", f"{tag}: probe strings found", "could not find DEP/PEP 668 probe")
            continue
        with tempdir() as t:
            tmp = Path(t)
            marker = plant_module(tmp, "charon_planted_probe_mod")
            r = subprocess.run([str(REAL_PY), "-c", dep, "os", "no_such_module_charon_test",
                                "json", "charon_planted_probe_mod"],
                               capture_output=True, text=True, timeout=60, cwd=str(tmp))
            r2 = subprocess.run([str(REAL_PY), "-c", pep], capture_output=True, text=True,
                                timeout=60, cwd=str(tmp))
            check(f"{tag}: import and PEP 668 probes run on a real interpreter, current folder unseen", [
                (r.returncode == 0
                 and r.stdout.strip() == "no_such_module_charon_test charon_planted_probe_mod",
                 f"import probe printed {r.stdout.strip()!r} / {r.stderr.strip()[:200]!r}"),
                (not marker.exists(), "the probe imported a module from the current folder"),
                (r2.returncode == 0 and r2.stdout.strip() in ("0", "1"),
                 f"PEP 668 probe printed {r2.stdout.strip()!r} / {r2.stderr.strip()[:200]!r}"),
            ], r.stdout + r.stderr + r2.stdout + r2.stderr)


def real_interpreter_dry_runs(bash: str | None, ps: str | None) -> None:
    """--dry-run with the machine's real interpreters on PATH. Side-effect free
    by design (probes only); HOME / USERPROFILE still point at a temp folder."""
    if bash:
        with tempdir() as t:
            tmp = Path(t)
            rc, out, log, home = run_bash(bash, tmp, {}, ["--dry-run", "--non-interactive"])
            check("bash: --dry-run with the real interpreter", [
                ("Interpreter: " in out, "no Python 3 interpreter chosen"),
                ("Traceback" not in out and "SyntaxError" not in out, "a probe raised"),
                (WIZ_NI in out, "wizard command not printed"),
                (rc in (0, 3), f"exit {rc}, expected 0 or 3"),
                (not (home / ".secrets").exists(), "dry run created HOME/.secrets"),
            ], out)
    if ps and os.name == "nt":
        with tempdir() as t:
            tmp = Path(t)
            profile = tmp / "profile"
            profile.mkdir()
            env = dict(os.environ)
            env.update({"USERPROFILE": str(profile), "TEMP": str(tmp), "TMP": str(tmp)})
            p = subprocess.run([ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy",
                                "RemoteSigned", "-File", str(INSTALL_PS1), "-DryRun",
                                "-NonInteractive", "-SkipObsidian", "-SkipNode"],
                               cwd=str(tmp), env=env, stdin=subprocess.DEVNULL,
                               capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=TIMEOUT)
            out = p.stdout + p.stderr
            check("ps1: -DryRun with the real interpreter", [
                ("Interpreter: " in out, "no Python 3 interpreter chosen"),
                ("Traceback" not in out and "SyntaxError" not in out, "a probe raised"),
                (WIZ_NI in out, "wizard command not printed"),
                (p.returncode in (0, 3), f"exit {p.returncode}, expected 0 or 3"),
                (not (profile / ".secrets").exists(), "dry run created the secrets folder"),
            ], out)


def main() -> int:
    print("Charon install script checks")
    print(f"repo: {REPO}\n")
    probe_tests()
    bash, why = find_bash()
    if bash:
        bash_tests(bash)
    else:
        record("SKIP", "bash: install.sh runs", why)
    ps, why_ps = find_powershell()
    if ps:
        ps_tests(ps)
    else:
        record("SKIP", "ps1: install.ps1 checks", why_ps)
    real_interpreter_dry_runs(bash, ps)

    passed = sum(1 for s, _, _ in RESULTS if s == "PASS")
    failed = sum(1 for s, _, _ in RESULTS if s == "FAIL")
    skipped = sum(1 for s, _, _ in RESULTS if s == "SKIP")
    # One line, last: the release gate (D41) shows only the final line, so the
    # failing check names have to be on it.
    failing = "; ".join(f"{n} [{d}]" for s, n, d in RESULTS if s == "FAIL")
    print(f"\nSummary: {passed} PASS, {failed} FAIL, {skipped} SKIP"
          + (f"  failed: {failing}" if failing else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
