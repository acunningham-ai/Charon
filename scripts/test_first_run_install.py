#!/usr/bin/env python3
"""End-to-end tests for the install side of first-run.py.

    python scripts/test_first_run_install.py

Every case drives the real entry point (`python scripts/first-run.py ...`) as a
subprocess, in a TEMPORARY COPY of the repo's scripts/ and .gitignore, with a
TEMPORARY HOME. The real Claude Code settings are never read or written: the copy's
post_install_wiring.py is replaced by a stub that only records how it was called.

What it proves:
  1. A fresh scaffold leaves `git status --porcelain` empty: every file the wizard
     creates is matched by .gitignore. Checked with a small gitignore matcher
     written here (tests may not call git); a fixture .gitignore missing one
     folder pattern must FAIL the same check.
  2. With stdin closed, the wizard finishes from an answers file and never calls
     input(); with a required answer missing it exits non-zero, names every gap,
     and writes nothing.
  3. On Windows, npm is started through its resolved npm.cmd path (a fake npm.cmd
     on PATH), and a failing npm reports its real exit code. Skipped elsewhere.
  4. The wizard calls post_install_wiring.py --mode install with its own
     interpreter, passes --non-interactive and --dry-run through, records the
     Agent Org answer in ~/.charon-agent-org.json, and is loud when the script
     exits 1 or is missing.
  5. Agent Org is on by default: no answer and no terminal records a default yes
     and says so loudly (with the off switch and the restart line), on install and
     in catch-up; Enter at the prompt means yes; a recorded "no", including one
     written by agent_org_setup.py --disable, is kept by every later run.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REAL_HOME = Path.home().resolve()
IS_WINDOWS = sys.platform.startswith("win")

results: list[tuple[str, bool, str]] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    results.append((name, bool(cond), detail))


# ---------- a small .gitignore matcher (the subset git uses here) ----------

def _glob_to_re(pat: str) -> re.Pattern:
    out, i = "", 0
    while i < len(pat):
        if pat.startswith("**/", i):
            out += "(?:.*/)?"
            i += 3
        elif pat.startswith("/**", i) and i + 3 == len(pat):
            out += "/.*"
            i += 3
        elif pat.startswith("**", i):
            out += ".*"
            i += 2
        elif pat[i] == "*":
            out += "[^/]*"
            i += 1
        elif pat[i] == "?":
            out += "[^/]"
            i += 1
        elif pat[i] == "[" and "]" in pat[i + 1:]:
            j = pat.index("]", i + 1)
            body = pat[i + 1:j]
            if body.startswith("!"):
                body = "^" + body[1:]
            out += "[" + body.replace("\\", "\\\\") + "]"
            i = j + 1
        else:
            out += re.escape(pat[i])
            i += 1
    return re.compile(out + r"\Z")


class GitIgnore:
    """Root .gitignore semantics: last match wins, `!` re-includes, a trailing `/`
    matches directories only, a pattern holding `/` is anchored to the root, and a
    file under an ignored directory stays ignored."""

    def __init__(self, text: str):
        self.rules = []
        for raw in text.splitlines():
            line = raw.rstrip()
            if not line or line.startswith("#"):
                continue
            neg = line.startswith("!")
            if neg:
                line = line[1:]
            if line.startswith("\\"):
                line = line[1:]
            dir_only = line.endswith("/")
            line = line.rstrip("/")
            anchored = "/" in line
            line = line.lstrip("/")
            if line:
                self.rules.append((neg, dir_only, anchored, _glob_to_re(line)))

    def _match(self, path: str, is_dir: bool) -> bool | None:
        result = None
        name = path.rsplit("/", 1)[-1]
        for neg, dir_only, anchored, rx in self.rules:
            if dir_only and not is_dir:
                continue
            if rx.match(path if anchored else name):
                result = not neg
        return result

    def ignored(self, path: str) -> bool:
        parts = path.split("/")
        for k in range(1, len(parts)):
            if self._match("/".join(parts[:k]), True):
                return True
        return bool(self._match(path, False))


def unignored(paths: set[str], gi: GitIgnore) -> list[str]:
    """What `git status --porcelain` would list among these new untracked files."""
    return sorted(p for p in paths if not gi.ignored(p))


# ---------- fixtures ----------

STUB_WIRING = '''import json, os, sys
log = os.environ.get("FR_TEST_WIRING_LOG")
if log:
    with open(log, "w", encoding="utf-8") as fh:
        json.dump({"argv": sys.argv[1:], "exe": sys.executable}, fh)
print("stub wiring: exit %d")
sys.exit(%d)
'''


def make_copy(root: Path, wiring_exit: int | None = 0) -> Path:
    """Temp copy of the parts of the repo the wizard runs from. wiring_exit None =
    no post_install_wiring.py at all."""
    repo = root / "repo"
    shutil.copytree(REPO / "scripts", repo / "scripts",
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "node_modules"))
    shutil.copy2(REPO / ".gitignore", repo / ".gitignore")
    (repo / "capture-pipeline").mkdir()
    shutil.copy2(REPO / "capture-pipeline" / "package.json", repo / "capture-pipeline" / "package.json")
    wiring = repo / "scripts" / "post_install_wiring.py"
    wiring.unlink(missing_ok=True)
    if wiring_exit is not None:
        wiring.write_text(STUB_WIRING % (wiring_exit, wiring_exit), encoding="utf-8")
    return repo


def make_env(root: Path, repo: Path, path_prefix: Path | None = None) -> dict:
    home = root / "home"
    home.mkdir(exist_ok=True)
    env = dict(os.environ)
    env.update({
        "HOME": str(home),
        "USERPROFILE": str(home),
        "HARNESS_VAULT_ROOT": str(repo),
        "HARNESS_MEMORY_ROOT": str(home / "memory"),
        "HARNESS_SECRETS_DIR": str(home / ".secrets"),
        "PYTHONIOENCODING": "utf-8",
        "PYTHONDONTWRITEBYTECODE": "1",
        "FR_TEST_WIRING_LOG": str(root / "wiring.json"),
        "HARNESS_HOOK_TEST": "1",
    })
    # PATH is pinned: no real node or npm can ever be found, so no case can start a
    # real `npm install` (network) by mistake. The wizard and the wiring run through
    # sys.executable; Windows keeps System32 for cmd.exe, which runs a fake npm.cmd.
    nobin = root / "nobin"
    nobin.mkdir(exist_ok=True)
    path = [str(nobin)]
    if IS_WINDOWS:
        path.append(str(Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"))
    if path_prefix is not None:
        path.insert(0, str(path_prefix))
    env["PATH"] = os.pathsep.join(path)
    if Path(env["HOME"]).resolve() == REAL_HOME:
        raise SystemExit("refusing to run: temp HOME resolves to the real home")
    return env


def run_wizard(repo: Path, env: dict, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(repo / "scripts" / "first-run.py"), *args],
        cwd=str(repo), env=env, stdin=subprocess.DEVNULL,
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=180)


def files_under(repo: Path) -> set[str]:
    return {p.relative_to(repo).as_posix() for p in repo.rglob("*") if p.is_file()}


def write_answers(root: Path, data: dict, name: str = "answers.json") -> Path:
    p = root / name
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


IDENTITY = {"identity_name": "Test User", "identity_role": "Tester", "identity_org": "Example org"}
# What the wizard must say when it switches Agent Org on by default.
SWITCHING_ON = "AGENT ORG IS BEING SWITCHED ON"
DISABLE = "scripts/agent_org_setup.py --disable"
RESTART = "RESTART CLAUDE CODE"


def agent_org_record(home: Path) -> dict:
    p = home / ".charon-agent-org.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}


def wiring_log(root: Path) -> dict | None:
    p = root / "wiring.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else None


def same_exe(a: str) -> bool:
    try:
        return os.path.normcase(str(Path(a).resolve())) == os.path.normcase(str(Path(sys.executable).resolve()))
    except OSError:
        return False


# ---------- 1. scaffold leaves git status clean (row 5c) ----------

with tempfile.TemporaryDirectory() as t:
    root = Path(t)
    repo = make_copy(root)
    env = make_env(root, repo)
    gi_text = (repo / ".gitignore").read_text(encoding="utf-8")
    gi = GitIgnore(gi_text)
    check("matcher sanity: shipped files are not ignored",
          not gi.ignored("scripts/first-run.py") and not gi.ignored("07-References/security-baselines.md")
          and not gi.ignored("capture-pipeline/package.json") and not gi.ignored("README.md"))
    check("matcher sanity: known private paths are ignored",
          gi.ignored("06-Decisions/x.md") and gi.ignored("scripts/lib/__pycache__/a.pyc")
          and gi.ignored("capture-pipeline/config.json") and gi.ignored("CLAUDE.local.md"))

    before = files_under(repo)
    r = run_wizard(repo, env, "--scaffold-only")
    new = files_under(repo) - before
    readmes = {f"{d}/README.md" for d in ("00-Inbox", "01-Daily", "02-BUs", "03-Domains", "04-People",
                                         "05-Meetings", "06-Decisions", "08-Projects", "09-Archive")}
    check("scaffold-only: exit 0 and all 9 folder READMEs created",
          r.returncode == 0 and readmes <= new, f"rc={r.returncode} new={sorted(new)[:12]} err={r.stderr[-300:]}")
    left = unignored(new, gi)
    check("scaffold-only: git status would be clean (every new file ignored)", not left, f"unignored={left}")

    # Negative: the same check must fail when one folder pattern is missing.
    broken = GitIgnore("\n".join(line for line in gi_text.splitlines() if line.strip() != "/04-People/"))
    left_broken = unignored(new, broken)
    check("negative: .gitignore without /04-People/ leaves 04-People/README.md visible",
          left_broken == ["04-People/README.md"], f"unignored={left_broken}")


# ---------- 2. non-interactive (row 5i) + 4. wiring (row 3) ----------

with tempfile.TemporaryDirectory() as t:
    root = Path(t)
    repo = make_copy(root, wiring_exit=0)
    env = make_env(root, repo)
    home = Path(env["HOME"])
    answers = write_answers(root, IDENTITY)
    before = files_under(repo)
    r = run_wizard(repo, env, "--non-interactive", "--answers", str(answers), "--no-logo")
    out = r.stdout + r.stderr
    role = home / "memory" / "user_role.md"
    check("non-interactive, stdin closed: completes (exit 0)", r.returncode == 0,
          f"rc={r.returncode} tail={out[-600:]}")
    check("non-interactive: answers file reached the memory file",
          role.is_file() and "Test User" in role.read_text(encoding="utf-8"))
    check("non-interactive: no input() call (no EOFError traceback)", "EOFError" not in out and "Traceback" not in out)
    log = wiring_log(root)
    check("wiring: called with --mode install --non-interactive",
          log is not None and log["argv"] == ["--mode", "install", "--non-interactive"], f"log={log}")
    check("wiring: run with the wizard's own interpreter", log is not None and same_exe(log["exe"]), f"log={log}")
    check("wiring exit 0: loud OK block printed", "CLAUDE CODE WIRING: OK" in out)
    rec = home / ".charon-agent-org.json"
    rec_data = json.loads(rec.read_text(encoding="utf-8")) if rec.is_file() else {}
    # On by default (2026-11-26, reverses X1): no terminal and no answer means yes.
    check("default on: no terminal and no answer: recorded as a default yes",
          rec_data.get("agent_org_enable") == "y" and rec_data.get("source") == "default", f"record={rec_data}")
    check("default on: no terminal and no answer: announced loudly, with the off switch and the restart line",
          SWITCHING_ON in out and DISABLE in out and RESTART in out, out[-1200:])
    check("state file cleared after a complete run", not (home / ".charon-first-run-state.json").exists())
    left = unignored(files_under(repo) - before, GitIgnore((repo / ".gitignore").read_text(encoding="utf-8")))
    check("full non-interactive install: git status would be clean", not left, f"unignored={left}")

with tempfile.TemporaryDirectory() as t:
    root = Path(t)
    repo = make_copy(root)
    env = make_env(root, repo)
    answers = write_answers(root, IDENTITY)
    r = run_wizard(repo, env, "--answers", str(answers), "--no-logo")  # no flag: stdin is not a TTY
    check("no --non-interactive flag but no TTY: completes without prompting",
          r.returncode == 0 and "Traceback" not in r.stderr, f"rc={r.returncode} err={r.stderr[-400:]}")

with tempfile.TemporaryDirectory() as t:
    root = Path(t)
    repo = make_copy(root)
    env = make_env(root, repo)
    home = Path(env["HOME"])
    r = run_wizard(repo, env, "--non-interactive", "--no-logo")
    check("negative: missing required answers exits non-zero (2)", r.returncode == 2, f"rc={r.returncode}")
    check("negative: message names every missing id",
          all(q in r.stderr for q in ("identity_name", "identity_role", "identity_org"))
          and "--answers" in r.stderr, r.stderr[-500:])
    check("negative: nothing written (no memory file, no state file, no wiring run)",
          not (home / "memory" / "user_role.md").exists()
          and not (home / ".charon-first-run-state.json").exists() and wiring_log(root) is None)

    r = run_wizard(repo, env, "--non-interactive", "--full", "--answers", str(write_answers(root, IDENTITY)),
                   "--no-logo")
    voice = ("voice_emphasis", "voice_cadence", "voice_personality", "voice_closer", "voice_anti_voice")
    check("negative: --full lists the five voice answers that have no default",
          r.returncode == 2 and all(v in r.stderr for v in voice) and "voice_refrains" not in r.stderr,
          r.stderr[-600:])

    bad = write_answers(root, {**IDENTITY, "not_a_question": "x", "agent_org_enable": "maybe",
                               "anthropic_key_value": "should-not-be-read"}, "bad.json")
    r = run_wizard(repo, env, "--non-interactive", "--answers", str(bad), "--no-logo")
    check("negative: bad answers file refused with each problem named",
          r.returncode == 2 and "not_a_question" in r.stderr and "agent_org_enable" in r.stderr
          and "anthropic_key_value" in r.stderr and "should-not-be-read" not in r.stderr, r.stderr[-600:])

# Answer "no" is recorded as no; --dry-run passes through and records nothing.
with tempfile.TemporaryDirectory() as t:
    root = Path(t)
    repo = make_copy(root)
    env = make_env(root, repo)
    home = Path(env["HOME"])
    r = run_wizard(repo, env, "--non-interactive", "--dry-run", "--no-logo",
                   "--answers", str(write_answers(root, IDENTITY)))
    log = wiring_log(root)
    check("wiring: --dry-run passed through", log is not None
          and log["argv"] == ["--mode", "install", "--non-interactive", "--dry-run"], f"log={log}")
    check("dry run: Agent Org record not written", not (home / ".charon-agent-org.json").exists())
    r = run_wizard(repo, env, "--non-interactive", "--no-logo",
                   "--answers", str(write_answers(root, {**IDENTITY, "agent_org_enable": "n"}, "no.json")))
    rec = home / ".charon-agent-org.json"
    check("answer no is recorded as n", r.returncode == 0 and rec.is_file()
          and json.loads(rec.read_text(encoding="utf-8")).get("agent_org_enable") == "n")

with tempfile.TemporaryDirectory() as t:
    root = Path(t)
    repo = make_copy(root, wiring_exit=1)
    env = make_env(root, repo)
    r = run_wizard(repo, env, "--non-interactive", "--no-logo", "--answers", str(write_answers(root, IDENTITY)))
    out = r.stdout + r.stderr
    check("wiring exit 1: loud NOT COMPLETE block with the fix command",
          "NOT COMPLETE (exit 1)" in out and "post_install_wiring.py --mode install" in out
          and "=" * 20 in out, out[-700:])
    check("wiring exit 1: wizard itself still exits 0 (files are written)", r.returncode == 0)

with tempfile.TemporaryDirectory() as t:
    root = Path(t)
    repo = make_copy(root, wiring_exit=None)
    env = make_env(root, repo)
    r = run_wizard(repo, env, "--non-interactive", "--no-logo", "--answers", str(write_answers(root, IDENTITY)))
    out = r.stdout + r.stderr
    check("wiring script missing: loud warning, not silence",
          "WIRING DID NOT RUN" in out and "post_install_wiring.py is missing" in out, out[-600:])


# ---------- 5. review fixes (backlog row 48) ----------

def snapshot(*roots: Path) -> set[str]:
    """Every file AND folder under the roots (folders count: A1 is about mkdir)."""
    out: set[str] = set()
    for base in roots:
        if base.exists():
            out |= {f"{base.name}/{p.relative_to(base).as_posix()}" for p in base.rglob("*")}
    return out


VOICE = {"voice_emphasis": "plain", "voice_cadence": "short", "voice_personality": "dry",
         "voice_closer": "thanks", "voice_anti_voice": "hype"}

# An explicit yes in an answers file is recorded as an answer, not as a default.
with tempfile.TemporaryDirectory() as t:
    root = Path(t)
    repo = make_copy(root)
    env = make_env(root, repo)
    home = Path(env["HOME"])
    r = run_wizard(repo, env, "--non-interactive", "--no-logo",
                   "--answers", str(write_answers(root, {**IDENTITY, "agent_org_enable": "y"})))
    rec = agent_org_record(home)
    check("agent_org_enable: y in an answers file is recorded as y (source answer), no default notice",
          r.returncode == 0 and rec.get("agent_org_enable") == "y" and rec.get("source") == "answer"
          and SWITCHING_ON not in r.stdout, (r.stdout + r.stderr)[-500:])

# Catch-up (the /charon-update path) with no terminal and no answer: on by default.
with tempfile.TemporaryDirectory() as t:
    root = Path(t)
    repo = make_copy(root)
    env = make_env(root, repo)
    home = Path(env["HOME"])
    r = run_wizard(repo, env, "--catch-up", "--non-interactive")
    state = home / ".charon-first-run-state.json"
    saved = json.loads(state.read_text(encoding="utf-8")) if state.is_file() else {}
    rec, log = agent_org_record(home), wiring_log(root)
    check("default on: catch-up without a terminal saves yes, records a default yes, runs the update wiring",
          saved.get("agent_org_enable") == "y" and rec.get("agent_org_enable") == "y"
          and rec.get("source") == "default" and log is not None
          and log["argv"] == ["--mode", "update", "--non-interactive"],
          f"rc={r.returncode} saved={saved} rec={rec} wiring={log} out={(r.stdout + r.stderr)[-500:]}")
    check("default on: catch-up without a terminal announces it, with the off switch and the restart line",
          SWITCHING_ON in r.stdout and DISABLE in r.stdout and RESTART in r.stdout, r.stdout[-900:])

# A recorded "no" stays no: on a later install and on a later update (catch-up).
with tempfile.TemporaryDirectory() as t:
    root = Path(t)
    repo = make_copy(root)
    env = make_env(root, repo)
    home = Path(env["HOME"])
    (home / ".charon-agent-org.json").write_text(json.dumps({"agent_org_enable": "n"}), encoding="utf-8")
    r = run_wizard(repo, env, "--non-interactive", "--no-logo", "--answers", str(write_answers(root, IDENTITY)))
    rec = agent_org_record(home)
    check("recorded no, later install (no terminal): kept as no, not switched on, says off",
          r.returncode == 0 and rec.get("agent_org_enable") == "n" and SWITCHING_ON not in r.stdout
          and "using your recorded answer (no)" in r.stdout and "Agent Org is off" in r.stdout,
          f"rec={rec} out={(r.stdout + r.stderr)[-700:]}")
    (root / "wiring.json").unlink(missing_ok=True)
    r = run_wizard(repo, env, "--catch-up", "--non-interactive")
    state = home / ".charon-first-run-state.json"
    saved = json.loads(state.read_text(encoding="utf-8")) if state.is_file() else {}
    rec = agent_org_record(home)
    check("recorded no, later update (catch-up, no terminal): kept as no, not switched on",
          rec.get("agent_org_enable") == "n" and saved.get("agent_org_enable") == "n"
          and SWITCHING_ON not in r.stdout,
          f"rc={r.returncode} saved={saved} rec={rec} out={(r.stdout + r.stderr)[-600:]}")

# agent_org_setup.py --disable after a default-on install: later updates leave it off.
with tempfile.TemporaryDirectory() as t:
    root = Path(t)
    repo = make_copy(root)
    env = make_env(root, repo)
    home = Path(env["HOME"])
    r = run_wizard(repo, env, "--non-interactive", "--no-logo", "--answers", str(write_answers(root, IDENTITY)))
    before = agent_org_record(home).get("agent_org_enable")
    d = subprocess.run([sys.executable, str(repo / "scripts" / "agent_org_setup.py"), "--disable"],
                       cwd=str(repo), env=env, stdin=subprocess.DEVNULL, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=120)
    after_disable = agent_org_record(home).get("agent_org_enable")
    r = run_wizard(repo, env, "--catch-up", "--non-interactive")
    rec = agent_org_record(home)
    check("disable after a default-on install: records no, and a later update keeps it no",
          before == "y" and d.returncode == 0 and after_disable == "n"
          and rec.get("agent_org_enable") == "n" and SWITCHING_ON not in r.stdout,
          f"before={before} disable_rc={d.returncode} disable_out={d.stdout[-300:]} rec={rec} "
          f"out={(r.stdout + r.stderr)[-500:]}")
    # --quick: catch-up left a state file, which would otherwise resume in full mode.
    # The state file holds "n" now, so remove it: the durable record alone must carry the no.
    (home / ".charon-first-run-state.json").unlink(missing_ok=True)
    r = run_wizard(repo, env, "--non-interactive", "--quick", "--no-logo",
                   "--answers", str(write_answers(root, IDENTITY)))
    check("disable: a later reinstall (no terminal, no state file) completes and keeps it no",
          r.returncode == 0 and agent_org_record(home).get("agent_org_enable") == "n"
          and SWITCHING_ON not in r.stdout and "using your recorded answer (no)" in r.stdout,
          f"rc={r.returncode} out={(r.stdout + r.stderr)[-500:]}")

# Interactive Enter at the Agent Org question means yes; Enter on a recorded "no" keeps it.
# ask_question() is the real prompt, driven in-process with input() replaced.
import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location("first_run_for_test", REPO / "scripts" / "first-run.py")
FR = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(FR)  # type: ignore[union-attr]
_q = next(q for q in FR.load_questions()["questions"] if q["id"] == "agent_org_enable")
_prompts: list[str] = []


def _enter(prompt: str = "") -> str:
    _prompts.append(prompt)
    return ""


FR.input = _enter  # module global shadows the builtin inside first-run.py
import contextlib as _cl  # noqa: E402
import io as _io  # noqa: E402

with _cl.redirect_stdout(_io.StringIO()):
    enter_fresh = FR.ask_question(_q, None)
    enter_on_no = FR.ask_question(_q, "n")
check("interactive Enter on the Agent Org question: yes (the [y] default is shown)",
      enter_fresh == "y" and any("[y]" in p for p in _prompts), f"answer={enter_fresh!r} prompts={_prompts}")
check("interactive Enter on a recorded no: keeps no", enter_on_no == "n", f"answer={enter_on_no!r}")
check("agent_org_enable is no longer explicit-answer-only", "agent_org_enable" not in FR.EXPLICIT_ANSWER_ONLY)

# A1 + --full nothing written: refused and dry runs create no folder anywhere.
with tempfile.TemporaryDirectory() as t:
    root = Path(t)
    repo = make_copy(root)
    env = make_env(root, repo)
    home = Path(env["HOME"])
    newvault, newsecrets = root / "nv" / "deep", root / "ns" / "deep"
    before = snapshot(home, repo)
    ans = write_answers(root, {**IDENTITY, "vault_path": str(newvault), "secrets_path": str(newsecrets)})
    r = run_wizard(repo, env, "--non-interactive", "--full", "--no-logo", "--answers", str(ans))
    check("A1: --full refused run (missing voice answers) exits 2", r.returncode == 2, r.stderr[-400:])
    check("A1: refused --full run creates no folder (vault, secrets) and writes nothing",
          not (root / "nv").exists() and not (root / "ns").exists() and snapshot(home, repo) == before,
          f"nv={(root / 'nv').exists()} ns={(root / 'ns').exists()} "
          f"diff={sorted(snapshot(home, repo) ^ before)[:10]}")

    ans = write_answers(root, {**IDENTITY, **VOICE, "vault_path": str(root / "nv2" / "deep"),
                               "secrets_path": str(root / "ns2" / "deep")}, "full.json")
    before = snapshot(home, repo)
    r = run_wizard(repo, env, "--non-interactive", "--full", "--dry-run", "--no-logo", "--answers", str(ans))
    check("A1: --full --dry-run completes", r.returncode == 0, (r.stdout + r.stderr)[-500:])
    check("A1: --full --dry-run writes nothing (no folder, no file, under HOME or the repo)",
          snapshot(home, repo) == before and not (root / "nv2").exists() and not (root / "ns2").exists(),
          f"nv2={(root / 'nv2').exists()} ns2={(root / 'ns2').exists()} "
          f"diff={sorted(snapshot(home, repo) ^ before)[:10]}")

    before = snapshot(home, repo)
    r = run_wizard(repo, env, "--non-interactive", "--quick", "--dry-run", "--no-logo",
                   "--answers", str(write_answers(root, IDENTITY)))
    check("A1: quick --dry-run does not create ~/.secrets",
          r.returncode == 0 and not (home / ".secrets").exists() and snapshot(home, repo) == before,
          f"rc={r.returncode} diff={sorted(snapshot(home, repo) ^ before)[:10]}")

    r = run_wizard(repo, env, "--non-interactive", "--no-logo")
    check("A1: refused quick run (no identity) does not create ~/.secrets",
          r.returncode == 2 and not (home / ".secrets").exists(), f"rc={r.returncode}")

    blocker = root / "afile"
    blocker.write_text("x", encoding="utf-8")
    r = run_wizard(repo, env, "--non-interactive", "--no-logo",
                   "--answers", str(write_answers(root, {**IDENTITY, "vault_path": str(blocker / "sub")}, "b.json")))
    check("A1: a vault path under an existing FILE is still refused", r.returncode == 2
          and "vault_path" in r.stderr, r.stderr[-400:])

# A2, A3, and the YAML tag, number and NUL cases: every bad answers file is refused cleanly.
with tempfile.TemporaryDirectory() as t:
    root = Path(t)
    repo = make_copy(root)
    env = make_env(root, repo)
    home = Path(env["HOME"])

    def refused(name: str, text: str) -> subprocess.CompletedProcess:
        p = root / name
        p.write_text(text, encoding="utf-8")
        return run_wizard(repo, env, "--non-interactive", "--no-logo", "--answers", str(p))

    big = "z" * 25_000
    lines = ", ".join(["*a"] * 1000)
    r = refused("alias.yaml", "identity_name: Test\nidentity_role: T\nidentity_org: O\n"
                f"org_specific_rules: [&a \"{big}\", {lines}]\n")
    check("A2: aliased multiline list is capped BEFORE it is joined",
          r.returncode == 2 and "org_specific_rules" in r.stderr and "list answer" in r.stderr
          and big[:200] not in r.stderr, r.stderr[-400:])

    r = refused("broken.yaml", 'identity_name: Test\nidentity_role: "MARKER_IN_FILE_TEXT\n  : : x\n')
    check("A3: YAML parse error is reported without echoing the file's text",
          r.returncode == 2 and "MARKER_IN_FILE_TEXT" not in r.stderr and "line" in r.stderr,
          r.stderr[-400:])

    r = refused("tag.yaml", "identity_name: !!python/name:builtins.MARKER_IN_TAG\n"
                            "identity_role: T\nidentity_org: O\n")
    check("YAML tag: a python tag is refused (safe_load) and the tag text is not echoed",
          r.returncode == 2 and "MARKER_IN_TAG" not in r.stderr
          and not (home / "memory" / "user_role.md").exists(), r.stderr[-400:])

    # Unquoted 7:00 is YAML 1.1 base 60: the number 420. (07:00 stays text in PyYAML.)
    r = refused("number.yaml", "identity_name: Test\nidentity_role: T\nidentity_org: O\n"
                               "pipeline_schedule_time: 7:00\n")
    check("YAML number: unquoted 7:00 (read as 420) is refused, asking for quotes",
          r.returncode == 2 and "pipeline_schedule_time" in r.stderr and "quotes" in r.stderr,
          r.stderr[-400:])

    r = refused("numkey.yaml", "identity_name: Test\nidentity_role: T\nidentity_org: O\n12345: x\n")
    check("YAML number: a numeric key is refused by name, no traceback",
          r.returncode == 2 and "12345" in r.stderr and "Traceback" not in r.stderr, r.stderr[-400:])

    r = refused("nul.json", json.dumps({**IDENTITY, "identity_name": "a\u0000b"}))
    check("NUL: an answer holding a NUL character is refused",
          r.returncode == 2 and "identity_name" in r.stderr and "NUL" in r.stderr
          and not (home / "memory" / "user_role.md").exists(), r.stderr[-400:])

# A4: an unattended overwrite of a memory file keeps a backup; quick mode does not use cwd.
with tempfile.TemporaryDirectory() as t:
    root = Path(t)
    repo = make_copy(root)
    env = make_env(root, repo)
    home = Path(env["HOME"])
    run_wizard(repo, env, "--non-interactive", "--no-logo", "--answers", str(write_answers(root, IDENTITY)))
    r = run_wizard(repo, env, "--non-interactive", "--no-logo",
                   "--answers", str(write_answers(root, {**IDENTITY, "identity_name": "Second Name"}, "2.json")))
    mem = home / "memory"
    backups = [p for p in mem.glob("user_role.md.bak-first-run-*")] if mem.is_dir() else []
    check("A4: unattended overwrite of user_role.md keeps a backup holding the old text",
          r.returncode == 0 and len(backups) == 1 and "Test User" in backups[0].read_text(encoding="utf-8")
          and "Second Name" in (mem / "user_role.md").read_text(encoding="utf-8"),
          f"backups={[b.name for b in backups]} out={(r.stdout + r.stderr)[-400:]}")
    check("A4: the backup is named in the output", bool(backups) and backups[0].name in r.stdout)

with tempfile.TemporaryDirectory() as t:
    root = Path(t)
    repo = make_copy(root)
    env = make_env(root, repo)
    env.pop("HARNESS_VAULT_ROOT")
    elsewhere = root / "elsewhere"
    elsewhere.mkdir()
    r = subprocess.run([sys.executable, str(repo / "scripts" / "first-run.py"), "--non-interactive", "--quick",
                        "--no-logo", "--answers", str(write_answers(root, IDENTITY))],
                       cwd=str(elsewhere), env=env, stdin=subprocess.DEVNULL, capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=180)
    check("A4: quick mode run from another folder does not scaffold the vault into the cwd",
          r.returncode == 0 and not any(elsewhere.iterdir()) and (repo / "04-People" / "README.md").is_file(),
          f"rc={r.returncode} cwd_has={[p.name for p in elsewhere.iterdir()]} out={(r.stdout + r.stderr)[-400:]}")
    check("A4: quick mode names the vault it chose", f"Vault: {repo.resolve()}" in r.stdout, r.stdout[-600:])

# E1 / E2: a wiring failure is the last thing printed, and a hung wiring call is stopped.
with tempfile.TemporaryDirectory() as t:
    root = Path(t)
    repo = make_copy(root, wiring_exit=1)
    env = make_env(root, repo)
    r = run_wizard(repo, env, "--non-interactive", "--no-logo", "--answers", str(write_answers(root, IDENTITY)))
    tail = [ln for ln in r.stdout.splitlines() if ln.strip()][-3:]
    check("E1: wiring failure is repeated as the LAST lines of the run",
          any("NOT COMPLETE" in ln for ln in tail), f"tail={tail}")
    check("E1: wiring failure is also written to stderr", "Claude Code wiring did not complete" in r.stderr,
          r.stderr[-400:])

with tempfile.TemporaryDirectory() as t:
    root = Path(t)
    repo = make_copy(root)
    (repo / "scripts" / "post_install_wiring.py").write_text(
        "import time\ntime.sleep(40)\n", encoding="utf-8")
    env = make_env(root, repo)
    env["HARNESS_WIRING_TIMEOUT"] = "3"
    import time as _time
    t0 = _time.monotonic()
    r = run_wizard(repo, env, "--non-interactive", "--no-logo", "--answers", str(write_answers(root, IDENTITY)))
    took = _time.monotonic() - t0
    out = r.stdout + r.stderr
    check("E2: a hung wiring call is stopped by the timeout and reported loudly",
          took < 30 and "TIMED OUT" in out and r.returncode == 0, f"took={took:.1f}s tail={out[-500:]}")


# ---------- 3. npm through npm.cmd (row 5h) ----------

if IS_WINDOWS:
    for npm_exit in (0, 7):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            repo = make_copy(root)
            fake = root / "fakebin"
            fake.mkdir()
            marker = root / "npm-ran.txt"
            (fake / "npm.cmd").write_bytes(
                ("@echo off\r\n"
                 f'echo %CD%> "{marker}"\r\n'
                 f'echo %*>> "{marker}"\r\n'
                 f"exit /b {npm_exit}\r\n").encode("ascii"))
            (fake / "node.cmd").write_bytes(b"@echo off\r\nexit /b 0\r\n")
            env = make_env(root, repo, path_prefix=fake)
            ans = write_answers(root, {**IDENTITY, "capture_pipeline_setup": "y"})
            r = run_wizard(repo, env, "--non-interactive", "--no-logo", "--answers", str(ans))
            out = r.stdout + r.stderr
            lines = marker.read_text(encoding="utf-8", errors="replace").splitlines() if marker.exists() else []
            if npm_exit == 0:
                check("npm: fake npm.cmd on PATH was run with `install` in capture-pipeline/",
                      len(lines) >= 2
                      and Path(lines[0].strip()).resolve() == (repo / "capture-pipeline").resolve()
                      and lines[1].strip() == "install" and "npm install: ok" in out,
                      f"marker={lines} tail={out[-500:]}")
            else:
                check("npm failure: the real exit code is reported",
                      bool(lines) and "npm install failed (exit 7" in out, f"tail={out[-500:]}")
    # N1: an npm.cmd / node.cmd sitting in the CURRENT folder is never run: not through
    # the Windows "current folder first" search (older Pythons), and not through a
    # relative "." entry on PATH (every platform and Python). PATH holds nothing else
    # but an empty folder, so no real npm can be found and nothing reaches the network.
    for label, rel_dot in (("cwd search", False), ("'.' on PATH", True)):
        with tempfile.TemporaryDirectory() as t:
            root = Path(t)
            repo = make_copy(root)
            marker = root / "cwd-npm-ran.txt"
            (repo / "npm.cmd").write_bytes(f'@echo off\r\necho ran> "{marker}"\r\nexit /b 0\r\n'.encode("ascii"))
            (repo / "node.cmd").write_bytes(b"@echo off\r\nexit /b 0\r\n")
            empty = root / "emptybin"
            empty.mkdir()
            env = make_env(root, repo)
            env["PATH"] = os.pathsep.join(([os.curdir] if rel_dot else []) + [str(empty)])
            env.pop("NoDefaultCurrentDirectoryInExePath", None)
            ans = write_answers(root, {**IDENTITY, "capture_pipeline_setup": "y"})
            r = run_wizard(repo, env, "--non-interactive", "--no-logo", "--answers", str(ans))
            out = r.stdout + r.stderr
            check(f"N1 ({label}): npm.cmd in the current folder is NOT run", not marker.exists(), out[-500:])
            check(f"N1 ({label}): the run says it ignored the copy in the current folder",
                  "current folder" in out and "Node.js / npm not detected" in out, out[-600:])
else:
    print("SKIP npm.cmd cases: npm.cmd resolution is Windows-only; this platform runs npm directly.")


# ---------- report ----------

failed = [r for r in results if not r[1]]
for name, ok, detail in results:
    print(f"{'PASS' if ok else 'FAIL'}  {name}")
    if not ok and detail:
        print(f"      {detail}")
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
