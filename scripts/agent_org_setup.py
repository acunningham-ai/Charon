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

Run by `first-run.py` (and its `--catch-up`, which `/charon-update` uses) when you
answer yes to `agent_org_enable`, or by hand:

    python scripts/agent_org_setup.py            # enable
    python scripts/agent_org_setup.py --check    # say what it would do, write nothing
    python scripts/agent_org_setup.py --disable  # remove this repo's folder from the list

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


def enable(dry_run: bool = False, repo: Path = REPO, version: tuple[int, int, int] | None = None) -> tuple[bool, str]:
    """(changed-or-already-on, message). Never raises for an expected problem."""
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
    path = settings_path()
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


def disable(dry_run: bool = False, repo: Path = REPO) -> tuple[bool, str]:
    pdir = plugin_dir(repo)
    path = settings_path()
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


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="Turn Agent Org on or off for this machine.")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="say what would change; write nothing")
    g.add_argument("--disable", action="store_true", help="remove this repo's plugin folder")
    a = ap.parse_args(argv)
    ok, msg = (disable(dry_run=False) if a.disable else enable(dry_run=a.check))
    print(msg)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
