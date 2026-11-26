#!/usr/bin/env python3
"""Turn Agent Org on (or off) for this machine.

Agent Org is a Claude Code *mod* (a function-hook plugin) that lives in this repo at
`plugins/agent-org-reporter/`. Claude Code loads a plugin folder named in the
`CLAUDE_CODE_PLUGIN_DIRS` variable of the `env` block in your user settings
(`~/.claude/settings.json`): one or more absolute paths separated by the platform's
path-list separator. This script adds this repo's plugin folder to that list.

It is careful with a file it does not own:
  * it needs Claude Code 2.1.287 or later (the version Anthropic documents for mods)
    and changes nothing on an older one;
  * it refuses to touch a settings file it cannot parse;
  * it keeps a timestamped backup beside the file before writing;
  * it MERGES: any folders already listed stay, every other setting stays, and running
    it twice changes nothing the second time.

Agent Org is on by default (decision 2026-11-26):`post_install_wiring.py`, run by
`first-run.py` and by `/charon-update`, switches it on unless a "no" is recorded.
By hand:

    python scripts/agent_org_setup.py            # enable (and record "yes")
    python scripts/agent_org_setup.py --check    # say what it would do, write nothing
    python scripts/agent_org_setup.py --disable  # remove this repo's folder, record "no"

`--disable` records the "no" in ~/.charon-agent-org.json (and in the wizard's state
file, if one holds an answer), so later installs and updates leave Agent Org off.
Run it without --disable to turn it back on.

Restart Claude Code afterwards: the variable is read when a session starts.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

MIN_VERSION = (2, 1, 287)
VAR = "CLAUDE_CODE_PLUGIN_DIRS"
REPO = Path(__file__).resolve().parents[1]
# Where the agent_org_enable answer is kept, both in the user's home folder.
# post_install_wiring.py reads them in this order (state file first); first-run.py
# writes both. Keep the names and the key in step with those two scripts.
ANSWER_KEY = "agent_org_enable"
STATE_NAME = ".charon-first-run-state.json"
RECORD_NAME = ".charon-agent-org.json"


def plugin_dir(repo: Path = REPO) -> Path:
    return (repo / "plugins" / "agent-org-reporter").resolve()


def settings_path() -> Path:
    return Path.home() / ".claude" / "settings.json"


def claude_version() -> tuple[int, int, int] | None:
    exe = shutil.which("claude")
    if not exe:
        return None
    try:
        out = subprocess.run([exe, "--version"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"(\d+)\.(\d+)\.(\d+)", out or "")
    return tuple(int(x) for x in m.groups()) if m else None  # type: ignore[return-value]


def _same(a: str, b: Path) -> bool:
    try:
        return Path(os.path.expanduser(a)).resolve() == b
    except OSError:
        return False


def _load(path: Path) -> tuple[dict | None, str]:
    if not path.exists():
        return {}, ""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return None, f"could not read {path} ({type(exc).__name__}); not touching it"
    if not isinstance(data, dict):
        return None, f"{path} is not a JSON object; not touching it"
    return data, ""


def _write(path: Path, data: dict) -> Path | None:
    backup = None
    if path.exists():
        backup = path.with_name(f"{path.name}.bak-agent-org-{time.strftime('%Y%m%d-%H%M%S')}")
        shutil.copy2(path, backup)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp-agent-org")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return backup


def enable(dry_run: bool = False, repo: Path = REPO, version: tuple[int, int, int] | None = None,
           settings: Path | None = None) -> tuple[bool, str]:
    """(changed-or-already-on, message). Never raises for an expected problem.

    `settings` names the settings file to change; None means the user's own
    (`settings_path()`). post_install_wiring.py passes its --settings value here."""
    pdir = plugin_dir(repo)
    if not (pdir / ".claude-plugin" / "plugin.json").is_file():
        return False, f"Agent Org plugin not found at {pdir}"
    ver = version if version is not None else claude_version()
    if ver is None:
        return False, ("Claude Code was not found on PATH, so the version could not be checked. "
                       "Install or update it, then run: python scripts/agent_org_setup.py")
    if ver < MIN_VERSION:
        have = ".".join(map(str, ver))
        return False, (f"Agent Org needs Claude Code 2.1.287 or later; you have {have}. Run `claude update`, "
                       "then: python scripts/agent_org_setup.py")
    path = settings if settings is not None else settings_path()
    data, err = _load(path)
    if data is None:
        return False, err
    env = data.get("env")
    if env is not None and not isinstance(env, dict):
        return False, f"`env` in {path} is not an object; not touching it"
    env = dict(env or {})
    parts = [p for p in str(env.get(VAR, "")).split(os.pathsep) if p.strip()]
    if any(_same(p, pdir) for p in parts):
        return True, f"Agent Org is already on ({VAR} lists {pdir})."
    parts.append(str(pdir))
    if dry_run:
        return True, f"Would add {pdir} to {VAR} in {path}."
    env[VAR] = os.pathsep.join(parts)
    data["env"] = env
    backup = _write(path, data)
    note = f" Backup: {backup}." if backup else ""
    return True, f"Agent Org is on: added {pdir} to {VAR} in {path}.{note} Restart Claude Code to load it."


def disable(dry_run: bool = False, repo: Path = REPO, settings: Path | None = None) -> tuple[bool, str]:
    pdir = plugin_dir(repo)
    path = settings if settings is not None else settings_path()
    data, err = _load(path)
    if data is None:
        return False, err
    env = data.get("env") if isinstance(data.get("env"), dict) else {}
    parts = [p for p in str(env.get(VAR, "")).split(os.pathsep) if p.strip()]
    keep = [p for p in parts if not _same(p, pdir)]
    if len(keep) == len(parts):
        return True, "Agent Org was not on; nothing to change."
    if dry_run:
        return True, f"Would remove {pdir} from {VAR} in {path}."
    env = dict(env)
    if keep:
        env[VAR] = os.pathsep.join(keep)
    else:
        env.pop(VAR, None)
    data["env"] = env
    backup = _write(path, data)
    return True, f"Agent Org is off: removed {pdir} from {VAR}. Backup: {backup}. Restart Claude Code."


def _answer_in(path: Path) -> tuple[dict | None, str | None]:
    """(the file's JSON object or None, its normalised answer 'y' / 'n' / None)."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None, None
    if not isinstance(data, dict):
        return None, None
    raw = str(data.get(ANSWER_KEY) or "").strip().lower()
    return data, ("y" if raw in ("y", "yes") else "n" if raw in ("n", "no") else None)


def _replace_json(path: Path, data: dict) -> None:
    tmp = path.with_name(path.name + ".tmp-agent-org")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def record_answer(value: str, home: Path | None = None) -> tuple[bool, str]:
    """Record the user's Agent Org choice ('y' or 'n') where installs and updates read it.

    Writes ~/.charon-agent-org.json, and changes the answer in the wizard's state file
    only if that file already holds a different one (it is read FIRST, so a stale "y"
    there would otherwise win over the "n" just recorded). Never creates the state
    file. Nothing is rewritten when the answer is already recorded."""
    if value not in ("y", "n"):
        raise ValueError("value must be 'y' or 'n'")
    home = home if home is not None else Path.home()
    word = "yes" if value == "y" else "no"
    record = home / RECORD_NAME
    notes: list[str] = []
    ok = True
    _, current = _answer_in(record)
    if current == value:
        notes.append(f'"{word}" was already recorded in {record}.')
    else:
        try:
            _replace_json(record, {ANSWER_KEY: value, "source": "answer",
                                   "recorded": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                   "recorded_by": "agent_org_setup.py"})
            notes.append(f'Recorded "{word}" in {record}.')
        except OSError as exc:
            ok = False
            notes.append(f'Could not record "{word}" in {record} ({type(exc).__name__}).')
    state = home / STATE_NAME
    data, current = _answer_in(state)
    if data is not None and current is not None and current != value:
        data[ANSWER_KEY] = value
        try:
            _replace_json(state, data)
            notes.append(f'Changed the saved setup answer in {state} to "{word}".')
        except OSError as exc:
            ok = False
            notes.append(f"Could not change the saved setup answer in {state} ({type(exc).__name__}); "
                         "it still holds the old answer.")
    return ok, " ".join(notes)


def main(argv: list[str] | None = None, *, home: Path | None = None,
         settings: Path | None = None, version: tuple[int, int, int] | None = None) -> int:
    """`home`, `settings` and `version` exist for tests; the command line always uses
    the real home, the real settings file and the installed Claude Code version."""
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Turn Agent Org on or off for this machine.")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="say what would change; write nothing")
    g.add_argument("--disable", action="store_true",
                   help="remove this repo's plugin folder and record 'no', so updates leave it off")
    a = ap.parse_args(argv)
    if a.disable:
        ok, msg = disable(dry_run=False, settings=settings)
        print(msg)
        rec_ok, rec_msg = record_answer("n", home=home)
        print(rec_msg)
        if rec_ok:
            print("Agent Org stays off through later installs and updates. "
                  "To turn it back on: python scripts/agent_org_setup.py")
        else:
            print("WARNING: the 'no' could not be fully recorded, so a later install or update "
                  "may switch Agent Org back on. Fix the file named above, then run this again.")
        return 0 if ok and rec_ok else 1
    ok, msg = enable(dry_run=a.check, settings=settings, version=version)
    print(msg)
    if ok and not a.check:
        rec_ok, rec_msg = record_answer("y", home=home)
        print(rec_msg)
        if not rec_ok:
            return 1
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
