"""File-type detection via magic-byte signatures — V3 layer.

Charon-native, dep-free. Reads the first N bytes of a file and classifies
by well-known magic-byte signatures. Compares against extension-based
detection (from signatures.py) and emits a FILE_MAGIC_MISMATCH finding
when the two disagree — catches disguised executables, archives renamed
to .txt, etc.

Magic-byte tables based on canonical file-format signatures. Covers
~30 commonly-encountered types in skill-scanning contexts. Magika
(Google's deep-learning detector) would give 200+ types at ~99% via a
~30MB neural model — we trade breadth for zero deps per
feedback_charon_dep_aversion.

The FILE_MAGIC_MISMATCH rule mirrors the same-named rule in Cisco's
upstream corpus. Charon-authored — lives in the `charon` pack alongside
future native rules.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional, Tuple

from cerberus.engine.models import FileType, Finding, Severity


# Bytes to read from each file for magic-byte detection
_READ_BYTES = 256

# Magic-byte signatures. (prefix_bytes, FileType). Order matters —
# first match wins, so longer / more-specific prefixes come first.
_MAGIC_BYTES: List[Tuple[bytes, FileType]] = [
    # --- Executables ---
    (b"\x7fELF",                       FileType.BINARY),   # ELF (Linux/Unix)
    (b"\xfe\xed\xfa\xce",              FileType.BINARY),   # Mach-O 32-bit
    (b"\xfe\xed\xfa\xcf",              FileType.BINARY),   # Mach-O 64-bit
    (b"\xce\xfa\xed\xfe",              FileType.BINARY),   # Mach-O 32-bit reverse
    (b"\xcf\xfa\xed\xfe",              FileType.BINARY),   # Mach-O 64-bit reverse
    (b"\xca\xfe\xba\xbe",              FileType.BINARY),   # Mach-O fat / Java class
    (b"MZ",                            FileType.BINARY),   # DOS/Windows PE (.exe/.dll)

    # --- Archives ---
    (b"PK\x03\x04",                    FileType.BINARY),   # ZIP / JAR / DOCX / XLSX
    (b"PK\x05\x06",                    FileType.BINARY),   # ZIP empty archive
    (b"PK\x07\x08",                    FileType.BINARY),   # ZIP spanned
    (b"\x1f\x8b\x08",                  FileType.BINARY),   # GZIP
    (b"BZh",                           FileType.BINARY),   # BZ2
    (b"\xfd7zXZ\x00",                  FileType.BINARY),   # XZ
    (b"7z\xbc\xaf\x27\x1c",            FileType.BINARY),   # 7zip
    (b"Rar!\x1a\x07",                  FileType.BINARY),   # RAR v1.5+
    (b"ustar",                         FileType.BINARY),   # TAR (USTAR offset 257; here as best-effort header)

    # --- Documents ---
    (b"%PDF",                          FileType.BINARY),   # PDF
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", FileType.BINARY),# MS Office OLE (legacy DOC/XLS/PPT)

    # --- Images ---
    (b"\x89PNG\r\n\x1a\n",             FileType.BINARY),   # PNG
    (b"\xff\xd8\xff",                  FileType.BINARY),   # JPEG (any subtype)
    (b"GIF87a",                        FileType.BINARY),   # GIF87a
    (b"GIF89a",                        FileType.BINARY),   # GIF89a
    (b"BM",                            FileType.BINARY),   # BMP
    (b"II*\x00",                       FileType.BINARY),   # TIFF little-endian
    (b"MM\x00*",                       FileType.BINARY),   # TIFF big-endian
    (b"RIFF",                          FileType.BINARY),   # RIFF (WAV/WebP/AVI — broad)

    # --- Scripts (shebang detection — gives a stronger signal than extension) ---
    (b"#!/bin/bash",                   FileType.BASH),
    (b"#!/usr/bin/env bash",           FileType.BASH),
    (b"#!/bin/sh",                     FileType.BASH),
    (b"#!/bin/zsh",                    FileType.BASH),
    (b"#!/usr/bin/env zsh",            FileType.BASH),
    (b"#!/usr/bin/env python",         FileType.PYTHON),
    (b"#!/usr/bin/python",             FileType.PYTHON),
    (b"#!/usr/bin/env node",           FileType.JAVASCRIPT),
    (b"#!/usr/bin/env ruby",           FileType.OTHER),    # Ruby — no FileType.RUBY today

    # --- Structured text (loose markers; full check happens in _looks_text) ---
    (b"<?xml",                         FileType.TEXT),
    (b"---\n",                         FileType.YAML),     # YAML frontmatter
    (b"---\r\n",                       FileType.YAML),
    (b"<!DOCTYPE html",                FileType.TEXT),
    (b"<html",                         FileType.TEXT),
]


# ---------- Content-based detection ----------

def detect_file_type_by_content(path: Path) -> FileType:
    """Identify file type by reading the first 256 bytes and matching magic bytes.

    Falls back to `TEXT` if the head decodes cleanly as UTF-8, `BINARY` if not,
    `OTHER` on read failure.
    """
    try:
        with path.open("rb") as f:
            head = f.read(_READ_BYTES)
    except OSError:
        return FileType.OTHER

    if not head:
        return FileType.OTHER

    for prefix, ftype in _MAGIC_BYTES:
        if head.startswith(prefix):
            return ftype

    # No magic match — heuristic on whether it looks like text
    if _looks_text(head):
        return FileType.TEXT
    return FileType.BINARY


def _looks_text(head: bytes) -> bool:
    """True if the head decodes as UTF-8 AND has few control bytes.

    Catches the common "rename a binary to .txt" pattern: a true text file
    has very few control bytes; a binary disguised as text fails the UTF-8
    decode OR is full of nulls / control characters.
    """
    try:
        head.decode("utf-8")
    except UnicodeDecodeError:
        return False
    # Count control bytes (excluding tab / LF / CR which are normal in text)
    control_byte_count = sum(
        1 for b in head if b < 0x20 and b not in (0x09, 0x0a, 0x0d)
    )
    # Heuristic threshold: if more than 5% of the head is unexpected control bytes,
    # it's almost certainly not plain text.
    return control_byte_count / max(len(head), 1) < 0.05


# ---------- V3 sub-check: extension vs content mismatch ----------

def check_magic_mismatch(path: Path) -> Optional[Finding]:
    """Emit a FILE_MAGIC_MISMATCH finding when extension and content disagree."""
    from cerberus.engine.signatures import detect_file_type as detect_by_ext

    by_ext = detect_by_ext(path)
    by_content = detect_file_type_by_content(path)

    # No-info extension is not a mismatch — caller has no signal to compare against
    if by_ext == FileType.OTHER:
        return None

    if _types_compatible(by_ext, by_content):
        return None

    return Finding(
        rule_id="FILE_MAGIC_MISMATCH",
        pack="charon",
        category="obfuscation",
        severity=Severity.HIGH,
        path=str(path),
        line=1,
        matched_text=f"ext={by_ext.value} vs content={by_content.value}",
        description=(
            f"File extension suggests {by_ext.value} but the content magic bytes "
            f"indicate {by_content.value} — possible disguised executable / archive / "
            f"renamed binary."
        ),
        remediation=(
            "Investigate why the file content doesn't match its extension. Common "
            "causes: renamed executable hidden under a benign extension, archive "
            "extracted with the wrong tool, or a corrupt file."
        ),
    )


def _types_compatible(by_ext: FileType, by_content: FileType) -> bool:
    """Return True if extension-detected and content-detected types are compatible."""
    if by_ext == by_content:
        return True

    # Source-code extensions all share the TEXT supertype as far as content goes
    text_extension_types = {
        FileType.PYTHON, FileType.JAVASCRIPT, FileType.TYPESCRIPT,
        FileType.BASH, FileType.MARKDOWN, FileType.YAML, FileType.JSON,
        FileType.MANIFEST,
    }
    if by_ext in text_extension_types:
        # Content TEXT is compatible
        if by_content == FileType.TEXT:
            return True
        # Content OTHER (no magic matched + small file) — assume benign
        if by_content == FileType.OTHER:
            return True
        # Shebang scripts: bash detected from shebang inside a .py file is OK
        # because the extension says "scripty"
        if by_content == FileType.BASH and by_ext == FileType.BASH:
            return True
        # Python shebang ok in .py
        if by_content == FileType.PYTHON and by_ext == FileType.PYTHON:
            return True

    # YAML extension can match either YAML magic or generic TEXT
    if by_ext == FileType.YAML and by_content in (FileType.TEXT, FileType.OTHER):
        return True

    return False


def scan_file_for_magic_mismatch(path: Path) -> List[Finding]:
    """Public wrapper — returns the list (possibly empty) of magic-mismatch findings."""
    f = check_magic_mismatch(path)
    return [f] if f else []
