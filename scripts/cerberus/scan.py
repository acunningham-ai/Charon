"""Cerberus engine scan driver — runs all layered detection against a target.

Layered detection:
  - Signature engine (YAML pattern rules from the vendored Cisco corpus)
  - YARA engine (pure-Python YARA-subset interpreter, vendored Cisco corpus)
  - Magic-byte file-type check (Charon-native, FILE_MAGIC_MISMATCH rule)
  - Unicode homoglyph check (Charon-native, HOMOGLYPH_DETECTED rule)

Usage::

    python -m scripts.cerberus.scan <target> [--format text|json|sarif] \\
                                   [--out PATH] [--no-yara] [--no-magic] \\
                                   [--no-homoglyph]

When no ``--out`` is given, JSON / SARIF are written to stdout. Text format
always goes to stdout.

This driver is what the vet-external-skill skill invokes during a
``/cerberus-vet <repo-url>`` flow — runs the engine over the cloned sandbox
and folds findings into the V0-V8 narrative verdict.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Iterable, List

from cerberus.engine.file_type import scan_file_for_magic_mismatch
from cerberus.engine.homoglyph import scan_file_for_homoglyphs
from cerberus.engine.models import Finding, Severity
from cerberus.engine.sarif import findings_to_sarif
from cerberus.engine.signatures import load_all_packs, scan_path
from cerberus.engine.yara_lite import load_all_yara_rules, scan_file_yara


_REPO_ROOT = Path(__file__).resolve().parents[2]
_PACKS_DIR = _REPO_ROOT / "cerberus" / "rules" / "packs"

# Directories never worth scanning
_SKIP_DIRS = frozenset({
    ".git", "__pycache__", "node_modules", ".venv", "venv",
    ".tox", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".cache",
})


def _configure_stdio_for_unicode() -> None:
    """Force UTF-8 on Windows so emoji / homoglyph output doesn't crash cp1252."""
    if sys.platform.startswith("win"):
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass


def _iter_scannable_files(target: Path) -> Iterable[Path]:
    """Yield every file under ``target`` not in a skip dir."""
    if target.is_file():
        yield target
        return
    for path in sorted(target.rglob("*")):
        if not path.is_file():
            continue
        if _SKIP_DIRS & set(path.parts):
            continue
        yield path


def run_scan(
    target: Path,
    *,
    run_signatures: bool = True,
    run_yara: bool = True,
    run_magic: bool = True,
    run_homoglyph: bool = True,
) -> List[Finding]:
    """Run all enabled engine layers against the target and return Findings."""
    findings: List[Finding] = []

    if run_signatures:
        signature_rules = load_all_packs(_PACKS_DIR)
        findings.extend(scan_path(target, signature_rules))

    if run_yara:
        yara_rules = load_all_yara_rules(_PACKS_DIR)
        for f in _iter_scannable_files(target):
            findings.extend(scan_file_yara(f, yara_rules))

    if run_magic:
        for f in _iter_scannable_files(target):
            findings.extend(scan_file_for_magic_mismatch(f))

    if run_homoglyph:
        for f in _iter_scannable_files(target):
            findings.extend(scan_file_for_homoglyphs(f))

    return findings


# ---------- Output formatting ----------

def format_text(findings: List[Finding], target: Path) -> str:
    """Human-readable text summary of findings, grouped by severity."""
    lines: List[str] = []
    lines.append(f"Cerberus scan — {target}")
    lines.append(f"  {len(findings)} finding(s)")
    lines.append("")
    if not findings:
        lines.append("  No findings.")
        return "\n".join(lines)

    by_sev: dict = {}
    for f in findings:
        by_sev.setdefault(f.severity, []).append(f)

    sev_order = [Severity.CRITICAL, Severity.HIGH, Severity.MEDIUM, Severity.LOW, Severity.INFO]
    for sev in sev_order:
        items = by_sev.get(sev, [])
        if not items:
            continue
        lines.append(f"--- {sev.value.upper()} ({len(items)}) ---")
        for f in items:
            lines.append(f"  [{f.pack}/{f.rule_id}] {f.path}:{f.line}")
            lines.append(f"    {f.description}")
            if f.matched_text:
                snippet = f.matched_text[:120].replace("\n", " ")
                lines.append(f"    matched: {snippet!r}")
        lines.append("")
    return "\n".join(lines)


def format_json(findings: List[Finding], target: Path) -> str:
    """Cerberus-native JSON envelope."""
    return json.dumps({
        "target": str(target),
        "tool": "cerberus",
        "version": "0.7.0",
        "finding_count": len(findings),
        "findings": [
            {
                "rule_id":     f.rule_id,
                "pack":        f.pack,
                "category":    f.category,
                "severity":    f.severity.value,
                "path":        f.path,
                "line":        f.line,
                "matched_text": f.matched_text,
                "description": f.description,
                "remediation": f.remediation,
            }
            for f in findings
        ],
    }, indent=2)


def format_sarif(findings: List[Finding], target: Path) -> str:
    """SARIF 2.1.0 JSON for CI consumers (GitHub Code Scanning, etc.)."""
    target_uri = target.resolve().as_uri() if target.exists() else None
    base_uri = (target_uri + "/") if target_uri and not target_uri.endswith("/") else target_uri
    sarif = findings_to_sarif(findings, base_uri=base_uri)
    return json.dumps(sarif, indent=2)


# ---------- CLI ----------

def main() -> int:
    _configure_stdio_for_unicode()
    p = argparse.ArgumentParser(description="Cerberus engine scan — run layered detection on a target")
    p.add_argument("target", help="File or directory to scan")
    p.add_argument("--format", choices=["text", "json", "sarif"], default="text",
                   help="Output format (default: text)")
    p.add_argument("--out", type=Path, help="Write output to this file (default: stdout)")
    p.add_argument("--no-signatures", action="store_true", help="Skip signature engine")
    p.add_argument("--no-yara", action="store_true", help="Skip YARA engine")
    p.add_argument("--no-magic", action="store_true", help="Skip magic-byte file-type check")
    p.add_argument("--no-homoglyph", action="store_true", help="Skip homoglyph detection")
    args = p.parse_args()

    target = Path(args.target).resolve()
    if not target.exists():
        sys.stderr.write(f"target not found: {target}\n")
        return 1

    findings = run_scan(
        target,
        run_signatures=not args.no_signatures,
        run_yara=not args.no_yara,
        run_magic=not args.no_magic,
        run_homoglyph=not args.no_homoglyph,
    )

    formatter = {"text": format_text, "json": format_json, "sarif": format_sarif}[args.format]
    output = formatter(findings, target)

    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(output, encoding="utf-8")
        sys.stderr.write(f"wrote {args.format} output to {args.out}\n")
    else:
        sys.stdout.write(output + "\n")

    # Exit-code convention: 0 = clean, 1 = findings present, 2 = error
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main())
