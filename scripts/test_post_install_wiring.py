#!/usr/bin/env python3
"""Tests for post_install_wiring.py and statusline.py.

Every case runs against a temporary HOME, a temporary settings file and a
temporary stand-in repo. The real user settings are never read or written: the
functions that would find them are replaced with ones that fail the test.

    python scripts/test_post_install_wiring.py
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import agent_org_setup as aos  # noqa: E402
import post_install_wiring as W  # noqa: E402

GOOD = (2, 1, 292)
OLD = (2, 1, 100)
STATUSLINE = HERE / "statusline.py"
WIRING = HERE / "post_install_wiring.py"
ANSI = re.compile(r"\x1b\[[0-9;]*m")
# The three things every run that switches Agent Org on must say.
SWITCHED = "AGENT ORG WAS SWITCHED ON"
DISABLE = "scripts/agent_org_setup.py --disable"
RESTART = "RESTART CLAUDE CODE"
results: list[tuple[str, bool]] = []


def check(name: str, cond: bool) -> None:
    results.append((name, bool(cond)))


def _forbidden(*_a, **_k):
    raise AssertionError("test reached for the real settings file or the real claude binary")


# Guards: nothing below may fall back to the user's own settings or run `claude`.
aos.settings_path = _forbidden  # type: ignore[assignment]
aos.claude_version = _forbidden  # type: ignore[assignment]


def make_repo(root: Path, launcher: bool = True) -> Path:
    repo = root / "repo"
    (repo / "plugins" / "agent-org-reporter" / ".claude-plugin").mkdir(parents=True)
    (repo / "plugins" / "agent-org-reporter" / ".claude-plugin" / "plugin.json").write_text("{}", encoding="utf-8")
    (repo / "scripts").mkdir()
    (repo / "scripts" / "statusline.py").write_text("# stand-in\n", encoding="utf-8")
    if launcher:
        (repo / "scripts" / "hook").write_text("# stand-in launcher\n", encoding="utf-8")
    return repo


def answer(home: Path, value: str) -> None:
    (home / W.STATE_NAME).write_text(json.dumps({"agent_org_enable": value}), encoding="utf-8")


def go(args: list[str], home: Path, repo: Path, version=GOOD, interactive=False, replies=None):
    lines: list[str] = []
    replies = list(replies or [])
    asked: list[str] = []

    def ask(prompt: str) -> str:
        asked.append(prompt)
        return replies.pop(0) if replies else ""

    rc = W.run(args, home=home, repo=repo, version=version, ask=ask, interactive=interactive, out=lines.append)
    return rc, "\n".join(lines), asked


def backups(settings: Path) -> list[str]:
    return sorted(p.name for p in settings.parent.iterdir() if ".bak-" in p.name)


def registered(settings: Path, repo: Path) -> bool:
    return W.agent_org_registered(settings, repo)[0] is True


def case(name: str):
    tmp = tempfile.TemporaryDirectory()
    root = Path(tmp.name)
    home = root / "home"
    (home / ".claude").mkdir(parents=True)
    return tmp, home, make_repo(root), home / ".claude" / "settings.json"


# ---------- 1. fresh settings: both wired, second run changes nothing ----------
tmp, home, repo, settings = case("fresh")
with tmp:
    answer(home, "y")
    args = ["--mode", "install", "--non-interactive", "--settings", str(settings)]
    rc, out, _ = go(args, home, repo)
    data = json.loads(settings.read_text(encoding="utf-8"))
    want = W.desired_statusline(repo)
    check("fresh: exit 0", rc == 0)
    check("fresh: Agent Org registered", registered(settings, repo))
    check("fresh: switching it on is announced, with the off switch and the restart line",
          SWITCHED in out and DISABLE in out and RESTART in out and "recorded answer is yes" in out)
    check("fresh: statusLine points at the launcher + statusline.py",
          data.get("statusLine") == {"type": "command", "command": want}
          and want.startswith('sh "') and want.endswith('/scripts/hook" scripts/statusline.py'))
    before, bk = settings.read_text(encoding="utf-8"), backups(settings)
    rc2, out2, _ = go(args, home, repo)
    check("fresh: second run exit 0, settings byte-identical, no new backup",
          rc2 == 0 and settings.read_text(encoding="utf-8") == before and backups(settings) == bk)
    check("fresh: second run (already on) announces nothing", SWITCHED not in out2)
    rc3, out3, _ = go(["--mode", "update", "--check", "--settings", str(settings)], home, repo)
    check("fresh: --check afterwards exit 0 and reports both OK",
          rc3 == 0 and "Agent Org: OK" in out3 and "Status line: OK" in out3)
    rc4, _, _ = go(["--mode", "update", "--non-interactive", "--settings", str(settings)], home, repo)
    check("fresh: update mode on a wired install changes nothing",
          rc4 == 0 and settings.read_text(encoding="utf-8") == before)

# ---------- 2. existing different statusLine is never clobbered ----------
tmp, home, repo, settings = case("different")
with tmp:
    answer(home, "y")
    theirs = {"type": "command", "command": "my-own-bar --fancy"}
    settings.write_text(json.dumps({"statusLine": theirs, "model": "keep-me"}), encoding="utf-8")
    args = ["--mode", "update", "--non-interactive", "--settings", str(settings)]
    rc, out, asked = go(args, home, repo)
    data = json.loads(settings.read_text(encoding="utf-8"))
    check("different, non-interactive: exit 1", rc == 1)
    check("different, non-interactive: their statusLine untouched", data["statusLine"] == theirs)
    check("different, non-interactive: reported with the fix command",
          "my-own-bar --fancy" in out and "Fix (Status line)" in out and "post_install_wiring.py --mode update" in out)
    check("different, non-interactive: nothing asked", asked == [])
    check("different: Agent Org still wired and other settings kept",
          registered(settings, repo) and data["model"] == "keep-me")

    snap = settings.read_text(encoding="utf-8")
    rc, out, asked = go(["--mode", "update", "--check", "--settings", str(settings)], home, repo)
    check("different, --check: exit 1, file byte-identical", rc == 1 and settings.read_text(encoding="utf-8") == snap)

    rc, out, asked = go(["--mode", "update", "--settings", str(settings)], home, repo, interactive=True, replies=["n"])
    check("different, interactive 'n': asked once, kept", len(asked) == 1 and
          json.loads(settings.read_text(encoding="utf-8"))["statusLine"] == theirs)
    rc, out, asked = go(["--mode", "update", "--settings", str(settings)], home, repo, interactive=True, replies=[""])
    check("different, interactive Enter: default is keep",
          json.loads(settings.read_text(encoding="utf-8"))["statusLine"] == theirs)
    n_bk = len(backups(settings))
    rc, out, asked = go(["--mode", "update", "--settings", str(settings)], home, repo, interactive=True, replies=["y"])
    data = json.loads(settings.read_text(encoding="utf-8"))
    check("different, interactive 'y': replaced, with a backup holding theirs",
          rc == 0 and data["statusLine"]["command"] == W.desired_statusline(repo)
          and len(backups(settings)) == n_bk + 1
          and any("my-own-bar" in (settings.parent / b).read_text(encoding="utf-8") for b in backups(settings)))

# ---------- 3. enable failure: exit 1 with the fix text, retried once ----------
tmp, home, repo, settings = case("enable-fails")
with tmp:
    answer(home, "y")
    calls = []
    real_enable = aos.enable

    def counting_enable(*a, **k):
        calls.append(1)
        return real_enable(*a, **k)

    aos.enable = counting_enable  # type: ignore[assignment]
    try:
        rc, out, _ = go(["--mode", "install", "--non-interactive", "--settings", str(settings)], home, repo, version=OLD)
    finally:
        aos.enable = real_enable  # type: ignore[assignment]
    check("enable fails: exit 1", rc == 1)
    check("enable fails: tried twice (one retry)", len(calls) == 2)
    check("enable fails: prints the reason and the fix command",
          "2.1.287" in out and "Fix (Agent Org)" in out and "post_install_wiring.py --mode update" in out)
    check("enable fails: not registered", not registered(settings, repo))

# ---------- 4. doctor: answered yes but not registered; missing status line ----------
tmp, home, repo, settings = case("doctor")
with tmp:
    answer(home, "yes")
    settings.write_text(json.dumps({"model": "x"}), encoding="utf-8")
    snap = settings.read_text(encoding="utf-8")
    rc, out, _ = go(["--mode", "update", "--check", "--settings", str(settings)], home, repo)
    check("check: flags 'answered yes but not registered'", rc == 1 and "answered yes but not registered" in out)
    check("check: flags the missing status line", "Status line: NOT WIRED" in out and "not set" in out)
    check("check: writes nothing", settings.read_text(encoding="utf-8") == snap and backups(settings) == [])
    (home / W.STATE_NAME).unlink()
    (home / W.RECORD_NAME).write_text(json.dumps({"agent_org_enable": "y"}), encoding="utf-8")
    rc, out, _ = go(["--mode", "update", "--check", "--settings", str(settings)], home, repo)
    check("check: reads the answer from the durable record too", "answered yes but not registered" in out)

# ---------- 5. a recorded 'no' is respected, on install AND update, interactive or not ----------
tmp, home, repo, settings = case("no")
with tmp:
    answer(home, "n")
    rc, out, _ = go(["--mode", "install", "--non-interactive", "--settings", str(settings)], home, repo)
    check("answered no: Agent Org left off, status line wired, exit 0",
          rc == 0 and not registered(settings, repo) and "answered no" in out
          and json.loads(settings.read_text(encoding="utf-8"))["statusLine"]["command"] == W.desired_statusline(repo))
    check("answered no, install: nothing announced as switched on", SWITCHED not in out)
    rc, out, asked = go(["--mode", "update", "--non-interactive", "--settings", str(settings)], home, repo)
    check("answered no, update (no terminal): still off, exit 0",
          rc == 0 and not registered(settings, repo) and "answered no" in out and SWITCHED not in out)
    rc, out, asked = go(["--mode", "update", "--settings", str(settings)], home, repo, interactive=True, replies=["y"])
    check("answered no, update (interactive): not asked again, still off",
          rc == 0 and not registered(settings, repo) and asked == [] and SWITCHED not in out)

tmp, home, repo, settings = case("no-record")
with tmp:
    # The durable record alone (the wizard's state file is gone after a complete run).
    (home / W.RECORD_NAME).write_text(json.dumps({"agent_org_enable": "n"}), encoding="utf-8")
    for mode in ("install", "update"):
        rc, out, _ = go(["--mode", mode, "--non-interactive", "--settings", str(settings)], home, repo)
        check(f"recorded no (durable record only), {mode}: stays off, exit 0, not announced",
              rc == 0 and not registered(settings, repo) and "answered no" in out and SWITCHED not in out)

# ---------- 6. no recorded answer: on by default ----------
for mode in ("install", "update"):
    tmp, home, repo, settings = case(f"unknown-{mode}")
    with tmp:
        rc, out, asked = go(["--mode", mode, "--non-interactive", "--settings", str(settings)], home, repo)
        rec = json.loads((home / W.RECORD_NAME).read_text(encoding="utf-8")) if (home / W.RECORD_NAME).is_file() else {}
        check(f"no answer + no terminal ({mode}): switched on, read back, exit 0, nothing asked",
              rc == 0 and registered(settings, repo) and asked == [] and "Agent Org: OK" in out)
        check(f"no answer + no terminal ({mode}): announced loudly with the off switch and the restart line",
              SWITCHED in out and DISABLE in out and RESTART in out and "on by default" in out and "=" * 40 in out)
        check(f"no answer + no terminal ({mode}): recorded as a default yes, so the choice is visible",
              rec.get("agent_org_enable") == "y" and rec.get("source") == "default"
              and W.recorded_answer(home)[0] == "yes")

tmp, home, repo, settings = case("unknown-interactive")
with tmp:
    rc, out, asked = go(["--mode", "update", "--settings", str(settings)], home, repo, interactive=True, replies=["y"])
    check("no answer, interactive yes: asked, wired, answer recorded, announced",
          rc == 0 and registered(settings, repo) and len(asked) == 1
          and W.recorded_answer(home)[0] == "yes" and SWITCHED in out and RESTART in out)

tmp, home, repo, settings = case("unknown-enter")
with tmp:
    rc, out, asked = go(["--mode", "install", "--settings", str(settings)], home, repo, interactive=True, replies=[""])
    check("no answer, interactive Enter: default is yes, switched on and announced",
          rc == 0 and registered(settings, repo) and len(asked) == 1 and "[Y/n]" in asked[0]
          and W.recorded_answer(home)[0] == "yes" and SWITCHED in out and DISABLE in out and RESTART in out)

tmp, home, repo, settings = case("unknown-n")
with tmp:
    rc, out, asked = go(["--mode", "install", "--settings", str(settings)], home, repo, interactive=True, replies=["n"])
    check("no answer, interactive 'n': left off and the no is recorded",
          rc == 0 and not registered(settings, repo) and W.recorded_answer(home)[0] == "no" and SWITCHED not in out)
    rc, out, asked = go(["--mode", "update", "--non-interactive", "--settings", str(settings)], home, repo)
    check("no answer, interactive 'n': a later update leaves it off",
          rc == 0 and not registered(settings, repo) and SWITCHED not in out)

tmp, home, repo, settings = case("unknown-check")
with tmp:
    rc, out, _ = go(["--mode", "update", "--check", "--settings", str(settings)], home, repo)
    check("no answer, --check: exit 1, says on by default, writes nothing",
          rc == 1 and "on by default" in out and not settings.exists() and not (home / W.RECORD_NAME).exists())
    rc, out, _ = go(["--mode", "install", "--dry-run", "--settings", str(settings)], home, repo)
    check("no answer, --dry-run: says a real run would switch it on, writes and records nothing",
          rc == 1 and "would switch it on" in out and not settings.exists()
          and not (home / W.RECORD_NAME).exists() and SWITCHED not in out)

# ---------- 6b. agent_org_setup.py --disable sticks through later updates ----------


def aos_main(argv: list[str], home: Path, settings: Path) -> tuple[int, str]:
    import contextlib
    import io
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = aos.main(argv, home=home, settings=settings, version=GOOD)
    return rc, buf.getvalue()


tmp, home, repo, settings = case("disable")
with tmp:
    # A state file holding "y" is what `first-run.py --catch-up` leaves behind, and it
    # is read BEFORE the durable record: the hardest case for the off switch.
    answer(home, "y")
    real_plugin_dir = aos.plugin_dir
    aos.plugin_dir = lambda r=repo: (repo / "plugins" / "agent-org-reporter").resolve()  # type: ignore[assignment]
    try:
        go(["--mode", "install", "--non-interactive", "--settings", str(settings)], home, repo)
        check("disable: precondition, Agent Org is on", registered(settings, repo))
        rc, out = aos_main(["--disable"], home, settings)
        state = json.loads((home / W.STATE_NAME).read_text(encoding="utf-8"))
        rec = json.loads((home / W.RECORD_NAME).read_text(encoding="utf-8"))
        check("disable: removed from settings, exit 0", rc == 0 and not registered(settings, repo))
        check("disable: records the no in the durable record AND the state file that held yes",
              rec.get("agent_org_enable") == "n" and state.get("agent_org_enable") == "n"
              and "Recorded" in out and "stays off" in out)
        for mode, inter in (("update", False), ("update", True), ("install", False)):
            rc, out, asked = go(["--mode", mode, "--settings", str(settings)] + ([] if inter else ["--non-interactive"]),
                                home, repo, interactive=inter, replies=["y", "y"])
            check(f"disable then a later {mode} ({'interactive' if inter else 'no terminal'}): stays off",
                  rc == 0 and not registered(settings, repo) and "answered no" in out and SWITCHED not in out
                  and not any("Agent Org" in a for a in asked))
        rc, out = aos_main(["--disable"], home, settings)
        check("disable twice: exit 0, says the no was already recorded", rc == 0 and "already recorded" in out)
        rc, out = aos_main([], home, settings)
        check("manual enable after disable: on, and the record says yes again",
              rc == 0 and registered(settings, repo) and W.recorded_answer(home)[0] == "yes")
    finally:
        aos.plugin_dir = real_plugin_dir  # type: ignore[assignment]

tmp, home, repo, settings = case("disable-no-state")
with tmp:
    rc, out = aos_main(["--disable"], home, settings)
    check("disable with no state file: records no, never creates the state file",
          rc == 0 and W.recorded_answer(home)[0] == "no" and not (home / W.STATE_NAME).exists())

# ---------- 7. dry run, broken settings, missing launcher ----------
tmp, home, repo, settings = case("dry")
with tmp:
    answer(home, "y")
    rc, out, _ = go(["--mode", "install", "--dry-run", "--settings", str(settings)], home, repo)
    check("dry run: exit 1, nothing written", rc == 1 and not settings.exists() and "Would add" in out)
    settings.write_text("{broken", encoding="utf-8")
    rc, out, _ = go(["--mode", "install", "--non-interactive", "--settings", str(settings)], home, repo)
    check("unparseable settings: exit 1, file untouched",
          rc == 1 and settings.read_text(encoding="utf-8") == "{broken" and "repair the JSON" in out)

tmp = tempfile.TemporaryDirectory()
with tmp:
    root = Path(tmp.name)
    home = root / "home"
    (home / ".claude").mkdir(parents=True)
    repo = make_repo(root, launcher=False)
    settings = home / ".claude" / "settings.json"
    answer(home, "y")
    rc, out, _ = go(["--mode", "install", "--non-interactive", "--settings", str(settings)], home, repo)
    data = json.loads(settings.read_text(encoding="utf-8"))
    check("launcher missing: status line not written, exit 1, says so",
          rc == 1 and "statusLine" not in data and "scripts/hook is missing" in out)

check("unsafe repo path refused for the command",
      W.desired_statusline(Path("/tmp/we$ird")) is None and W.desired_statusline(Path('/tmp/a"b')) is None)

# ---------- 8. the real entry point ----------
tmp = tempfile.TemporaryDirectory()
with tmp:
    root = Path(tmp.name)
    env = dict(os.environ, HOME=str(root), USERPROFILE=str(root))
    p = subprocess.run([sys.executable, str(WIRING), "--help"], capture_output=True, text=True, env=env, timeout=60)
    check("CLI --help: exit 0, names the contract flags",
          p.returncode == 0 and all(f in p.stdout for f in ("--mode", "--check", "--non-interactive", "--dry-run", "--settings")))
    s = root / "settings.json"
    p = subprocess.run([sys.executable, str(WIRING), "--mode", "update", "--check", "--settings", str(s)],
                       capture_output=True, text=True, env=env, timeout=60)
    check("CLI --check on empty settings: exit 1, prints a fix, writes nothing",
          p.returncode == 1 and "Fix (" in p.stdout and not s.exists())

# The off switch through the real command lines, with a temporary HOME: the default
# settings file and the answer record both resolve under it, never the real ones.
tmp = tempfile.TemporaryDirectory()
with tmp:
    root = Path(tmp.name).resolve()
    env = dict(os.environ, HOME=str(root), USERPROFILE=str(root), PYTHONIOENCODING="utf-8")
    (root / ".claude").mkdir()
    s = root / ".claude" / "settings.json"
    real_pdir = str((HERE.parent / "plugins" / "agent-org-reporter").resolve())
    s.write_text(json.dumps({"env": {"CLAUDE_CODE_PLUGIN_DIRS": real_pdir}}), encoding="utf-8")
    (root / W.STATE_NAME).write_text(json.dumps({"agent_org_enable": "y"}), encoding="utf-8")
    p = subprocess.run([sys.executable, str(HERE / "agent_org_setup.py"), "--disable"],
                       capture_output=True, text=True, env=env, timeout=60)
    after = json.loads(s.read_text(encoding="utf-8"))
    check("CLI agent_org_setup.py --disable: exit 0, removed, no recorded in the temp home",
          p.returncode == 0 and "CLAUDE_CODE_PLUGIN_DIRS" not in after.get("env", {})
          and json.loads((root / W.RECORD_NAME).read_text(encoding="utf-8")).get("agent_org_enable") == "n"
          and json.loads((root / W.STATE_NAME).read_text(encoding="utf-8")).get("agent_org_enable") == "n")
    p = subprocess.run([sys.executable, str(WIRING), "--mode", "update", "--non-interactive"],
                       capture_output=True, text=True, env=env, timeout=60)
    after = json.loads(s.read_text(encoding="utf-8"))
    check("CLI: a later update after --disable leaves Agent Org off and says why",
          "CLAUDE_CODE_PLUGIN_DIRS" not in after.get("env", {}) and "answered no" in p.stdout
          and SWITCHED not in p.stdout)

# ---------- 9. statusline.py ----------


def sl(stdin: bytes, home: Path, colour: bool = False) -> tuple[int, str, str]:
    env = dict(os.environ, HOME=str(home), USERPROFILE=str(home))
    env.pop("NO_COLOR", None)
    if not colour:
        env["NO_COLOR"] = "1"
    p = subprocess.run([sys.executable, str(STATUSLINE)], input=stdin, capture_output=True,
                       env=env, cwd=str(home), timeout=60)
    return p.returncode, p.stdout.decode("utf-8", "replace"), p.stderr.decode("utf-8", "replace")


tmp = tempfile.TemporaryDirectory()
with tmp:
    home = Path(tmp.name).resolve()
    proj = home / "proj"
    proj.mkdir()
    full = {
        "workspace": {"current_dir": str(proj)},
        "cwd": str(home / "other"),
        "model": {"id": "model-id-x", "display_name": "Model X"},
        "context_window": {"used_percentage": 41.6},
        "rate_limits": {"five_hour": {"used_percentage": 10}, "seven_day": {"used_percentage": 3.2}},
    }
    rc, out, err = sl(json.dumps(full).encode(), home)
    lines = out.split("\n")
    check("statusline full: line 1 is the folder with home as ~", rc == 0 and lines[0] == "~/proj")
    check("statusline full: line 2 has every segment",
          len(lines) == 2 and lines[1] == "Model X | CTX 42% | Session 10% | Total 3%")
    rc, out, err = sl(json.dumps(full).encode(), home, colour=True)
    check("statusline colour: same text once colours are stripped",
          rc == 0 and "\x1b[" in out and ANSI.sub("", out) == "~/proj\nModel X | CTX 42% | Session 10% | Total 3%")

    rc, out, _ = sl(json.dumps({"cwd": str(proj), "model": {"id": "only-id"}}).encode(), home)
    check("statusline missing fields: cwd fallback, model id, missing segments dropped",
          rc == 0 and out == "~/proj\nonly-id")
    rc, out, _ = sl(json.dumps({"workspace": {"current_dir": str(proj)}, "context_window": {"used_percentage": 5}}).encode(), home)
    check("statusline no model: segment dropped, CTX alone", rc == 0 and out == "~/proj\nCTX 5%")
    rc, out, _ = sl(json.dumps({"workspace": {"current_dir": str(proj)}}).encode(), home)
    check("statusline nothing for line 2: folder only", rc == 0 and out == "~/proj")
    bad_types = {"workspace": {"current_dir": 7}, "model": 5, "context_window": {"used_percentage": "41"},
                 "rate_limits": {"five_hour": None, "seven_day": {"used_percentage": True}}}
    rc, out, err = sl(json.dumps(bad_types).encode(), home)
    check("statusline wrong types: exit 0, segments dropped, no traceback",
          rc == 0 and "\n" not in out and out == "~" and "Traceback" not in err)

    for label, payload in (("garbage", b"not json {{"), ("empty", b""), ("non-object", b"[1, 2, 3]"),
                           ("invalid utf-8", b"\xff\xfe\x00{"), ("deep nesting", b"[" * 100000),
                           ("NaN", b'{"context_window": {"used_percentage": NaN}}')):
        rc, out, err = sl(payload, home)
        check(f"statusline {label}: exit 0, prints the folder, no traceback",
              rc == 0 and out.split("\n")[0] == "~" and "Traceback" not in err and "CTX" not in out)

    sneaky = {"workspace": {"current_dir": str(proj)}, "model": {"display_name": "X\x1b]0;owned\x07Y\u009b31m"}}
    rc, out, _ = sl(json.dumps(sneaky).encode(), home)
    check("statusline strips control characters from values", rc == 0 and "\x1b" not in out and "\x07" not in out
          and "\u009b" not in out and out.endswith("X]0;ownedY31m"))
    sibling = home.parent / (home.name + "x")
    rc, out, _ = sl(json.dumps({"cwd": str(sibling)}).encode(), home)
    check("statusline: a sibling folder sharing the home prefix is not shortened", rc == 0 and not out.startswith("~"))

failed = [n for n, passed in results if not passed]
for n, passed in results:
    print(("PASS  " if passed else "FAIL  ") + n)
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
