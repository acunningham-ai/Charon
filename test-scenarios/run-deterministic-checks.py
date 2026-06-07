#!/usr/bin/env python3
"""run-deterministic-checks.py — Charon test suite, automated portion.

Runs the deterministic checks (numbered 11+ in the suite) — the ones that
don't need an LLM in the loop. Each check returns PASS / WARN / FAIL.

Usage:
    python test-scenarios/run-deterministic-checks.py             # human-readable
    python test-scenarios/run-deterministic-checks.py --json      # machine-readable
    python test-scenarios/run-deterministic-checks.py --no-color  # disable ANSI

Exit code:
    0  if every check passes (WARN tolerated)
    1  if any check FAILs

Designed to run from the Charon repo root (the parent of test-scenarios/).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parent.parent
RULES_DIR = REPO_ROOT / ".claude" / "rules"
AGENTS_DIR = REPO_ROOT / ".claude" / "agents"
HOOKS_DIR = REPO_ROOT / "scripts" / "hooks"
SETTINGS_FILE = REPO_ROOT / ".claude" / "settings.json"
MCP_FILE = REPO_ROOT / ".mcp.json"
QUESTIONS_FILE = REPO_ROOT / "scripts" / "first-run-questions.yaml"
FIRST_RUN_SCRIPT = REPO_ROOT / "scripts" / "first-run.py"
BANNER_SCRIPT = REPO_ROOT / "scripts" / "lib" / "banner.py"
SEMANTIC_INDEX_SCRIPT = REPO_ROOT / "scripts" / "semantic_index.py"
EXTRACT_ENTITIES_SCRIPT = REPO_ROOT / "scripts" / "extract_entities.py"
VOICE_CAPTURE_SCRIPT = REPO_ROOT / "scripts" / "voice-capture.py"
GRAPH_LIB = REPO_ROOT / "scripts" / "lib" / "graph.py"
SEMANTIC_LIB = REPO_ROOT / "scripts" / "lib" / "semantic.py"

EXPECTED_SUBAGENTS = {
    "secure-code-reviewer",
    "owasp-llm-reviewer",
    "owasp-agentic-reviewer",
    "knowledge-synthesizer",
}

ALWAYS_FIRE_RULES = [
    "no-assumptions.md",
    "save-on-mention.md",
    "session-start-ritual.md",
    "confidence-tags.md",
]

# Hooks that are intentionally not wired in settings.json — invoked directly
# from runners or .bat scripts. Document new entries here as they're added.
STANDALONE_HOOKS = {
    "on-error.py",       # called from scheduled .bat runners on non-zero exit
    "_telemetry.py",     # imported by other hooks, not invoked by Claude Code
    "_verdict.py",       # imported by hooks adopting the verdict layer, not invoked directly
    "_jsonl_append.py",  # imported by _verdict.py and _telemetry.py for safe append
}

# Personal-content patterns — must NOT appear in any Charon file.
# Each pattern is a (regex, name, severity, allowlist) tuple.
# allowlist = paths where the pattern is acceptable (e.g. LICENSE for the author's name).
PERSONAL_PATTERNS = [
    (r"\bvela\b", "Vela keyword", "FAIL", []),
    (r"\bvelaapx\b", "Vela company name", "FAIL", []),
    (r"\bMagentus\b", "Magentus reference", "FAIL", []),
    (r"\bAccredo\b", "Accredo BU name", "FAIL", []),
    (r"\b(Argo|Atlas|Centaurus)\b(?!\s+Pipeline)", "Vela portfolio name", "FAIL", []),
    (r"\bSchmutter\b", "personnel name", "FAIL", []),
    (r"\bKaren Chung\b", "personnel name", "FAIL", []),
    (r"\bRaj Gurusinghe\b", "personnel name", "FAIL", []),
    # Joh Leonhardt — original Cerberus author; attribution allowed in Cerberus-related files
    (r"\bJoh Leonhardt\b", "personnel name", "FAIL", [
        ".claude/commands/cerberus-setup.md",
        ".claude/commands/cerberus-audit.md",
        ".claude/commands/cerberus-vet.md",
        ".claude/commands/cerberus-recover.md",
        ".claude/commands/cerberus-deps.md",
        "CAPABILITIES.md",
        "README.md",
        "CHANGELOG.md",
        "ROADMAP.md",
    ]),
    (r"\bBrad Mason\b", "personnel name", "FAIL", []),
    (r"\bLuke Haites\b", "personnel name", "FAIL", []),
    (r"\bBen Dowling\b", "personnel name", "FAIL", []),
    (r"\bMark Clearwater\b", "personnel name", "FAIL", []),
    (r"Payroll\s+Bot", "Payroll Bot reference", "FAIL", []),
    # Cerberus — now a shipping capability in Charon (v0.3.0-preview, 2026-05-25)
    # Previously excluded; the proprietary fork concern was resolved when Adam released
    # the engine under MIT with Vela approval. The capability ships from the .claude/
    # tree alongside the rest of the harness.
    (r"\bWardgate\b", "Wardgate reference", "FAIL", []),
    (r"\bPlaud\b", "Plaud reference", "FAIL", []),
    (r"\bCrowdStrike\b", "CrowdStrike reference", "FAIL", []),
    (r"\bConnX\b", "ConnX reference", "FAIL", []),
    (r"\bTurso\b", "Turso reference", "FAIL", []),
    (r"\bQSR\b", "QSR shorthand", "FAIL", []),
    # Adam-personal — name allowed only in LICENSE
    (r"Adam Cunningham", "author name outside LICENSE", "FAIL", ["LICENSE"]),
    # Adam-personal paths
    (r"AdamCunningham", "user-path leak", "FAIL", []),
    (r"OneDrive - Vela", "OneDrive path leak", "FAIL", []),
]

# Files to skip entirely during the personal-content scrub.
SCRUB_SKIP_GLOBS = [
    ".git/**",
    "test-scenarios/run-deterministic-checks.py",  # contains the patterns themselves
    "scripts/lib/charon-logo.txt",                  # ASCII art may match arbitrary chars
]


# ---------- ANSI ----------

class Ansi:
    enabled = True

    @classmethod
    def configure(cls, no_color: bool) -> None:
        cls.enabled = not no_color and sys.stdout.isatty()

    @classmethod
    def _wrap(cls, code: str, text: str) -> str:
        return f"\033[{code}m{text}\033[0m" if cls.enabled else text

    @classmethod
    def green(cls, t: str) -> str: return cls._wrap("32", t)
    @classmethod
    def yellow(cls, t: str) -> str: return cls._wrap("33", t)
    @classmethod
    def red(cls, t: str) -> str: return cls._wrap("31", t)
    @classmethod
    def dim(cls, t: str) -> str: return cls._wrap("2", t)


# ---------- Result model ----------

@dataclass
class CheckResult:
    name: str
    status: str  # PASS / WARN / FAIL
    detail: str = ""
    findings: list[str] = field(default_factory=list)

    def is_blocking(self) -> bool:
        return self.status == "FAIL"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "findings": self.findings,
        }


# ---------- Check implementations ----------

def check_yaml_schema() -> CheckResult:
    """Verify first-run-questions.yaml parses + has valid schema."""
    try:
        import yaml
    except ImportError:
        return CheckResult(
            "YAML schema validation",
            "FAIL",
            "PyYAML not installed — pip install PyYAML or run requirements.txt install.",
        )
    if not QUESTIONS_FILE.exists():
        return CheckResult("YAML schema validation", "FAIL", f"missing: {QUESTIONS_FILE}")
    try:
        data = yaml.safe_load(QUESTIONS_FILE.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        return CheckResult("YAML schema validation", "FAIL", f"parse error: {e}")

    findings = []
    if not isinstance(data, dict):
        return CheckResult("YAML schema validation", "FAIL", "top level is not a mapping")
    for key in ("phases", "questions", "templates", "env_vars"):
        if key not in data:
            findings.append(f"missing top-level key: {key}")

    phase_ids = {p["id"] for p in (data.get("phases") or []) if isinstance(p, dict) and "id" in p}
    question_ids = set()
    allowed_types = {"string", "multiline", "path-dir", "path-file", "yes-no", "choice", "secret"}

    for q in (data.get("questions") or []):
        if not isinstance(q, dict):
            findings.append("question entry is not a mapping")
            continue
        for f in ("id", "phase", "prompt", "type"):
            if f not in q:
                findings.append(f"question {q.get('id', '?')} missing field: {f}")
        qid = q.get("id")
        if qid in question_ids:
            findings.append(f"duplicate question id: {qid}")
        question_ids.add(qid)
        if q.get("phase") not in phase_ids:
            findings.append(f"question {qid} references unknown phase: {q.get('phase')}")
        if q.get("type") not in allowed_types:
            findings.append(f"question {qid} has unknown type: {q.get('type')}")

    for tid, tdef in (data.get("templates") or {}).items():
        if not isinstance(tdef, dict):
            findings.append(f"template {tid}: not a mapping")
            continue
        for req in (tdef.get("require_any") or []):
            if req not in question_ids:
                findings.append(f"template {tid}: require_any references unknown question: {req}")

    for ev in (data.get("env_vars") or []):
        vf = ev.get("value_from") if isinstance(ev, dict) else None
        if vf and vf not in question_ids:
            findings.append(f"env_var {ev.get('name')}: value_from references unknown question: {vf}")

    if findings:
        return CheckResult("YAML schema validation", "FAIL", f"{len(findings)} issue(s)", findings)
    counts = (
        f"{len(phase_ids)} phases, {len(question_ids)} questions, "
        f"{len(data.get('templates') or {})} templates, {len(data.get('env_vars') or [])} env vars"
    )
    return CheckResult("YAML schema validation", "PASS", counts)


def check_hook_wiring() -> CheckResult:
    """Every scripts/hooks/*.py is referenced in settings.json (or on the standalone allowlist)."""
    if not SETTINGS_FILE.exists():
        return CheckResult("Hook wiring coverage", "FAIL", f"missing: {SETTINGS_FILE}")
    if not HOOKS_DIR.is_dir():
        return CheckResult("Hook wiring coverage", "FAIL", f"missing: {HOOKS_DIR}")
    settings_text = SETTINGS_FILE.read_text(encoding="utf-8")
    findings = []
    for hook in sorted(HOOKS_DIR.glob("*.py")):
        name = hook.name
        if name in STANDALONE_HOOKS:
            continue
        # Look for the filename in settings.json (rough but reliable check)
        if name not in settings_text:
            findings.append(f"{name} not referenced in settings.json (and not on STANDALONE_HOOKS allowlist)")
    if findings:
        return CheckResult("Hook wiring coverage", "FAIL", f"{len(findings)} unwired hook(s)", findings)
    return CheckResult("Hook wiring coverage", "PASS", "all hooks accounted for")


def check_rule_frontmatter() -> CheckResult:
    """Every .claude/rules/*.md has frontmatter with at least one trigger."""
    if not RULES_DIR.is_dir():
        return CheckResult("Rule frontmatter validation", "FAIL", f"missing: {RULES_DIR}")
    findings = []
    rule_files = list(RULES_DIR.glob("*.md"))
    if not rule_files:
        return CheckResult("Rule frontmatter validation", "FAIL", "no rule files found")
    for rule in sorted(rule_files):
        content = rule.read_text(encoding="utf-8")
        m = re.match(r"^---\r?\n(.*?)\r?\n---", content, re.S)
        if not m:
            findings.append(f"{rule.name}: missing YAML frontmatter")
            continue
        fm = m.group(1)
        has_always = re.search(r"^\s*always:\s*true", fm, re.M)
        has_paths = re.search(r"^\s*paths:", fm, re.M)
        has_keywords = re.search(r"^\s*keywords:", fm, re.M)
        if not (has_always or has_paths or has_keywords):
            findings.append(f"{rule.name}: no trigger (no `always: true`, no `paths:`, no `keywords:`)")
    if findings:
        return CheckResult("Rule frontmatter validation", "FAIL", f"{len(findings)} rule(s) with issues", findings)
    return CheckResult("Rule frontmatter validation", "PASS", f"{len(rule_files)} rules valid")


def check_always_fire_rules() -> CheckResult:
    """The four foundational always-fire rules ship and are correctly tagged."""
    findings = []
    for name in ALWAYS_FIRE_RULES:
        path = RULES_DIR / name
        if not path.exists():
            findings.append(f"missing: {name}")
            continue
        content = path.read_text(encoding="utf-8")
        m = re.match(r"^---\r?\n(.*?)\r?\n---", content, re.S)
        if not m or not re.search(r"^\s*always:\s*true", m.group(1), re.M):
            findings.append(f"{name}: not tagged `always: true`")
    if findings:
        return CheckResult("Always-fire rules present", "FAIL", f"{len(findings)} issue(s)", findings)
    return CheckResult("Always-fire rules present", "PASS", "all 4 present")


def _should_skip_for_scrub(path: Path) -> bool:
    rel = path.relative_to(REPO_ROOT).as_posix()
    for pat in SCRUB_SKIP_GLOBS:
        pat_re = "^" + re.escape(pat).replace(r"\*\*", ".*").replace(r"\*", "[^/]*") + "$"
        if re.match(pat_re, rel):
            return True
    return False


def check_personal_content_scrub() -> CheckResult:
    """No personal / Vela-specific content leaks into shipped files."""
    findings = []
    # Walk the repo, skip .git and binary files
    text_extensions = {".md", ".py", ".ps1", ".sh", ".yaml", ".yml", ".json", ".txt", ".bat"}
    for root, dirs, files in os.walk(REPO_ROOT):
        if ".git" in dirs:
            dirs.remove(".git")
        for fname in files:
            path = Path(root) / fname
            if path.suffix.lower() not in text_extensions:
                continue
            if _should_skip_for_scrub(path):
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue
            rel = path.relative_to(REPO_ROOT).as_posix()
            for pattern, label, _severity, allowlist in PERSONAL_PATTERNS:
                if rel in allowlist:
                    continue
                m = re.search(pattern, content)
                if m:
                    # Find line number
                    line_no = content[:m.start()].count("\n") + 1
                    findings.append(f"{rel}:{line_no}: {label} -- `{m.group(0)}`")
    if findings:
        return CheckResult(
            "No-personal-content scrub",
            "FAIL",
            f"{len(findings)} leak(s) detected",
            findings[:30],  # cap for output sanity
        )
    return CheckResult("No-personal-content scrub", "PASS", "clean")


def check_first_run_launches() -> CheckResult:
    """`python scripts/first-run.py --help` exits 0."""
    if not FIRST_RUN_SCRIPT.exists():
        return CheckResult("First-run wizard launches", "FAIL", f"missing: {FIRST_RUN_SCRIPT}")
    try:
        result = subprocess.run(
            [sys.executable, str(FIRST_RUN_SCRIPT), "--help"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as e:
        return CheckResult("First-run wizard launches", "FAIL", f"exec error: {e}")
    if result.returncode != 0:
        return CheckResult(
            "First-run wizard launches",
            "FAIL",
            f"exit code {result.returncode}",
            [result.stderr.strip()[:500]] if result.stderr else [],
        )
    if "first-run" not in result.stdout.lower() and "wizard" not in result.stdout.lower():
        return CheckResult(
            "First-run wizard launches",
            "WARN",
            "exit 0 but help text doesn't mention 'first-run' or 'wizard'",
        )
    return CheckResult("First-run wizard launches", "PASS", "exit 0, help text rendered")


def check_banner_renders() -> CheckResult:
    """`python scripts/lib/banner.py --logo small` outputs non-empty text."""
    if not BANNER_SCRIPT.exists():
        return CheckResult("Banner module renders", "FAIL", f"missing: {BANNER_SCRIPT}")
    try:
        result = subprocess.run(
            [sys.executable, str(BANNER_SCRIPT), "--logo", "small"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as e:
        return CheckResult("Banner module renders", "FAIL", f"exec error: {e}")
    if result.returncode != 0:
        return CheckResult("Banner module renders", "FAIL", f"exit code {result.returncode}")
    if not result.stdout.strip():
        return CheckResult("Banner module renders", "FAIL", "empty output")
    return CheckResult("Banner module renders", "PASS", f"{len(result.stdout)} bytes of banner")


def check_subagent_frontmatter() -> CheckResult:
    """All expected subagents present with valid frontmatter (name, description, tools)."""
    if not AGENTS_DIR.is_dir():
        return CheckResult("Subagent frontmatter", "FAIL", f"missing: {AGENTS_DIR}")
    findings: list[str] = []
    found_names: set[str] = set()
    for agent_file in sorted(AGENTS_DIR.glob("*.md")):
        if agent_file.name == "README.md":
            continue
        try:
            content = agent_file.read_text(encoding="utf-8")
        except Exception as e:
            findings.append(f"{agent_file.name}: unreadable ({e})")
            continue
        m = re.match(r"^---\r?\n(.*?)\r?\n---", content, re.S)
        if not m:
            findings.append(f"{agent_file.name}: missing frontmatter")
            continue
        fm = m.group(1)
        name_match = re.search(r"^\s*name:\s*(\S+)", fm, re.M)
        desc_match = re.search(r"^\s*description:\s*\S+", fm, re.M)
        tools_match = re.search(r"^\s*tools:\s*\S+", fm, re.M)
        if not name_match:
            findings.append(f"{agent_file.name}: missing `name:` in frontmatter")
            continue
        if not desc_match:
            findings.append(f"{agent_file.name}: missing `description:` in frontmatter")
        if not tools_match:
            findings.append(f"{agent_file.name}: missing `tools:` in frontmatter")
        found_names.add(name_match.group(1))
    missing = EXPECTED_SUBAGENTS - found_names
    if missing:
        findings.append(f"expected subagents missing: {sorted(missing)}")
    if findings:
        return CheckResult("Subagent frontmatter", "FAIL", f"{len(findings)} issue(s)", findings)
    return CheckResult("Subagent frontmatter", "PASS", f"{len(found_names)} subagents, all valid")


def check_optional_libs_importable() -> CheckResult:
    """Optional-feature libraries (graph, semantic) must import cleanly even
    when their heavy deps aren't installed (graceful-degradation property)."""
    findings: list[str] = []
    for label, path in [("graph", GRAPH_LIB), ("semantic", SEMANTIC_LIB)]:
        if not path.exists():
            findings.append(f"missing: {path}")
            continue
        try:
            # Import via a subprocess so we don't pollute this process's sys.modules
            result = subprocess.run(
                [sys.executable, "-c",
                 f"import sys; sys.path.insert(0, r'{REPO_ROOT / 'scripts'}'); "
                 f"from lib import {label}; "
                 f"ok, reason = {label}.is_available(); "
                 f"print(f'{label} importable; available={{ok}}; reason={{reason}}')"],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode != 0:
                findings.append(f"{label}: import failed: {result.stderr.strip()[:300]}")
        except Exception as e:
            findings.append(f"{label}: subprocess error: {e}")
    if findings:
        return CheckResult("Optional libs importable", "FAIL", f"{len(findings)} issue(s)", findings)
    return CheckResult("Optional libs importable", "PASS", "graph + semantic libs import (graceful when deps absent)")


def check_optional_scripts_launch() -> CheckResult:
    """Optional-feature CLI scripts must respond to --help / --stats without
    crashing, even when their deps aren't installed."""
    findings: list[str] = []
    targets = [
        (SEMANTIC_INDEX_SCRIPT, ["--stats"], "semantic_index"),
        (EXTRACT_ENTITIES_SCRIPT, ["--stats"], "extract_entities"),
        (VOICE_CAPTURE_SCRIPT, ["--help"], "voice-capture"),
    ]
    for script, args, label in targets:
        if not script.exists():
            findings.append(f"missing: {script}")
            continue
        try:
            result = subprocess.run(
                [sys.executable, str(script)] + args,
                capture_output=True, text=True, timeout=15,
            )
            # Exit 0 = ran cleanly. Exit 1 = degraded (deps missing) — also acceptable;
            # what matters is no crash + clear messaging.
            if result.returncode not in (0, 1):
                findings.append(f"{label}: exit code {result.returncode} (expected 0 or 1)")
        except Exception as e:
            findings.append(f"{label}: subprocess error: {e}")
    if findings:
        return CheckResult("Optional scripts launch", "FAIL", f"{len(findings)} issue(s)", findings)
    return CheckResult("Optional scripts launch", "PASS", "semantic/extract/voice scripts launch cleanly")


def check_cerberus_engine_smoke() -> CheckResult:
    """Run cerberus.engine.smoke_test; assert every check passes."""
    if not (REPO_ROOT / "cerberus" / "engine" / "smoke_test.py").exists():
        return CheckResult("Cerberus engine smoke", "FAIL",
                           "missing: cerberus/engine/smoke_test.py")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "cerberus.engine.smoke_test"],
            capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=60,
        )
    except Exception as e:
        return CheckResult("Cerberus engine smoke", "FAIL", f"subprocess error: {e}")
    if result.returncode != 0:
        tail = (result.stdout + result.stderr)[-300:]
        return CheckResult("Cerberus engine smoke", "FAIL",
                           f"exit {result.returncode}: ...{tail}")
    m = re.search(r"(\d+)/(\d+) passed", result.stdout)
    if not m:
        return CheckResult("Cerberus engine smoke", "FAIL",
                           "summary line 'N/N passed' missing from output")
    passed, total = int(m.group(1)), int(m.group(2))
    if passed != total:
        return CheckResult("Cerberus engine smoke", "FAIL", f"{passed}/{total} passed")
    return CheckResult("Cerberus engine smoke", "PASS", f"{passed}/{total} passed")


def check_cerberus_scan_text_format() -> CheckResult:
    """Run scripts.cerberus.scan against the engine source itself; verify text output renders."""
    target = REPO_ROOT / "cerberus" / "engine"
    if not target.exists():
        return CheckResult("Cerberus scan text format", "FAIL", f"missing: {target}")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "scripts.cerberus.scan", str(target), "--format", "text"],
            capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=120,
        )
    except Exception as e:
        return CheckResult("Cerberus scan text format", "FAIL", f"subprocess error: {e}")
    # Exit code 0 = clean, 1 = findings present, 2 = error. 0 or 1 means the scan ran successfully.
    if result.returncode not in (0, 1):
        tail = (result.stdout + result.stderr)[-300:]
        return CheckResult("Cerberus scan text format", "FAIL",
                           f"exit {result.returncode}: ...{tail}")
    if "Cerberus scan" not in result.stdout or "finding(s)" not in result.stdout:
        return CheckResult("Cerberus scan text format", "FAIL",
                           "expected 'Cerberus scan' + 'finding(s)' in output")
    m = re.search(r"(\d+)\s+finding\(s\)", result.stdout)
    count = m.group(1) if m else "?"
    return CheckResult("Cerberus scan text format", "PASS", f"{count} finding(s) from scan")


def check_cerberus_sarif_validates() -> CheckResult:
    """Run scripts.cerberus.scan with --format sarif on a tiny fixture; verify structural shape."""
    target = REPO_ROOT / "cerberus" / "engine" / "__init__.py"
    if not target.exists():
        return CheckResult("Cerberus SARIF output", "FAIL", f"missing: {target}")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "scripts.cerberus.scan", str(target), "--format", "sarif"],
            capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=60,
        )
    except Exception as e:
        return CheckResult("Cerberus SARIF output", "FAIL", f"subprocess error: {e}")
    if result.returncode not in (0, 1):
        tail = (result.stdout + result.stderr)[-300:]
        return CheckResult("Cerberus SARIF output", "FAIL",
                           f"exit {result.returncode}: ...{tail}")
    try:
        sarif = json.loads(result.stdout)
    except json.JSONDecodeError as e:
        return CheckResult("Cerberus SARIF output", "FAIL", f"invalid JSON: {e}")
    # Use the engine's own structural validator
    try:
        proc = subprocess.run(
            [sys.executable, "-c",
             "import json, sys; "
             "from cerberus.engine.sarif import validate_sarif_shape; "
             "issues = validate_sarif_shape(json.loads(sys.stdin.read())); "
             "print('OK' if not issues else 'ISSUES: ' + '; '.join(issues))"],
            input=result.stdout, capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=10,
        )
        if proc.returncode != 0 or not proc.stdout.startswith("OK"):
            return CheckResult("Cerberus SARIF output", "FAIL",
                               proc.stdout.strip() or proc.stderr.strip())
    except Exception as e:
        return CheckResult("Cerberus SARIF output", "FAIL", f"validation error: {e}")
    # Schema sanity
    if sarif.get("version") != "2.1.0":
        return CheckResult("Cerberus SARIF output", "FAIL", "version != 2.1.0")
    return CheckResult("Cerberus SARIF output", "PASS",
                       f"v{sarif['version']}, {len(sarif['runs'][0]['results'])} results")


def check_closed_vocabularies() -> CheckResult:
    """Verify the closed-vocabulary sets in graph.py exist and are non-empty
    (per C-3.1 value-layer constraint)."""
    if not GRAPH_LIB.exists():
        return CheckResult("Closed-vocabulary check", "FAIL", f"missing: {GRAPH_LIB}")
    try:
        result = subprocess.run(
            [sys.executable, "-c",
             f"import sys; sys.path.insert(0, r'{REPO_ROOT / 'scripts'}'); "
             f"from lib import graph; "
             f"assert isinstance(graph.ENTITY_TYPES, frozenset) and len(graph.ENTITY_TYPES) > 0, 'ENTITY_TYPES empty'; "
             f"assert isinstance(graph.RELATIONSHIP_TYPES, frozenset) and len(graph.RELATIONSHIP_TYPES) > 0, 'RELATIONSHIP_TYPES empty'; "
             f"print(f'entity_types={{len(graph.ENTITY_TYPES)}}, rel_types={{len(graph.RELATIONSHIP_TYPES)}}')"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            return CheckResult("Closed-vocabulary check", "FAIL",
                               result.stderr.strip()[:200] or "subprocess returned non-zero")
        return CheckResult("Closed-vocabulary check", "PASS", result.stdout.strip())
    except Exception as e:
        return CheckResult("Closed-vocabulary check", "FAIL", f"subprocess error: {e}")


# ---------- Output ----------

CHECKS = [
    ("D1", check_yaml_schema),
    ("D2", check_hook_wiring),
    ("D3", check_rule_frontmatter),
    ("D4", check_always_fire_rules),
    ("D5", check_personal_content_scrub),
    ("D6", check_first_run_launches),
    ("D7", check_banner_renders),
    ("D8", check_subagent_frontmatter),
    ("D9", check_optional_libs_importable),
    ("D10", check_optional_scripts_launch),
    ("D11", check_closed_vocabularies),
    ("D12", check_cerberus_engine_smoke),
    ("D13", check_cerberus_scan_text_format),
    ("D14", check_cerberus_sarif_validates),
]


def render_status(status: str) -> str:
    if status == "PASS":
        return Ansi.green("PASS")
    if status == "WARN":
        return Ansi.yellow("WARN")
    return Ansi.red("FAIL")


def print_human(results: list[tuple[str, CheckResult]]) -> int:
    print()
    print("Charon — deterministic test checks")
    print(Ansi.dim(f"repo: {REPO_ROOT}"))
    print()
    total = len(results)
    passed = sum(1 for _, r in results if r.status == "PASS")
    warned = sum(1 for _, r in results if r.status == "WARN")
    failed = sum(1 for _, r in results if r.status == "FAIL")
    width = max(len(r.name) for _, r in results) + 2

    for num, r in results:
        dots = "." * max(3, width + 5 - len(r.name))
        line = f"  [{num}] {r.name} {dots} {render_status(r.status)}"
        if r.detail:
            line += Ansi.dim(f"  ({r.detail})")
        print(line)
        for finding in r.findings:
            print(Ansi.dim(f"        - {finding}"))

    print()
    summary = f"Summary: {passed} PASS, {warned} WARN, {failed} FAIL  ({total} total)"
    if failed:
        print(Ansi.red(summary))
    elif warned:
        print(Ansi.yellow(summary))
    else:
        print(Ansi.green(summary))

    if failed:
        print()
        print(Ansi.red("Deterministic checks BLOCKED — fix the FAILs before release."))
    return 1 if failed else 0


def print_json(results: list[tuple[str, CheckResult]]) -> int:
    payload = {
        "checks": [{"num": num, **r.to_dict()} for num, r in results],
        "passed": sum(1 for _, r in results if r.status == "PASS"),
        "warned": sum(1 for _, r in results if r.status == "WARN"),
        "failed": sum(1 for _, r in results if r.status == "FAIL"),
    }
    print(json.dumps(payload, indent=2))
    return 1 if payload["failed"] else 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Charon deterministic test checks")
    parser.add_argument("--json", action="store_true", help="emit JSON")
    parser.add_argument("--no-color", action="store_true", help="disable ANSI colors")
    args = parser.parse_args()
    Ansi.configure(args.no_color)

    results = [(num, fn()) for num, fn in CHECKS]
    if args.json:
        return print_json(results)
    return print_human(results)


if __name__ == "__main__":
    sys.exit(main())
