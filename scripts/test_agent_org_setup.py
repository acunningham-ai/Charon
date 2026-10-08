#!/usr/bin/env python3
"""Tests for agent_org_setup.py, against a temporary settings file (never the real one).

    python scripts/test_agent_org_setup.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import agent_org_setup as S  # noqa: E402

GOOD = (2, 1, 292)
results: list[tuple[str, bool]] = []


def check(name: str, cond: bool) -> None:
    results.append((name, bool(cond)))


with tempfile.TemporaryDirectory() as tmp:
    settings = Path(tmp) / ".claude" / "settings.json"
    S.settings_path = lambda: settings  # type: ignore[assignment]
    pdir = str(S.plugin_dir())
    other = str(Path(tmp) / "some-other-plugin")

    ok, msg = S.enable(version=(2, 1, 286))
    check("older Claude Code: refused, nothing written", not ok and "2.1.287" in msg and not settings.exists())

    settings.parent.mkdir(parents=True)
    settings.write_text("{not json", encoding="utf-8")
    ok, msg = S.enable(version=GOOD)
    check("unparseable settings: refused, file untouched", not ok and settings.read_text(encoding="utf-8") == "{not json")

    settings.write_text(json.dumps({"model": "opus", "env": {"CLAUDE_CODE_PLUGIN_DIRS": other, "KEEP": "1"}}), encoding="utf-8")
    ok, msg = S.enable(dry_run=True, version=GOOD)
    check("--check writes nothing", ok and "Would add" in msg and pdir not in settings.read_text(encoding="utf-8"))

    ok, msg = S.enable(version=GOOD)
    data = json.loads(settings.read_text(encoding="utf-8"))
    dirs = data["env"]["CLAUDE_CODE_PLUGIN_DIRS"].split(os.pathsep)
    check("enable merges: existing folder kept, ours added", ok and dirs == [other, pdir])
    check("enable keeps every other setting", data["model"] == "opus" and data["env"]["KEEP"] == "1")
    check("enable leaves a backup", any(p.name.startswith("settings.json.bak-agent-org-") for p in settings.parent.iterdir()))

    before = settings.read_text(encoding="utf-8")
    ok, msg = S.enable(version=GOOD)
    check("enable twice changes nothing", ok and "already on" in msg and settings.read_text(encoding="utf-8") == before)

    ok, msg = S.disable()
    data = json.loads(settings.read_text(encoding="utf-8"))
    check("disable removes only ours", ok and data["env"]["CLAUDE_CODE_PLUGIN_DIRS"] == other and data["model"] == "opus")

    settings.write_text(json.dumps({"env": {"CLAUDE_CODE_PLUGIN_DIRS": pdir}}), encoding="utf-8")
    S.disable()
    data = json.loads(settings.read_text(encoding="utf-8"))
    check("disable drops the variable when ours was the only folder", "CLAUDE_CODE_PLUGIN_DIRS" not in data["env"])

    settings.unlink()
    ok, msg = S.enable(version=GOOD)
    check("no settings file yet: created with just our variable",
          ok and json.loads(settings.read_text(encoding="utf-8")) == {"env": {"CLAUDE_CODE_PLUGIN_DIRS": pdir}})

failed = [n for n, passed in results if not passed]
for n, passed in results:
    print(("PASS  " if passed else "FAIL  ") + n)
print(f"\n{len(results) - len(failed)}/{len(results)} passed")
sys.exit(1 if failed else 0)
