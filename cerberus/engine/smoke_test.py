"""Smoke test for the Cerberus signature matcher engine.

Runs the engine against in-memory fixtures to verify:

1. The full rule corpus loads cleanly from ``cerberus/rules/packs/``
2. Patterns fire on intentionally vulnerable fixture content
3. Exclude patterns suppress documented false positives
4. Rules load from every vendored pack (core / atr / promptguard)

Usage::

    cd /path/to/Charon
    python -m cerberus.engine.smoke_test

Exit code 0 on pass, 1 on any failure.

This is a SMOKE test only — proper test scenarios under ``test-scenarios/``
land in v0.7 chunk 9.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

from cerberus.engine.signatures import load_all_packs, scan_file
from cerberus.engine.yara_lite import (
    load_all_yara_rules,
    scan_file_yara,
)
from cerberus.engine.file_type import (
    detect_file_type_by_content,
    scan_file_for_magic_mismatch,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
PACKS_DIR = REPO_ROOT / "cerberus" / "rules" / "packs"


# ----------------- Fixtures (inline; real scenarios in chunk 9) -----------------

VULNERABLE_PY = """
# Intentionally vulnerable fixture for the smoke test.
def run(user_input):
    return eval(user_input)
"""

SAFE_PY = """
# Never use eval() — this comment must NOT trigger COMMAND_INJECTION_EVAL.
# Use of eval() is generally avoided in this codebase.
def parse_safe(x: str) -> int:
    return int(x)
"""


# ----------------- Test helpers -----------------

def _write_fixture(content: str, suffix: str) -> Path:
    fd, path_str = tempfile.mkstemp(suffix=suffix)
    path = Path(path_str)
    with open(fd, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def _check(name: str, ok: bool, detail: str = "") -> bool:
    status = "PASS" if ok else "FAIL"
    print(f"  [{status}] {name}" + (f": {detail}" if detail else ""))
    return ok


# ----------------- Tests -----------------

def test_corpus_loads() -> bool:
    """The vendored rule corpus should load cleanly with >= 30 signature rules."""
    rules = load_all_packs(PACKS_DIR)
    return _check(
        "corpus loads",
        len(rules) >= 30,
        f"{len(rules)} signature rules from {PACKS_DIR}",
    )


def test_pack_distribution() -> bool:
    """Rules should be spread across the three vendored packs."""
    rules = load_all_packs(PACKS_DIR)
    packs = {r.pack for r in rules}
    expected = {"core", "atr", "promptguard"}
    return _check(
        "rules load from core + atr + promptguard packs",
        expected.issubset(packs),
        f"found packs: {sorted(packs)}",
    )


def test_eval_pattern_fires() -> bool:
    """COMMAND_INJECTION_EVAL should fire on a vulnerable Python fixture."""
    rules = load_all_packs(PACKS_DIR)
    path = _write_fixture(VULNERABLE_PY, ".py")
    try:
        findings = scan_file(path, rules)
        eval_findings = [f for f in findings if f.rule_id == "COMMAND_INJECTION_EVAL"]
        return _check(
            "COMMAND_INJECTION_EVAL fires on eval(user_input)",
            len(eval_findings) >= 1,
            f"{len(eval_findings)} eval findings, {len(findings)} total",
        )
    finally:
        path.unlink(missing_ok=True)


def test_yara_corpus_loads() -> bool:
    """The vendored YARA corpus should parse cleanly via the pure-Python engine."""
    rules = load_all_yara_rules(PACKS_DIR)
    return _check(
        "YARA corpus loads (no yara-x dep)",
        len(rules) >= 10,
        f"{len(rules)} YARA rules parsed from {PACKS_DIR}",
    )


def test_yara_elf_binary_detection() -> bool:
    """YARA's embedded_elf_binary rule should fire on a file starting with ELF magic."""
    rules = load_all_yara_rules(PACKS_DIR)
    elf_rules = [r for r in rules if r.name == "embedded_elf_binary"]
    if not elf_rules:
        return _check("YARA embedded_elf_binary rule present in corpus", False, "rule not found")
    # Write a tiny ELF-header-prefixed fixture
    fd, path_str = tempfile.mkstemp(suffix=".bin")
    import os
    with open(fd, "wb") as f:
        f.write(b"\x7fELF" + b"\x00" * 60)
    path = Path(path_str)
    try:
        findings = scan_file_yara(path, elf_rules)
        return _check(
            "YARA embedded_elf_binary fires on ELF-prefixed bytes",
            any(f.rule_id == "YARA_embedded_elf_binary" for f in findings),
            f"{len(findings)} findings: {[f.rule_id for f in findings]}",
        )
    finally:
        path.unlink(missing_ok=True)


def test_exclude_suppresses_false_positive() -> bool:
    """Comments about eval should NOT trigger the rule (exclude_pattern)."""
    rules = load_all_packs(PACKS_DIR)
    path = _write_fixture(SAFE_PY, ".py")
    try:
        findings = scan_file(path, rules)
        eval_findings = [f for f in findings if f.rule_id == "COMMAND_INJECTION_EVAL"]
        return _check(
            "comments about eval do NOT fire COMMAND_INJECTION_EVAL",
            len(eval_findings) == 0,
            f"{len(eval_findings)} eval findings (expected 0)",
        )
    finally:
        path.unlink(missing_ok=True)


def test_magic_byte_detection() -> bool:
    """Content-based file-type detection should identify ELF / ZIP / PDF correctly."""
    import os
    cases = [
        (b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 40, ".bin", "ELF magic"),
        (b"PK\x03\x04" + b"\x00" * 40, ".zip", "ZIP magic"),
        (b"%PDF-1.4\n%..." + b"\x00" * 40, ".pdf", "PDF magic"),
    ]
    all_ok = True
    for content, suffix, label in cases:
        fd, path_str = tempfile.mkstemp(suffix=suffix)
        path = Path(path_str)
        try:
            with open(fd, "wb") as f:
                f.write(content)
            ftype = detect_file_type_by_content(path)
            ok = ftype.value == "binary"
            all_ok = all_ok and ok
        finally:
            path.unlink(missing_ok=True)
    return _check("magic-byte detection (ELF / ZIP / PDF -> binary)", all_ok)


def test_magic_mismatch_catches_disguised_binary() -> bool:
    """A .py file with ELF magic bytes should fire FILE_MAGIC_MISMATCH."""
    fd, path_str = tempfile.mkstemp(suffix=".py")
    path = Path(path_str)
    try:
        with open(fd, "wb") as f:
            f.write(b"\x7fELF\x02\x01\x01\x00" + b"\x00" * 40)
        findings = scan_file_for_magic_mismatch(path)
        return _check(
            "FILE_MAGIC_MISMATCH fires on ELF bytes hidden in .py file",
            any(f.rule_id == "FILE_MAGIC_MISMATCH" for f in findings),
            f"{len(findings)} findings; rules: {[f.rule_id for f in findings]}",
        )
    finally:
        path.unlink(missing_ok=True)


def test_magic_mismatch_silent_on_legitimate_text() -> bool:
    """A genuine Python file should NOT fire FILE_MAGIC_MISMATCH."""
    fd, path_str = tempfile.mkstemp(suffix=".py")
    path = Path(path_str)
    try:
        with open(fd, "wb") as f:
            f.write(b"def hello():\n    return 'world'\n")
        findings = scan_file_for_magic_mismatch(path)
        return _check(
            "FILE_MAGIC_MISMATCH silent on legitimate Python content",
            not findings,
            f"{len(findings)} findings (expected 0)",
        )
    finally:
        path.unlink(missing_ok=True)


# ----------------- Runner -----------------

def main() -> int:
    print("Cerberus signature engine — smoke test")
    print(f"  rules at: {PACKS_DIR}")
    print()
    results = [
        test_corpus_loads(),
        test_pack_distribution(),
        test_eval_pattern_fires(),
        test_exclude_suppresses_false_positive(),
        test_yara_corpus_loads(),
        test_yara_elf_binary_detection(),
        test_magic_byte_detection(),
        test_magic_mismatch_catches_disguised_binary(),
        test_magic_mismatch_silent_on_legitimate_text(),
    ]
    print()
    passed = sum(results)
    total = len(results)
    print(f"  {passed}/{total} passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
