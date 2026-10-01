#!/usr/bin/env python3
"""Lint Claude Code permission rules -- read-only, stdlib only.

Why this exists
---------------
Claude Code checks `permissions.allow` rules at startup and prints a warning for
malformed ones -- in yellow, for a second, before the UI repaints over it. Nobody
can read it, so a rule that silently never matches, or one that approves far more
than it looks like it does, just sits there. This makes the same class of problem
a durable audit finding. Called by the audit-claude-setup skill (Step 2b).

Checks (allow list only -- a loose DENY rule over-blocks, which is safe):

  mixed-wildcard-prefix   `*` earlier in the rule AND the trailing `:*` prefix form,
                          e.g. Bash(scp * host:*). The `*` is then literal, so the
                          rule will likely never match. Dead config.
  broad-exec-or-egress    an interpreter or a network-copy tool allowed with only a
                          wildcard after it -- Bash(python:*), Bash(curl *),
                          Bash(scp *). Any code, or any file to any host, with no
                          prompt.
  allow-everything        Bash / Bash(*) / Bash(:*) -- every shell command.
  claude-startup-lint     (opt-in, --with-claude-lint) Claude Code's OWN warnings,
                          parsed verbatim from a headless start. The only source for
                          "wildcard before the rest of the command": that check is
                          narrower than any simple heuristic -- calibrated 2026-10-01,
                          it warns on `rm -rf * /tmp` but not `ls * -la`, and a
                          whitespace-split heuristic produced 13 false positives on a
                          real settings file. So we ask Claude Code rather than guess.

Usage:
    python lint-permission-rules.py [--project DIR] [--json] [--with-claude-lint]

--with-claude-lint runs `claude -p` once (cheapest model, one turn) from the
project directory. It costs a small API call and fires the project's SessionStart
hooks like any session, which is why it is opt-in.

Always exits 0: this reports, it never gates.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path

SHELL_TOOLS = ("Bash", "PowerShell")

#: Allowed with nothing but a wildcard after them, these run arbitrary code.
INTERPRETERS = {
    "python", "python3", "py", "node", "npx", "deno", "bun", "tsx", "perl", "ruby",
    "bash", "sh", "zsh", "pwsh", "powershell", "powershell.exe", "cmd", "cmd.exe",
    "iex", "invoke-expression",
}
#: ...and these move data off the machine.
EGRESS = {
    "curl", "wget", "nc", "ncat", "netcat", "scp", "sftp", "rsync", "ftp",
    "invoke-webrequest", "iwr", "invoke-restmethod", "irm",
}

#: Project settings can be hostile: strip control characters (ANSI escapes, CR,
#: backspace) from anything echoed to the terminal so rule text stays inert.
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def _inert(s: str) -> str:
    return _CONTROL.sub("?", s)


RULE_RE = re.compile(r"^(?P<tool>[A-Za-z_][\w-]*)(?:\((?P<body>.*)\))?$", re.S)


def settings_files(project: Path) -> list[Path]:
    home = Path.home() / ".claude"
    return [home / "settings.json", home / "settings.local.json",
            project / ".claude" / "settings.json", project / ".claude" / "settings.local.json"]


def lint_rule(rule: str) -> list[dict]:
    m = RULE_RE.match(rule.strip())
    if not m or m.group("tool") not in SHELL_TOOLS:
        return []
    tool, body = m.group("tool"), m.group("body")
    if body is None or body.strip() in ("*", ":*", ""):
        return [{"check": "allow-everything", "severity": "Critical",
                 "why": f"approves every {tool} command with no prompt"}]

    out = []
    body = body.strip()
    prefix_form = body.endswith(":*")
    core = body[:-2] if prefix_form else body

    if prefix_form and "*" in core:
        out.append({"check": "mixed-wildcard-prefix", "severity": "Important",
                    "why": "mixes `*` with the trailing `:*` prefix form, so the `*` is taken "
                           "literally and the rule will likely never match"})

    head = (core.split() or [""])[0].lower()
    if head in INTERPRETERS | EGRESS:
        rest = core[len(head):].strip()
        if rest in ("", "*"):
            kind = "any code" if head in INTERPRETERS else "any file to any host"
            out.append({"check": "broad-exec-or-egress", "severity": "Important",
                        "why": f"`{head}` with only a wildcard after it -- runs {kind} with no prompt"})
    return out


def lint(project: Path) -> tuple[list[dict], list[str]]:
    findings, notes = [], []
    for p in settings_files(project):
        if not p.is_file():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            notes.append(f"{p}: unreadable ({type(exc).__name__}) -- not linted")
            continue
        allow = ((data.get("permissions") or {}).get("allow")) or []
        for i, rule in enumerate(allow):
            if not isinstance(rule, str):
                continue
            for f in lint_rule(rule):
                findings.append({"file": str(p), "index": i, "rule": rule, **f})
    return findings, notes


CLAUDE_WARNING_RE = re.compile(r"^Permission allow rule \((?P<file>[^)]*)\): (?P<rest>.+)$")


def claude_startup_lint(project: Path) -> tuple[list[dict], list[str]]:
    """Claude Code's own permission-rule warnings, from a one-turn headless start."""
    exe = shutil.which("claude")
    if not exe:
        return [], ["--with-claude-lint: `claude` not on PATH -- skipped"]
    try:
        proc = subprocess.run(
            [exe, "-p", "reply OK", "--max-turns", "1", "--model", "haiku"],
            cwd=str(project), stdin=subprocess.DEVNULL, capture_output=True,
            text=True, encoding="utf-8", errors="replace", timeout=180)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return [], [f"--with-claude-lint: could not run claude ({type(exc).__name__}) -- skipped"]
    findings = []
    for line in proc.stderr.splitlines():
        m = CLAUDE_WARNING_RE.match(line.strip())
        if m:
            findings.append({"file": m.group("file"), "index": None, "rule": m.group("rest"),
                             "check": "claude-startup-lint", "severity": "Important",
                             "why": "Claude Code's own startup warning (verbatim above)"})
    return findings, []


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--project", default=".", help="project root (default: cwd)")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--with-claude-lint", action="store_true",
                    help="also run Claude Code's own startup check (one small API call)")
    args = ap.parse_args()

    project = Path(args.project).resolve()
    findings, notes = lint(project)
    if args.with_claude_lint:
        extra, extra_notes = claude_startup_lint(project)
        findings += extra
        notes += extra_notes
    if args.json:
        print(json.dumps({"findings": findings, "notes": notes}, indent=2))
        return 0
    for n in notes:
        print(f"  note: {_inert(n)}")
    if not findings:
        print("  permission rules: no findings")
        return 0
    for f in findings:
        rule = _inert(f["rule"])
        shown = rule if len(rule) <= 100 else rule[:97] + "..."
        where = f"allow[{f['index']}]" if f["index"] is not None else ""
        print(f"  [{f['severity']}] {f['check']}  {_inert(f['file'])} {where}".rstrip())
        print(f"      {shown}")
        print(f"      {f['why']}")
    print(f"\n  {len(findings)} finding(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
