#!/usr/bin/env python
"""score-vault.py — deterministic hygiene audit for the harness.

Audits the auto-loaded surfaces (CLAUDE.md, MEMORY.md, .claude/rules/, the
memory directory) against the actual filesystem. Catches:
  - Broken path references in CLAUDE.md
  - Memory files linked from MEMORY.md that don't exist
  - Memory files on disk that aren't indexed (and aren't deprecated)
  - Deprecated memory files still linked from MEMORY.md
  - Broken cross-references between memory files
  - Missing required frontmatter (name/description/type)
  - Rule files without a paths:/keywords: trigger

Deterministic. No LLM call.

Usage:
  python score-vault.py            # human-readable markdown report
  python score-vault.py --json     # machine-readable JSON

Exit code is always 0 — a low score is information, not failure.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.harness_paths import memory_root, vault_root  # noqa: E402


SCRIPT_DIR = Path(__file__).parent
VAULT_ROOT = vault_root()
MEMORY_DIR = memory_root()

SEVERITY_WEIGHTS = {"CRITICAL": 10, "HIGH": 5, "MEDIUM": 2, "LOW": 1}
VALID_MEMORY_TYPES = {"user", "feedback", "project", "reference"}
REQUIRED_FRONTMATTER = ("name", "description", "type")

# Memory cross-reference pattern: reference_*.md / feedback_*.md / project_*.md /
# user_*.md. Lowercase + underscores by convention.
MEMORY_REF_RE = re.compile(
    r"\b((?:reference|feedback|project|user)_[a-z0-9_]+\.md)\b"
)

# Vault-relative path in backticks, leading two-digit folder prefix.
VAULT_PATH_RE = re.compile(r"`([0-9]{2}-[A-Za-z0-9_-]+(?:/[A-Za-z0-9_./-]+)?)`")

# Script reference: `scripts/foo.py`
SCRIPT_REF_RE = re.compile(r"`(scripts/[A-Za-z0-9_./-]+\.py)`")

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)


class Finding:
    __slots__ = ("severity", "category", "message", "file")

    def __init__(self, severity, category, message, file=None):
        self.severity = severity
        self.category = category
        self.message = message
        self.file = file

    def to_dict(self):
        return {
            "severity": self.severity,
            "category": self.category,
            "message": self.message,
            "file": self.file,
        }


def _read(path):
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


def _frontmatter(text):
    m = FRONTMATTER_RE.search(text)
    return m.group(1) if m else None


def _is_deprecated(path):
    fm = _frontmatter(_read(path))
    if not fm:
        return False
    return bool(re.search(r"^status:\s*deprecated\b", fm, re.MULTILINE))


def check_memory_index(findings):
    """MEMORY.md links must resolve; non-deprecated memory files must be indexed."""
    index_path = MEMORY_DIR / "MEMORY.md"
    if not index_path.exists():
        findings.append(
            Finding("CRITICAL", "memory-index", "MEMORY.md not found", str(index_path))
        )
        return

    text = _read(index_path)
    linked = set()
    for raw in re.findall(r"\]\(([^)]+\.md)\)", text):
        if raw.startswith(("http://", "https://", "..", "%")):
            continue
        if "%20" in raw or raw.startswith("/"):
            continue
        linked.add(Path(raw).name)

    actual = {f.name for f in MEMORY_DIR.glob("*.md") if f.name != "MEMORY.md"}

    for name in linked:
        if name not in actual:
            findings.append(
                Finding(
                    "HIGH",
                    "memory-index",
                    f"MEMORY.md links '{name}' but file does not exist",
                    "MEMORY.md",
                )
            )

    for name in actual:
        fpath = MEMORY_DIR / name
        deprecated = _is_deprecated(fpath)
        indexed = name in linked
        if deprecated and indexed:
            findings.append(
                Finding(
                    "MEDIUM",
                    "memory-index",
                    f"'{name}' is marked deprecated but still linked from MEMORY.md",
                    name,
                )
            )
        elif not deprecated and not indexed:
            findings.append(
                Finding(
                    "MEDIUM",
                    "memory-index",
                    f"'{name}' exists on disk but not in MEMORY.md (and not marked deprecated)",
                    name,
                )
            )


def check_memory_frontmatter(findings):
    """Each memory file needs name/description/type; type from allowlist."""
    for f in MEMORY_DIR.glob("*.md"):
        if f.name == "MEMORY.md":
            continue
        text = _read(f)
        fm = _frontmatter(text)
        if fm is None:
            findings.append(
                Finding("MEDIUM", "frontmatter", f"'{f.name}' has no frontmatter block", f.name)
            )
            continue
        for field in REQUIRED_FRONTMATTER:
            if not re.search(rf"^{field}:", fm, re.MULTILINE):
                findings.append(
                    Finding("LOW", "frontmatter", f"'{f.name}' missing field: {field}", f.name)
                )
        m_type = re.search(r"^type:\s*(\S+)", fm, re.MULTILINE)
        if m_type and m_type.group(1).strip().lower() not in VALID_MEMORY_TYPES:
            findings.append(
                Finding(
                    "LOW",
                    "frontmatter",
                    f"'{f.name}' has unknown type: {m_type.group(1)}",
                    f.name,
                )
            )


def check_memory_cross_refs(findings):
    """Memory files reference each other by basename — verify targets exist."""
    actual = {f.name for f in MEMORY_DIR.glob("*.md")}

    for f in MEMORY_DIR.glob("*.md"):
        text = _read(f)
        seen = set()
        for match in MEMORY_REF_RE.finditer(text):
            target = match.group(1)
            if target in seen:
                continue
            seen.add(target)
            if target not in actual:
                findings.append(
                    Finding(
                        "HIGH",
                        "memory-xref",
                        f"'{f.name}' references '{target}' which does not exist",
                        f.name,
                    )
                )


def check_claude_md_paths(findings):
    """Root CLAUDE.md path references — backticked vault paths must exist."""
    claude_md = VAULT_ROOT / "CLAUDE.md"
    if not claude_md.exists():
        findings.append(
            Finding("CRITICAL", "claude-md", f"CLAUDE.md not found at {claude_md}", "CLAUDE.md")
        )
        return

    text = _read(claude_md)

    seen = set()
    for match in VAULT_PATH_RE.finditer(text):
        rel = match.group(1)
        if rel in seen:
            continue
        seen.add(rel)
        target = VAULT_ROOT / rel
        if not target.exists():
            findings.append(
                Finding(
                    "CRITICAL",
                    "claude-md",
                    f"CLAUDE.md references '{rel}' which does not exist",
                    "CLAUDE.md",
                )
            )

    seen = set()
    for match in SCRIPT_REF_RE.finditer(text):
        rel = match.group(1)
        if rel in seen:
            continue
        seen.add(rel)
        target = VAULT_ROOT / rel
        if not target.exists():
            findings.append(
                Finding(
                    "HIGH",
                    "claude-md",
                    f"CLAUDE.md references script '{rel}' which does not exist",
                    "CLAUDE.md",
                )
            )


def check_rules(findings):
    """.claude/rules/*.md should have a paths:/keywords: trigger in frontmatter."""
    rules_dir = VAULT_ROOT / ".claude" / "rules"
    if not rules_dir.exists():
        return
    for f in rules_dir.glob("*.md"):
        text = _read(f)
        fm = _frontmatter(text)
        if fm is None:
            findings.append(
                Finding("MEDIUM", "rules", f"Rule '{f.name}' has no frontmatter", f.name)
            )
            continue
        has_trigger = (
            re.search(r"^paths:", fm, re.MULTILINE)
            or re.search(r"^keywords:", fm, re.MULTILINE)
            or re.search(r"^always:\s*(true|yes|1)\b", fm, re.MULTILINE | re.IGNORECASE)
        )
        if not has_trigger:
            findings.append(
                Finding(
                    "MEDIUM",
                    "rules",
                    f"Rule '{f.name}' has no `paths:`, `keywords:`, or `always: true` trigger",
                    f.name,
                )
            )


INLINE_LINK_RE = re.compile(r"(?<!\!)\[[^\]]+\]\(([^)\s<>]+)(?:\s+\"[^\"]*\")?\)")


def _is_internal_vault_path(target: str) -> bool:
    if not target:
        return False
    if target.startswith(("http://", "https://", "mailto:", "#", "/")):
        return False
    if re.match(r"^[a-zA-Z]:[\\/]", target):
        return False
    if "%20" in target or target.startswith("%"):
        return False
    return True


def check_citation_graph(findings):
    """Walk authored docs in 06-Decisions/ and 07-References/; verify that
    inline markdown link targets pointing to vault-relative paths resolve.
    """
    audit_roots = [
        VAULT_ROOT / "06-Decisions",
        VAULT_ROOT / "07-References",
    ]
    for root in audit_roots:
        if not root.exists():
            continue
        for f in root.rglob("*.md"):
            text = _read(f)
            if not text:
                continue
            seen = set()
            for match in INLINE_LINK_RE.finditer(text):
                target = match.group(1).strip()
                if target in seen:
                    continue
                seen.add(target)
                if not _is_internal_vault_path(target):
                    continue
                path_part = target.split("#", 1)[0]
                if not path_part:
                    continue
                rel_to_doc = (f.parent / path_part).resolve()
                rel_to_vault = (VAULT_ROOT / path_part).resolve()
                if rel_to_doc.exists() or rel_to_vault.exists():
                    continue
                try:
                    doc_rel = str(f.relative_to(VAULT_ROOT))
                except ValueError:
                    doc_rel = f.name
                findings.append(
                    Finding(
                        "MEDIUM",
                        "citation",
                        f"'{doc_rel}' cites '{target}' which does not exist",
                        doc_rel,
                    )
                )


# Anti-pattern detection thresholds — advisory, not blocking.
ANTIPATTERN_STALE_CAPTURE_DAYS = 30
ANTIPATTERN_STALE_CAPTURE_THRESHOLD = 50
ANTIPATTERN_AUDIT_FILE_THRESHOLD = 5


def check_antipatterns(findings):
    """LOW-severity advisories.

    - 'Notes go in but never come out': captures older than N days.
    - Audit-file backlog: unattended-run audit files accumulating.
    """
    import time

    captured = VAULT_ROOT / "00-Inbox" / "_captured"
    if captured.exists():
        cutoff = time.time() - ANTIPATTERN_STALE_CAPTURE_DAYS * 86400
        stale = 0
        for p in captured.rglob("*.md"):
            try:
                if p.stat().st_mtime < cutoff:
                    stale += 1
            except OSError:
                continue
        if stale >= ANTIPATTERN_STALE_CAPTURE_THRESHOLD:
            findings.append(
                Finding(
                    "LOW",
                    "antipattern",
                    f"{stale} captures older than {ANTIPATTERN_STALE_CAPTURE_DAYS}d in "
                    f"`00-Inbox/_captured/` — 'notes go in but never come out' "
                    f"anti-pattern. Consider archiving via `/triage-inbox` or moving "
                    f"to `09-Archive/`.",
                    "00-Inbox/_captured/",
                )
            )

    audit_dir = VAULT_ROOT / "00-Inbox" / "_captured" / "_audit"
    if audit_dir.exists():
        audit_files = list(audit_dir.glob("*.md"))
        if len(audit_files) >= ANTIPATTERN_AUDIT_FILE_THRESHOLD:
            findings.append(
                Finding(
                    "LOW",
                    "antipattern",
                    f"{len(audit_files)} unreviewed audit files in "
                    f"`00-Inbox/_captured/_audit/`. Each was flagged by a post-run "
                    f"audit and warrants review — see "
                    f"`07-References/security-baselines.md` C-5.",
                    "00-Inbox/_captured/_audit/",
                )
            )


def compute_score(findings):
    deductions = sum(SEVERITY_WEIGHTS[f.severity] for f in findings)
    return max(0, 100 - deductions)


def emit_json(score, findings):
    print(
        json.dumps(
            {
                "score": score,
                "finding_count": len(findings),
                "findings": [f.to_dict() for f in findings],
            },
            indent=2,
        )
    )


def emit_markdown(score, findings):
    print(f"# Vault hygiene score: {score}/100")
    print()
    print(f"**Findings:** {len(findings)}")
    print()

    if not findings:
        print("Clean. No issues found.")
        return

    by_sev = {}
    for f in findings:
        by_sev.setdefault(f.severity, []).append(f)

    for sev in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
        if sev not in by_sev:
            continue
        print(f"## {sev} ({len(by_sev[sev])})")
        print()
        print("| Category | File | Message |")
        print("|---|---|---|")
        for f in by_sev[sev]:
            file_str = f.file or "—"
            msg = f.message.replace("|", "\\|")
            print(f"| {f.category} | `{file_str}` | {msg} |")
        print()


def main():
    findings = []
    check_memory_index(findings)
    check_memory_frontmatter(findings)
    check_memory_cross_refs(findings)
    check_claude_md_paths(findings)
    check_rules(findings)
    check_citation_graph(findings)
    check_antipatterns(findings)

    score = compute_score(findings)

    if "--json" in sys.argv:
        emit_json(score, findings)
    else:
        emit_markdown(score, findings)

    return 0


if __name__ == "__main__":
    sys.exit(main())
