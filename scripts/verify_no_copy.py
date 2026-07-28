#!/usr/bin/env python3
"""verify_no_copy.py — clean-room port verifier.

Asserts that a re-authored artifact shares NO verbatim run of >= THRESHOLD
characters with the third-party source it was ported from. This is the
enforcement half of the clean-room porting discipline (see
`.claude/rules/clean-room-port.md`): a recon sub-agent reads the untrusted
source as DATA and emits a structured spec; the main agent re-authors from the
spec; THIS script proves the re-authoring didn't lift source text — protecting
against both prompt-injection contamination and verbatim-copy / licence exposure.

Usage:
    python scripts/verify_no_copy.py --source <src_file_or_dir> \
                                     --target <target_file_or_dir> \
                                     [--threshold 40] [--json]

Exit codes:
    0  PASS  — no shared verbatim run >= threshold
    2  FAIL  — at least one shared run found (details printed)
    1  usage/IO error

Method: whitespace is normalised (runs of whitespace -> single space, trimmed)
so that reformatting can't disguise a lift. Every length-THRESHOLD character
window of every source file is hashed into a set; each target file is then slid
window-by-window and any window present in the source set is reported (with the
offending text and both file paths). Data files intended to be vendored verbatim
under licence (rule corpora, LICENSE/NOTICE) are NOT the target of this check —
run it only against re-authored CODE/PROSE.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_THRESHOLD = 40
# Text-like suffixes we compare; binary/data are skipped.
TEXT_SUFFIXES = {".py", ".mjs", ".js", ".ts", ".sh", ".ps1", ".md", ".txt", ".yaml", ".yml", ".json", ".toml"}


def _normalise(text: str) -> str:
    """Normalise for comparison, dropping lines that would false-positive.

    Import/`from`/`__future__` lines and comment-only lines are shared boilerplate
    between ANY two Python files and are not evidence of copying — they are
    filtered out. Whitespace is then collapsed so reformatting can't disguise a
    lift. Shared API symbol names (e.g. a re-export `__all__` list) may still
    overlap legitimately when a compatible interface is mandated — review such
    hits rather than treating them as copies.
    """
    kept = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith(("import ", "from ", "#")):
            continue
        kept.append(s)
    return " ".join(" ".join(kept).split())


def _iter_files(root: Path):
    if root.is_file():
        yield root
        return
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in TEXT_SUFFIXES:
            yield p


def _windows(s: str, n: int):
    for i in range(0, len(s) - n + 1):
        yield i, s[i : i + n]


def build_source_index(source: Path, n: int) -> set[str]:
    index: set[str] = set()
    for f in _iter_files(source):
        try:
            norm = _normalise(f.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        for _, w in _windows(norm, n):
            index.add(w)
    return index


def scan_target(target: Path, index: set[str], n: int) -> list[dict]:
    findings: list[dict] = []
    for f in _iter_files(target):
        try:
            norm = _normalise(f.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
        seen: set[str] = set()
        for i, w in _windows(norm, n):
            if w in index and w not in seen:
                seen.add(w)
                findings.append({"target_file": str(f), "offset": i, "text": w})
    return findings


def main() -> int:
    ap = argparse.ArgumentParser(description="Clean-room port verifier — no verbatim overlap.")
    ap.add_argument("--source", required=True, help="Third-party source file or dir the port derived from")
    ap.add_argument("--target", required=True, help="Re-authored file or dir to verify")
    ap.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD, help="Min shared run length (chars) that fails")
    ap.add_argument("--json", action="store_true", help="Emit JSON")
    args = ap.parse_args()

    source, target = Path(args.source), Path(args.target)
    if not source.exists() or not target.exists():
        print(f"error: source or target missing ({source} / {target})", file=sys.stderr)
        return 1
    if args.threshold < 8:
        print("error: threshold too small (>=8); short common runs are not evidence of copying", file=sys.stderr)
        return 1

    index = build_source_index(source, args.threshold)
    findings = scan_target(target, index, args.threshold)

    if args.json:
        print(json.dumps({"threshold": args.threshold, "passed": not findings, "findings": findings[:200]}, indent=2))
    else:
        if not findings:
            print(f"PASS — no verbatim run >= {args.threshold} chars shared with source.")
        else:
            print(f"FAIL — {len(findings)} shared run(s) >= {args.threshold} chars:\n")
            for fnd in findings[:50]:
                print(f"  {fnd['target_file']} @ {fnd['offset']}:")
                print(f"    {fnd['text']!r}\n")
            if len(findings) > 50:
                print(f"  … and {len(findings) - 50} more.")
    return 2 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
