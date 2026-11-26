"""The guard launch path must be protected by the policy engine.

WHY. Every hook and MCP guard in .claude/settings.json is started through
scripts/hook (or scripts/hook.cmd on Windows), the guards themselves live in
scripts/hooks/, and .mcp.json decides which MCP servers start. Until v0.38.0
scripts/policy/policy.json protected only CLAUDE.md and .claude/settings*.json,
so a single Write making the launcher `exit 0` silently disabled every guard,
and no rule fired. This test drives the REAL engine (scripts/hooks/_policy.py,
the one deny-destructive.py calls) against a policy file and asserts:

  1. Write / Edit (and MultiEdit / NotebookEdit, which settings.json also routes
     to deny-destructive.py) on scripts/hook, scripts/hook.cmd, .mcp.json and
     scripts/hooks/deny-destructive.py get the protected verdict: `ask`, from
     protected-config-write, with enforce on.
  2. The shell forms (redirect, cp / mv / tee, sed -i, Set-Content / Out-File /
     Add-Content, Copy-Item) get the same, from protected-config-write-via-shell.
  3. Negatives stay quiet: scripts/other.py, notes/x.md, look-alike names, and
     commands that only READ or RUN a hook.
  4. Existing verdicts are unchanged: CLAUDE.md and settings.json still `ask`,
     TODO.md and MEMORY.md still excluded by role, plus every case in the
     engine's own _SELFTEST_CASES.
  5. When the file under test is not scripts/policy/policy.json itself, every
     other rule is byte-for-byte the same as the live one, and the two changed
     rules only widened (same verdict, enforce, severity, exclusions).

The engine is imported, not reimplemented. Pure and offline: no files are
written, no hook is executed, nothing is logged (evaluate() never emits).

Run:  python scripts/test_policy_protects_launcher.py [policy-file]
      default policy-file: scripts/policy/policy.json (relative paths resolve
      against the repo root).
Exit: 0 = all pass, 1 = a case failed, 2 = the policy file could not be loaded.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(HERE / "hooks"))

import _policy  # noqa: E402  the engine the hooks use

LIVE_POLICY = REPO / "scripts" / "policy" / "policy.json"

PROTECTED_PATHS = [
    "scripts/hook",
    "scripts/hook.cmd",
    ".mcp.json",
    "scripts/hooks/deny-destructive.py",
    # absolute and backslashed forms, as Claude Code passes them on Windows
    "D:\\work\\charon\\scripts\\hook.cmd",
    "/home/user/charon/scripts/hooks/_policy.py",
    "/home/user/charon/.mcp.json",
]
REQUIRED_TOOLS = ["Write", "Edit"]
EXTRA_TOOLS = ["MultiEdit", "NotebookEdit"]

NEGATIVE_WRITES = [
    "scripts/other.py",
    "notes/x.md",
    "scripts/hook-notes.md",
    "scripts/hooksmith.py",
    "scripts/hooks.md",
    "docs/mcp.json.md",
]

PROTECTED_COMMANDS = [
    "echo 'exit 0' > scripts/hook",
    "echo exit /b 0 >> scripts/hook.cmd",
    "printf '{}' > .mcp.json",
    "echo pass > scripts/hooks/deny-destructive.py",
    "cp /tmp/evil scripts/hook",
    "mv evil.cmd scripts/hook.cmd",
    "echo '{}' | tee .mcp.json",
    "cp x.py scripts/hooks/deny-destructive.py",
    "sed -i 's/return 2/return 0/' scripts/hooks/deny-destructive.py",
    "sed -i 's/x/y/' scripts/hook",
    "Set-Content -Path scripts\\hook.cmd -Value 'exit /b 0'",
    "'{}' | Out-File -FilePath .mcp.json",
    "Add-Content scripts/hooks/_policy.py 'x'",
    "Copy-Item evil.py scripts\\hooks\\deny-destructive.py",
    "Move-Item evil scripts/hook",
]

NEGATIVE_COMMANDS = [
    "python scripts/hooks/_policy.py --selftest",
    "cat scripts/hook.cmd",
    "grep -n exit scripts/hook > out.txt",
    "echo x > scripts/other.py",
    "echo x > scripts/hook-notes.txt",
    "cp a.json foo.mcp.json.bak",
    "python scripts/test_policy_protects_launcher.py policy.proposed.json",
    "git diff --stat",
]

SHELL_RULE = "protected-config-write-via-shell"
TOOL_RULE = "protected-config-write"


def _resolve(arg: str) -> Path:
    p = Path(arg)
    return p if p.is_absolute() else (REPO / p)


class Tally:
    def __init__(self):
        self.passed = 0
        self.failed = 0

    def check(self, ok: bool, label: str, detail: str = ""):
        if ok:
            self.passed += 1
            print(f"  [PASS] {label}")
        else:
            self.failed += 1
            print(f"  [FAIL] {label}{('  -> ' + detail) if detail else ''}")


def _protected(decision: dict, rule_id: str) -> bool:
    return (decision["verdict"] == "ask"
            and rule_id in decision["matched"]
            and decision["enforce"] is True)


def _show(decision: dict) -> str:
    return (f"verdict={decision['verdict']} matched={decision['matched']} "
            f"enforce={decision['enforce']}")


def _rule_by_id(pol: dict, rid: str) -> dict:
    for r in pol.get("rules", []):
        if r.get("id") == rid:
            return r
    return {}


def main(argv) -> int:
    target = _resolve(argv[1] if len(argv) > 1 else "scripts/policy/policy.json")
    print(f"policy under test: {target}")
    if not target.is_file():
        print("  [FAIL] policy file not found")
        return 2
    # load_policy() fails OPEN (returns an empty rule set), so a broken file
    # would make every case fall to the default verdict. Refuse that outright.
    pol = _policy.load_policy(target)
    if pol.get("_error"):
        print(f"  [FAIL] policy did not load: {pol['_error']}")
        return 2

    t = Tally()

    def ev(action, profile="interactive"):
        return _policy.evaluate(action, profile, pol)

    print("\n1. Tool writes to the guard launch path are protected")
    for path in PROTECTED_PATHS:
        for tool in REQUIRED_TOOLS + EXTRA_TOOLS:
            d = ev({"tool": tool, "path": path})
            t.check(_protected(d, TOOL_RULE), f"{tool:12} {path}", _show(d))

    print("\n2. Shell writes to the guard launch path are protected")
    for cmd in PROTECTED_COMMANDS:
        d = ev({"tool": "Bash", "command": cmd})
        t.check(_protected(d, SHELL_RULE), f"Bash {cmd}", _show(d))

    print("\n3. Negatives stay quiet")
    for path in NEGATIVE_WRITES:
        for tool in REQUIRED_TOOLS:
            d = ev({"tool": tool, "path": path})
            t.check(d["verdict"] == "allow" and not d["matched"],
                    f"{tool:12} {path} -> allow", _show(d))
    for cmd in NEGATIVE_COMMANDS:
        d = ev({"tool": "Bash", "command": cmd})
        t.check(SHELL_RULE not in d["matched"] and d["verdict"] == "allow",
                f"Bash {cmd} -> allow", _show(d))

    print("\n4. Existing verdicts are unchanged")
    for tool in REQUIRED_TOOLS:
        for path in ("CLAUDE.md", "sub/dir/CLAUDE.md", ".claude/settings.json",
                     ".claude/settings.local.json"):
            d = ev({"tool": tool, "path": path})
            t.check(_protected(d, TOOL_RULE), f"{tool:12} {path} -> ask", _show(d))
        for path in ("TODO.md", "MEMORY.md"):
            d = ev({"tool": tool, "path": path})
            t.check(d["verdict"] == "allow", f"{tool:12} {path} -> allow (role)", _show(d))
    for cmd in ("echo x > CLAUDE.md", "cp a .claude/settings.json"):
        d = ev({"tool": "Bash", "command": cmd})
        t.check(_protected(d, SHELL_RULE), f"Bash {cmd} -> ask", _show(d))
    for action, profile, expected in _policy._SELFTEST_CASES:
        got = ev(action, profile)["verdict"]
        t.check(got == expected, f"engine selftest {profile} {action} -> {expected}",
                f"got {got}")

    if target.resolve() != LIVE_POLICY.resolve():
        print("\n5. Nothing else changed versus scripts/policy/policy.json")
        live = json.loads(LIVE_POLICY.read_text(encoding="utf-8"))
        for key in ("version", "description", "default_verdict", "profiles"):
            t.check(pol.get(key) == live.get(key), f"top-level '{key}' unchanged")
        live_ids = [r.get("id") for r in live["rules"]]
        new_ids = [r.get("id") for r in pol["rules"]]
        t.check(live_ids == new_ids, "same rules, same order", f"{new_ids}")
        for rid in live_ids:
            old, new = _rule_by_id(live, rid), _rule_by_id(pol, rid)
            if rid not in (TOOL_RULE, SHELL_RULE):
                t.check(old == new, f"rule '{rid}' identical")
                continue
            for key in ("applies_to", "verdict", "enforce", "severity"):
                t.check(old.get(key) == new.get(key), f"rule '{rid}' {key} unchanged")
            om, nm = old.get("match", {}), new.get("match", {})
            t.check(set(om.get("tool", [])) <= set(nm.get("tool", [])),
                    f"rule '{rid}' tools only widened")
            t.check(set(om.get("path_globs", [])) <= set(nm.get("path_globs", [])),
                    f"rule '{rid}' path_globs only widened")
            t.check(om.get("exclude_roles") == nm.get("exclude_roles"),
                    f"rule '{rid}' exclude_roles unchanged")
            t.check(len(om.get("command_patterns", [])) == len(nm.get("command_patterns", [])),
                    f"rule '{rid}' same number of command_patterns")

    total = t.passed + t.failed
    print(f"\n{t.passed} passed, {t.failed} failed, {total} total")
    return 0 if t.failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
