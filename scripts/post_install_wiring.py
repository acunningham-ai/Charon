#!/usr/bin/env python3
"""Wire Charon into Claude Code after an install or an update: the Agent Org pane and
the status line.

    python scripts/post_install_wiring.py --mode install|update
                                          [--check] [--non-interactive] [--dry-run]
                                          [--settings PATH]

`first-run.py` runs it with `--mode install`; `/charon-update` runs it with
`--mode update`; `/harness-doctor` runs it with `--check`.

What it does, in your Claude Code user settings (default `~/.claude/settings.json`):

1. **Agent Org. On by default** (decision 2026-11-26; this reverses the 2026-11-25
   "explicit yes only" rule). Unless a "no" is recorded it switches the mod on
   through `agent_org_setup.py` (merged, backed up, idempotent), tries once more if
   that fails, then reads the settings back to prove the plugin folder really is
   listed. With no recorded answer, an interactive run asks ([Y/n], Enter = yes)
   and a run without a terminal switches it on and records a default "yes" in
   ~/.charon-agent-org.json so the choice is visible. A recorded "no" is respected
   and never overridden. Every run that switches it on prints a loud block saying
   so, how to turn it off (`agent_org_setup.py --disable`, which also records the
   "no"), and that Claude Code must be restarted to show the pane. Where the answer
   is read from: see `recorded_answer()`.
2. **Status line.** Points `statusLine` at `scripts/statusline.py` through the
   `scripts/hook` launcher:  sh "<repo>/scripts/hook" scripts/statusline.py
   The same `sh` form is used on every platform (Claude Code runs commands through
   a POSIX shell, Git Bash on Windows). If you already have a DIFFERENT status
   line it is never replaced without asking: interactive runs ask, and
   non-interactive runs leave it alone and say so.

Every write keeps a timestamped backup beside the settings file.

`--check` writes nothing and reports both. `--dry-run` writes nothing and reports
what a real run would change.

Exit 0: everything is wired. Exit 1: something is not wired; the output names it
and prints the exact command that fixes it. It never exits quietly.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agent_org_setup as aos  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
LAUNCHER = "scripts/hook"
STATUSLINE_SCRIPT = "scripts/statusline.py"
ANSWER_KEY = aos.ANSWER_KEY
# Where the agent_org_enable answer lands, read in this order:
#   1. the wizard's state file: answers sit here while first-run runs, and stay
#      after `first-run.py --catch-up` (the /charon-update path);
#   2. a durable record written once the answer is known, which survives the
#      wizard clearing its state file at the end of a complete run.
# `agent_org_setup.py --disable` writes "no" to the record AND to the state file
# when that holds a different answer, so the off switch survives this order.
STATE_NAME = aos.STATE_NAME
RECORD_NAME = aos.RECORD_NAME
# Characters that would change the meaning of the status line command inside its
# double quotes (or end them). A repo path holding one is refused, not escaped.
_UNSAFE_IN_COMMAND = set('"$`\\')


@dataclass
class Item:
    name: str
    ok: bool
    detail: str
    fix: str = ""
    changed: bool = False
    announce: tuple[str, ...] = ()  # printed as a loud block after the summary lines


@dataclass
class Ctx:
    mode: str
    check: bool
    dry_run: bool
    interactive: bool
    settings: Path
    default_settings: bool
    home: Path
    repo: Path
    version: tuple[int, int, int] | None = None
    ask: Callable[[str], str] = input


# ---------- helpers ----------

def _fix_command(ctx: Ctx) -> str:
    """The command that repairs the wiring, run from the Charon folder."""
    py = "python" if os.name == "nt" else "python3"
    cmd = f"{py} scripts/post_install_wiring.py --mode update"
    if not ctx.default_settings:
        cmd += f' --settings "{ctx.settings}"'
    return f"from {ctx.repo}, run: {cmd}"


def _write_settings(path: Path, data: dict) -> Path | None:
    """Back up, then replace atomically. Returns the backup path (None if no file yet)."""
    backup = None
    if path.exists():
        stamp = time.strftime("%Y%m%d-%H%M%S")
        backup = path.with_name(f"{path.name}.bak-charon-wiring-{stamp}")
        n = 1
        while backup.exists():
            n += 1
            backup = path.with_name(f"{path.name}.bak-charon-wiring-{stamp}-{n}")
        shutil.copy2(path, backup)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp-charon-wiring")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return backup


def recorded_answer(home: Path) -> tuple[str | None, str]:
    """('yes' | 'no' | None, where it was found)."""
    for name in (STATE_NAME, RECORD_NAME):
        p = home / name
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        value = str(data.get(ANSWER_KEY) or "").strip().lower()
        if value in ("y", "yes"):
            return "yes", str(p)
        if value in ("n", "no"):
            return "no", str(p)
    return None, ""


def _record_answer(home: Path, answer: str, source: str = "answer") -> None:
    """source: 'answer' (the person said it) or 'default' (no answer; on by default)."""
    try:
        (home / RECORD_NAME).write_text(
            json.dumps({ANSWER_KEY: "y" if answer == "yes" else "n", "source": source,
                        "recorded": time.strftime("%Y-%m-%dT%H:%M:%S"),
                        "recorded_by": "post_install_wiring.py"}, indent=2) + "\n",
            encoding="utf-8")
    except OSError:
        pass  # the settings change itself is the record that matters


def _python_cmd() -> str:
    return "python" if os.name == "nt" else "python3"


def switched_on_notice(why: str) -> tuple[str, ...]:
    """The loud lines every run that switches Agent Org on must print."""
    py = _python_cmd()
    return (
        "AGENT ORG WAS SWITCHED ON.",
        f"Why: {why}.",
        "RESTART CLAUDE CODE to show the Agent Org pane (it is read when a session starts).",
        f"To turn it off: {py} scripts/agent_org_setup.py --disable",
        "  (run from the Charon folder; that also records a \"no\", so later updates leave it off)",
    )


def agent_org_registered(settings: Path, repo: Path) -> tuple[bool | None, str]:
    """(True / False, '') or (None, why the settings could not be read)."""
    data, err = aos._load(settings)
    if data is None:
        return None, err
    env = data.get("env")
    if not isinstance(env, dict):
        return False, ""
    pdir = aos.plugin_dir(repo)
    parts = [p for p in str(env.get(aos.VAR, "")).split(os.pathsep) if p.strip()]
    return any(aos._same(p, pdir) for p in parts), ""


def desired_statusline(repo: Path) -> str | None:
    root = repo.resolve().as_posix()
    if any(c in _UNSAFE_IN_COMMAND or ord(c) < 0x20 or ord(c) == 0x7F for c in root):
        return None
    return f'sh "{root}/{LAUNCHER}" {STATUSLINE_SCRIPT}'


def _describe(value) -> str:
    if isinstance(value, dict) and isinstance(value.get("command"), str):
        text = value["command"]
    else:
        text = json.dumps(value, ensure_ascii=True)
    text = "".join(ch for ch in text if ord(ch) >= 0x20 and not 0x7F <= ord(ch) < 0xA0)
    return text if len(text) <= 120 else text[:117] + "..."


def _yes(reply: str, default: bool) -> bool:
    reply = (reply or "").strip().lower()
    if not reply:
        return default
    return reply in ("y", "yes")


def _ask(ctx: Ctx, prompt: str, default: bool) -> bool:
    try:
        return _yes(ctx.ask(prompt), default)
    except (EOFError, KeyboardInterrupt):
        return False


# ---------- Agent Org ----------

def wire_agent_org(ctx: Ctx) -> Item:
    name = "Agent Org"
    pdir = aos.plugin_dir(ctx.repo)
    if not (pdir / ".claude-plugin" / "plugin.json").is_file():
        return Item(name, False, f"the plugin is missing from this install ({pdir}).",
                    "run /charon-update to restore it, then " + _fix_command(ctx))
    reg, err = agent_org_registered(ctx.settings, ctx.repo)
    if reg is None:
        return Item(name, False, err, f"repair the JSON in {ctx.settings}, then " + _fix_command(ctx))
    answer, source = recorded_answer(ctx.home)
    if reg:
        return Item(name, True, f"on ({aos.VAR} lists {pdir}).")
    if answer == "no":
        return Item(name, True, f"off, because you answered no ({source}). "
                                "To turn it on: python scripts/agent_org_setup.py")

    if ctx.check:
        if answer == "yes":
            return Item(name, False, f"answered yes but not registered: {aos.VAR} in {ctx.settings} "
                                     f"does not list {pdir} (answer read from {source}).",
                        _fix_command(ctx))
        return Item(name, False, f"not registered in {ctx.settings}, and no answer is recorded "
                                 f"(looked in ~/{STATE_NAME} and ~/{RECORD_NAME}). Agent Org is on by "
                                 "default, so the next install or update switches it on.",
                    _fix_command(ctx))

    # On by default (decision 2026-11-26):no recorded answer means switch it on.
    if answer is None:
        if ctx.dry_run:
            return Item(name, False, "not registered and no answer recorded; a real run would switch it "
                                     "on (on by default) and record a default yes. Would add "
                                     f"{pdir} to {aos.VAR}.", "run again without --dry-run")
        if ctx.interactive:
            if not _ask(ctx, "Turn on Agent Org (the live agent pane beside the conversation)? [Y/n]: ", True):
                _record_answer(ctx.home, "no")
                return Item(name, True, "left off: you answered no. To turn it on later: "
                                        "python scripts/agent_org_setup.py")
            _record_answer(ctx.home, "yes")
            why = "you answered yes"
        else:
            _record_answer(ctx.home, "yes", source="default")
            why = (f"no answer was recorded, so it is on by default "
                   f"(recorded as a default yes in {ctx.home / RECORD_NAME})")
    else:
        why = f"your recorded answer is yes ({source})"

    ok, msg = False, ""
    for _attempt in range(2):  # one retry
        ok, msg = aos.enable(dry_run=ctx.dry_run, repo=ctx.repo, version=ctx.version, settings=ctx.settings)
        if ok:
            break
    if not ok:
        return Item(name, False, f"could not be switched on (tried twice): {msg}", _fix_command(ctx))
    if ctx.dry_run:
        return Item(name, False, f"dry run: {msg}", "run again without --dry-run")
    reg, err = agent_org_registered(ctx.settings, ctx.repo)
    if not reg:
        return Item(name, False, "enable reported success, but reading the settings back does not show "
                                 f"{pdir} in {aos.VAR}. {err}".strip(), _fix_command(ctx))
    return Item(name, True, msg, changed=True, announce=switched_on_notice(why))


# ---------- status line ----------

def wire_statusline(ctx: Ctx) -> Item:
    name = "Status line"
    cmd = desired_statusline(ctx.repo)
    if cmd is None:
        return Item(name, False, f"the Charon folder path ({ctx.repo}) holds a character that is unsafe "
                                 'in a shell command (" $ ` or \\), so it was not wired.',
                    "move Charon to a plain folder path, then " + _fix_command(ctx))
    for rel in (STATUSLINE_SCRIPT, LAUNCHER):
        if not (ctx.repo / rel).is_file():
            return Item(name, False, f"{rel} is missing from this install.",
                        "run /charon-update to restore it, then " + _fix_command(ctx))
    data, err = aos._load(ctx.settings)
    if data is None:
        return Item(name, False, err, f"repair the JSON in {ctx.settings}, then " + _fix_command(ctx))
    current = data.get("statusLine")
    if isinstance(current, dict) and current.get("command") == cmd:
        return Item(name, True, "points at Charon's status line.")

    if current is not None:
        found = _describe(current)
        if ctx.check:
            return Item(name, False, f"you have a different status line ({found}); Charon's is not wired. "
                                     "That is fine if you chose your own.", _fix_command(ctx) + " (it asks first)")
        if ctx.dry_run:
            return Item(name, False, f"you have a different status line ({found}); a real run would ask "
                                     "before replacing it.", _fix_command(ctx))
        if not ctx.interactive:
            return Item(name, False, f"left your own status line in place ({found}); it is never replaced "
                                     "without asking.", _fix_command(ctx) + " (it asks first)")
        if not _ask(ctx, f"You already have a status line ({found}). Replace it with Charon's? [y/N]: ", False):
            return Item(name, True, f"kept your own status line ({found}), as you chose.")
    elif ctx.check:
        return Item(name, False, f"not set in {ctx.settings}.", _fix_command(ctx))
    elif ctx.dry_run:
        return Item(name, False, f"dry run: would set statusLine to: {cmd}", "run again without --dry-run")

    new = dict(data)
    new["statusLine"] = {"type": "command", "command": cmd}
    try:
        backup = _write_settings(ctx.settings, new)
    except OSError as exc:
        return Item(name, False, f"could not write {ctx.settings} ({type(exc).__name__}).", _fix_command(ctx))
    back, _ = aos._load(ctx.settings)
    if not (isinstance(back, dict) and isinstance(back.get("statusLine"), dict)
            and back["statusLine"].get("command") == cmd):
        return Item(name, False, "wrote the setting, but reading it back does not show it.", _fix_command(ctx))
    note = f" Backup: {backup}." if backup else ""
    return Item(name, True, f"set to: {cmd}.{note} Restart Claude Code to see it.", changed=True)


# ---------- entry point ----------

def run(argv: list[str] | None = None, *, home: Path | None = None, repo: Path = REPO,
        version: tuple[int, int, int] | None = None, ask: Callable[[str], str] | None = None,
        interactive: bool | None = None, out: Callable[[str], None] = print) -> int:
    ap = argparse.ArgumentParser(
        description="Wire the Agent Org pane and the Charon status line into Claude Code. "
                    "Exit 0 = everything wired; exit 1 = something is not, with the fix command printed.")
    ap.add_argument("--mode", choices=("install", "update"), required=True,
                    help="install: run by first-run.py; update: run by /charon-update")
    ap.add_argument("--check", action="store_true", help="read-only: report both, write nothing")
    ap.add_argument("--non-interactive", action="store_true",
                    help="never ask: Agent Org with no recorded answer is switched on (on by default) "
                         "and announced; a different status line is left alone and reported")
    ap.add_argument("--dry-run", action="store_true", help="say what would change; write nothing")
    ap.add_argument("--settings", type=Path, default=None,
                    help="Claude Code settings file to wire (default: ~/.claude/settings.json)")
    a = ap.parse_args(argv)

    home = home if home is not None else Path.home()
    default = home / ".claude" / "settings.json"
    settings = a.settings if a.settings is not None else default
    if interactive is None:
        try:
            interactive = sys.stdin.isatty()
        except (AttributeError, ValueError):
            interactive = False
    ctx = Ctx(mode=a.mode, check=a.check, dry_run=a.dry_run,
              interactive=bool(interactive) and not a.non_interactive and not a.check and not a.dry_run,
              settings=settings, default_settings=a.settings is None, home=home, repo=repo,
              version=version, ask=ask or input)

    label = "check" if a.check else ("dry run" if a.dry_run else a.mode)
    out(f"Charon wiring ({label}) for {settings}")
    items = [wire_agent_org(ctx), wire_statusline(ctx)]
    for it in items:
        mark = "OK" if it.ok else "NOT WIRED"
        out(f"  {it.name}: {mark} - {it.detail}")
    for it in items:
        if it.announce:
            bar = "=" * 70
            out(bar)
            for line in it.announce:
                out(f"  {line}")
            out(bar)
    failed = [it for it in items if not it.ok]
    if failed:
        for it in failed:
            out(f"  Fix ({it.name}): {it.fix}")
        out("Not everything is wired (exit 1).")
        return 1
    out("Everything is wired." + (" Restart Claude Code to load the changes." if any(i.changed for i in items) else ""))
    return 0


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    return run(argv)


if __name__ == "__main__":
    sys.exit(main())
