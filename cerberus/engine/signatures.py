"""Cerberus signature matcher — runs YAML pattern rules against scan targets.

The signature YAML schema matches the cisco-ai-defense/skill-scanner format,
so the vendored rule corpus under ``cerberus/rules/packs/*/signatures/*.yaml``
loads directly. Each list-item has fields:

    id              required, unique within the pack
    category        required, e.g. command_injection, data_exfiltration
    severity        required, one of CRITICAL/HIGH/MEDIUM/LOW/INFO
    patterns        required, list of regex strings (compiled re.MULTILINE)
    exclude_patterns optional, list of regex strings — match suppresses finding
    file_types      required, list of file type strings (see FileType)
    description     required, short human-readable description
    remediation     optional, short remediation guidance

This module implements signature rules ONLY. YARA + Magika + homoglyph layers
land in v0.7 chunks 4-6. ``source: python`` corpus rules depend on Cisco's
analyzer framework and are NOT run by this engine (they stay vendored for
future work).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, Iterator, List

import yaml  # PyYAML — already a Charon runtime dep

from cerberus.engine.models import (
    FileType,
    Finding,
    Severity,
    SignatureRule,
)


_REQUIRED_FIELDS = frozenset({
    "id", "category", "severity", "patterns", "file_types", "description"
})

_SKIP_DIR_NAMES = frozenset({
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".tox", ".pytest_cache", ".mypy_cache", ".ruff_cache",
})

_EXTENSION_TO_FILETYPE = {
    ".py":       FileType.PYTHON,
    ".js":       FileType.JAVASCRIPT,
    ".mjs":      FileType.JAVASCRIPT,
    ".cjs":      FileType.JAVASCRIPT,
    ".jsx":      FileType.JAVASCRIPT,
    ".ts":       FileType.TYPESCRIPT,
    ".tsx":      FileType.TYPESCRIPT,
    ".sh":       FileType.BASH,
    ".bash":     FileType.BASH,
    ".md":       FileType.MARKDOWN,
    ".markdown": FileType.MARKDOWN,
    ".yaml":     FileType.YAML,
    ".yml":      FileType.YAML,
    ".json":     FileType.JSON,
}


# ---------- Loaders ----------

def load_all_packs(packs_root: Path) -> List[SignatureRule]:
    """Load signatures from every pack directory under ``packs_root``.

    A pack directory must contain a ``signatures/`` subdirectory with one or
    more YAML files. Directories whose name starts with ``_`` or ``.`` are
    skipped (Python module dirs, dotfiles).
    """
    rules: List[SignatureRule] = []
    if not packs_root.is_dir():
        raise FileNotFoundError(f"packs root not found: {packs_root}")
    for pack_dir in sorted(packs_root.iterdir()):
        if not pack_dir.is_dir():
            continue
        if pack_dir.name.startswith("_") or pack_dir.name.startswith("."):
            continue
        rules.extend(load_pack_signatures(pack_dir))
    return rules


def load_pack_signatures(pack_dir: Path) -> List[SignatureRule]:
    """Load all signature YAML files in a pack's ``signatures/`` subdir.

    Returns an empty list if the pack has no signatures (e.g., a YARA-only pack).
    """
    rules: List[SignatureRule] = []
    sig_dir = pack_dir / "signatures"
    if not sig_dir.exists():
        return rules
    for yaml_file in sorted(sig_dir.glob("*.yaml")):
        with yaml_file.open(encoding="utf-8") as f:
            data = yaml.safe_load(f) or []
        # Accept both top-level shapes:
        #   1. bare list:  [ {id: ..., ...}, ... ]
        #   2. dict wrap:  { signatures: [ {id: ..., ...}, ... ] }  (ATR convention)
        if isinstance(data, dict) and "signatures" in data:
            entries = data["signatures"] or []
        elif isinstance(data, list):
            entries = data
        else:
            raise ValueError(
                f"{yaml_file}: expected a YAML list or a {{signatures: [...]}} mapping, "
                f"got {type(data).__name__}"
            )
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError(
                    f"{yaml_file}: each signature must be a mapping, "
                    f"got {type(entry).__name__}"
                )
            rule = _parse_signature(
                entry, pack=pack_dir.name, source_file=str(yaml_file)
            )
            if rule is not None:
                rules.append(rule)
    return rules


def _parse_signature(entry: dict, *, pack: str, source_file: str):
    """Parse a single signature dict. Returns a ``SignatureRule`` on success,
    or ``None`` if any pattern fails to compile (rule skipped, warning logged).

    Raises ``ValueError`` only on schema-level problems (missing required
    fields, unknown severity / file_type, etc.) — pattern-compile failures
    degrade gracefully so a single bad regex doesn't kill the whole corpus.
    """
    missing = _REQUIRED_FIELDS - entry.keys()
    if missing:
        raise ValueError(
            f"{source_file}: signature {entry.get('id', '?')!r} missing fields: "
            f"{sorted(missing)}"
        )

    rule_id = entry["id"]
    severity = Severity.from_str(entry["severity"])
    file_types = frozenset(FileType.from_str(ft) for ft in entry["file_types"])

    patterns = _compile_pattern_list(
        entry["patterns"], rule_id=rule_id, source_file=source_file,
    )
    if patterns is None:
        return None  # at least one pattern uncompilable — skip the whole rule

    exclude_patterns = _compile_pattern_list(
        entry.get("exclude_patterns", []) or [],
        rule_id=rule_id,
        source_file=source_file,
    ) or ()

    return SignatureRule(
        id=rule_id,
        category=entry["category"],
        severity=severity,
        patterns=patterns,
        exclude_patterns=exclude_patterns,
        file_types=file_types,
        description=entry["description"],
        remediation=entry.get("remediation"),
        pack=pack,
        source_file=source_file,
    )


_WARNED_RULES: set = set()  # module-level dedupe for skip warnings


def _compile_pattern_list(patterns, *, rule_id: str, source_file: str):
    """Compile each pattern; return tuple on success, or ``None`` if any fail.

    Failures are logged to stderr ONCE per ``(rule_id, source_file)`` pair so
    repeated ``load_all_packs`` calls don't spam diagnostics.
    """
    compiled = []
    for p in patterns:
        translated = _translate_pcre_escapes(p)
        try:
            compiled.append(re.compile(translated, re.MULTILINE))
        except re.error as exc:
            key = (rule_id, source_file)
            if key not in _WARNED_RULES:
                _WARNED_RULES.add(key)
                import sys
                sys.stderr.write(
                    f"  WARN cerberus.engine: skipping rule {rule_id!r} in "
                    f"{source_file}: uncompilable regex {p!r}: {exc}\n"
                )
            return None
    return tuple(compiled)


# PCRE-style Unicode escape pattern: \u{HEX} → Python \uXXXX or \UXXXXXXXX
_PCRE_UNICODE_ESCAPE = re.compile(r"\\u\{([0-9a-fA-F]+)\}")


def _translate_pcre_escapes(pattern: str) -> str:
    """Translate PCRE ``\\u{HEX}`` Unicode escapes to Python re's syntax.

    Cisco's ATR signature YAMLs use ``\\u{E0000}`` style escapes (PCRE
    extended unicode form). Python's ``re`` requires ``\\uXXXX`` for BMP
    code points and ``\\UXXXXXXXX`` for supplementary planes. This helper
    rewrites at compile time so the vendored corpus loads unchanged.
    """
    def _replace(match: re.Match) -> str:
        codepoint = int(match.group(1), 16)
        if codepoint <= 0xFFFF:
            return f"\\u{codepoint:04x}"
        return f"\\U{codepoint:08x}"
    return _PCRE_UNICODE_ESCAPE.sub(_replace, pattern)


# ---------- File-type detection (Magika upgrade lands in chunk 5) ----------

def detect_file_type(path: Path) -> FileType:
    """Detect file type from extension. Magika upgrade lands in v0.7 chunk 5."""
    return _EXTENSION_TO_FILETYPE.get(path.suffix.lower(), FileType.OTHER)


# ---------- Scanners ----------

def scan_file(path: Path, rules: Iterable[SignatureRule]) -> List[Finding]:
    """Apply all applicable rules to a single file.

    Returns an empty list if the file can't be read (binary, permission, etc.).
    """
    rules = list(rules)
    file_type = detect_file_type(path)
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return list(_match_rules(text, path, file_type, rules))


def scan_path(target: Path, rules: Iterable[SignatureRule]) -> List[Finding]:
    """Recursively scan a directory tree, or a single file.

    Skips well-known noise directories (``.git``, ``__pycache__``, etc.).
    """
    rules = list(rules)
    if target.is_file():
        return scan_file(target, rules)
    if not target.is_dir():
        raise FileNotFoundError(f"target not found: {target}")
    findings: List[Finding] = []
    for child in sorted(target.rglob("*")):
        if child.is_file() and not _should_skip(child):
            findings.extend(scan_file(child, rules))
    return findings


def _should_skip(path: Path) -> bool:
    """Skip noise dirs that are never scan-worthy."""
    return bool(_SKIP_DIR_NAMES & set(path.parts))


# ---------- Matching ----------

def _match_rules(
    text: str,
    path: Path,
    file_type: FileType,
    rules: Iterable[SignatureRule],
) -> Iterator[Finding]:
    """Match all applicable rules against the text. Yields Findings.

    Routing logic: a rule fires if its ``file_types`` includes the detected
    ``file_type`` for this file OR if it includes ``FileType.TEXT`` (a
    "match-any-text-file" wildcard used by broad ATR-style rules).
    """
    for rule in rules:
        if file_type not in rule.file_types and FileType.TEXT not in rule.file_types:
            continue
        for pattern in rule.patterns:
            for m in pattern.finditer(text):
                if _is_excluded(text, m, rule):
                    continue
                line_no = text.count("\n", 0, m.start()) + 1
                yield Finding(
                    rule_id=rule.id,
                    pack=rule.pack,
                    category=rule.category,
                    severity=rule.severity,
                    path=str(path),
                    line=line_no,
                    matched_text=m.group(0),
                    description=rule.description,
                    remediation=rule.remediation,
                )


def _is_excluded(text: str, match: re.Match, rule: SignatureRule) -> bool:
    """Check ``exclude_patterns`` against (a) the matched text and
    (b) the full line containing the match. Either firing suppresses."""
    if not rule.exclude_patterns:
        return False

    matched_text = match.group(0)
    if any(ex.search(matched_text) for ex in rule.exclude_patterns):
        return True

    line_start = text.rfind("\n", 0, match.start()) + 1
    line_end = text.find("\n", match.end())
    if line_end == -1:
        line_end = len(text)
    line = text[line_start:line_end]
    return any(ex.search(line) for ex in rule.exclude_patterns)
