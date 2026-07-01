#!/usr/bin/env python
"""vault-lint.py — content-graph hygiene lint for the authored vault body.

Complements scripts/score-vault.py, which audits the harness SURFACES
(memory dir, CLAUDE.md, .claude/rules/, and markdown links in 06-/07- only).
This lint covers the authored knowledge body with two checks:

  B. Broken markdown file-links across the authored body
     Walks 01-Daily, 02-BUs, 03-Domains, 04-People, 05-Meetings, 08-Projects and
     verifies inline [text](path.md) links to vault-internal paths resolve.
     06-/07- are score-vault's turf; 00-Inbox (untrusted captures) and 09-Archive
     (cold) are skipped, as are any `captured/` subtrees.

  C. Tag-taxonomy drift
     Lints frontmatter `tags:` against the faceted taxonomy in
     07-References/tag-taxonomy.md (the fenced ```json block is the source of
     truth). Flags bare (un-namespaced) tags, unknown facets, and unknown values
     in closed facets. Inline #hashtags are NOT governed (social tags). The
     engine hardcodes no facet or value — it reads whatever the taxonomy declares.

There is deliberately no graph-orphan check: degree-0 entities and file-level
orphans are firehoses when a vault connects via the `[[Entity]] (REL)` graph
rather than note-to-note markdown links. "What's under-connected" is a
/vault-query question, not a hygiene lint.

Deterministic. No LLM call. Read-only — never edits the vault.

Usage:
  python scripts/vault-lint.py            # human-readable markdown worklist
  python scripts/vault-lint.py --json     # machine-readable JSON

Exit code is always 0 — findings are a worklist, not a failure.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.harness_paths import vault_root  # noqa: E402

VAULT_ROOT = vault_root()

# Authored dirs this lint owns. 06-/07- excluded (score-vault checks those);
# 00-Inbox (untrusted captures) and 09-Archive (cold storage) excluded.
LINT_DIRS = ("01-Daily", "02-BUs", "03-Domains", "04-People", "05-Meetings", "08-Projects")

# Directory segments that mark untrusted captured content — never our links to fix.
CAPTURED_SEGMENTS = {"captured", "_captured", "_audit"}

TAXONOMY_DOC = VAULT_ROOT / "07-References" / "tag-taxonomy.md"

# Inline markdown link: [text](target). Skips images (!) and angle-bracket
# template placeholders [text](<path>). Mirrors score-vault's resolver.
INLINE_LINK_RE = re.compile(r"(?<!\!)\[[^\]]+\]\(([^)\s<>]+)(?:\s+\"[^\"]*\")?\)")

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
JSON_BLOCK_RE = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


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


def _is_captured(rel: Path) -> bool:
    """True if any DIRECTORY component marks captured/untrusted content."""
    return any(part.lower() in CAPTURED_SEGMENTS for part in rel.parts[:-1])


def _authored_md_files():
    for d in LINT_DIRS:
        root = VAULT_ROOT / d
        if not root.exists():
            continue
        for f in root.rglob("*.md"):
            try:
                rel = f.relative_to(VAULT_ROOT)
            except ValueError:
                continue
            if _is_captured(rel):
                continue
            yield f, rel


# ---------- Check B: broken markdown file-links ----------

def _is_internal_vault_path(target: str) -> bool:
    """Vault-internal relative path, not a URL / anchor / absolute path.
    Lifted from score-vault.py so the two tools resolve links identically."""
    if not target:
        return False
    if target.startswith(("http://", "https://", "mailto:", "#", "/")):
        return False
    if re.match(r"^[a-zA-Z]:[\\/]", target):
        return False
    if "%20" in target or target.startswith("%"):
        return False
    return True


def check_broken_links(findings, summary):
    checked = 0
    for f, rel in _authored_md_files():
        text = _read(f)
        if not text:
            continue
        checked += 1
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
            # Only assert resolution for note links; asset links (png, pdf) are
            # out of scope for a content-graph lint.
            if not path_part.lower().endswith(".md") and "." in Path(path_part).name:
                continue
            rel_to_doc = (f.parent / path_part).resolve()
            rel_to_vault = (VAULT_ROOT / path_part).resolve()
            if rel_to_doc.exists() or rel_to_vault.exists():
                continue
            findings.append(
                Finding(
                    "HIGH",
                    "broken-link",
                    f"'{rel}' links to '{target}' which does not resolve.",
                    str(rel),
                )
            )
    summary["files_scanned"] = checked


# ---------- Check C: tag-taxonomy drift ----------

def _load_taxonomy(summary):
    """Read the fenced json block from the taxonomy doc. Returns dict or None."""
    if not TAXONOMY_DOC.exists():
        summary["taxonomy"] = "not found — 07-References/tag-taxonomy.md missing"
        return None
    m = JSON_BLOCK_RE.search(_read(TAXONOMY_DOC))
    if not m:
        summary["taxonomy"] = "no ```json block in tag-taxonomy.md"
        return None
    try:
        tax = json.loads(m.group(1))
    except Exception as e:
        summary["taxonomy"] = f"json parse error ({e})"
        return None
    summary["taxonomy"] = f"v{tax.get('version', '?')}"
    return tax


def _extract_tags(fm: str):
    """Extract tag values from a frontmatter block. Handles both
    `tags: [a, b]` inline and `tags:\\n  - a\\n  - b` block forms."""
    tags = []
    inline = re.search(r"^tags:\s*\[(.*?)\]\s*$", fm, re.MULTILINE | re.DOTALL)
    if inline:
        tags += [t.strip().strip("'\"") for t in inline.group(1).split(",") if t.strip()]
    block = re.search(r"^tags:\s*\n((?:[ \t]*-[ \t]*.+\n?)+)", fm, re.MULTILINE)
    if block:
        tags += [
            t.strip().strip("'\"")
            for t in re.findall(r"-[ \t]*(.+)", block.group(1))
            if t.strip()
        ]
    # `tags: single` scalar form
    scalar = re.search(r"^tags:[ \t]*([^\[\n][^\n]*)$", fm, re.MULTILINE)
    if scalar and not inline:
        v = scalar.group(1).strip().strip("'\"")
        if v:
            tags.append(v)
    return [t for t in tags if t]


def check_tag_drift(findings, summary):
    tax = _load_taxonomy(summary)
    if not tax:
        return
    facets = tax.get("facets", {})
    migrations = tax.get("migrations", {})
    closed_values = {
        name: set(spec.get("values", []))
        for name, spec in facets.items()
        if spec.get("closed")
    }
    open_facets = {name for name, spec in facets.items() if not spec.get("closed")}
    all_facets = set(facets)

    tagged = 0
    for f, rel in _authored_md_files():
        text = _read(f)
        m = FRONTMATTER_RE.search(text)
        if not m:
            continue
        tags = _extract_tags(m.group(1))
        if not tags:
            continue
        tagged += 1
        for tag in tags:
            if "/" not in tag:
                hint = migrations.get(tag)
                suffix = f" → use `{hint}`" if hint else " → namespace it (facet/value)"
                findings.append(
                    Finding(
                        "MEDIUM", "tag-drift",
                        f"`{rel}` bare tag `{tag}`{suffix}", str(rel),
                    )
                )
                continue
            facet, value = tag.split("/", 1)
            if facet not in all_facets:
                findings.append(
                    Finding(
                        "MEDIUM", "tag-drift",
                        f"`{rel}` unknown facet `{facet}/` in tag `{tag}` "
                        f"(facets: {', '.join(sorted(all_facets))})", str(rel),
                    )
                )
            elif facet in closed_values:
                if value not in closed_values[facet]:
                    findings.append(
                        Finding(
                            "MEDIUM", "tag-drift",
                            f"`{rel}` unknown value `{value}` in closed facet "
                            f"`{facet}/` (tag `{tag}`)", str(rel),
                        )
                    )
            elif facet in open_facets:
                if not SLUG_RE.match(value):
                    findings.append(
                        Finding(
                            "LOW", "tag-drift",
                            f"`{rel}` tag `{tag}` value not kebab-case", str(rel),
                        )
                    )
    summary["files_tagged"] = tagged


# ---------- Report ----------

def emit_json(findings, summary):
    print(
        json.dumps(
            {
                "summary": summary,
                "finding_count": len(findings),
                "findings": [f.to_dict() for f in findings],
            },
            indent=2,
        )
    )


def emit_markdown(findings, summary):
    print("# Vault content-graph lint")
    print()
    print(f"- Authored files scanned (links): {summary.get('files_scanned', 0)}")
    print(f"- Files with frontmatter tags: {summary.get('files_tagged', 0)}")
    print(f"- Taxonomy: {summary.get('taxonomy', 'n/a')}")
    print(f"- **Findings: {len(findings)}**")
    print()

    if not findings:
        print("Clean. No broken authored links, no tag drift.")
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
    summary = {}
    check_broken_links(findings, summary)
    check_tag_drift(findings, summary)

    if "--json" in sys.argv:
        emit_json(findings, summary)
    else:
        emit_markdown(findings, summary)
    return 0


if __name__ == "__main__":
    sys.exit(main())
