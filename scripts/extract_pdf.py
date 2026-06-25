"""extract_pdf.py — PDF text extraction for the vault corpus.

Reads a PDF and writes its text content as a sibling ``.txt`` file (or
to a chosen output path), so the content joins the searchable / graph-
extractable corpus instead of sitting as an opaque binary.

Usage::

    python scripts/extract_pdf.py path/to/file.pdf
    python scripts/extract_pdf.py path/to/file.pdf --out path/to/file.txt
    python scripts/extract_pdf.py path/to/dir --recursive          # walk a directory
    python scripts/extract_pdf.py path/to/dir --recursive --skip-existing

Optional dep: ``pypdf`` via ``requirements-multimodal.txt``.
Without it, the script exits non-zero with a clear install pointer.

Why "borrow from graphify": graphify ingests PDFs as part of its
multimodal corpus build. In a working vault, captured vendor
questionnaires / SOWs / talk-PDFs sit in ``00-Inbox/_captured/`` or
``~/Downloads/`` as opaque files. Extracted text gives the graph + the
LLM something to work with.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Iterable, Optional, Tuple


def pypdf_available() -> Tuple[bool, str]:
    try:
        import pypdf  # noqa: F401
        return True, ""
    except ImportError:
        return False, "pypdf not installed — `pip install -r requirements-multimodal.txt`"


def _configure_stdio_for_unicode() -> None:
    if sys.platform.startswith("win"):
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass


# ---------- Extraction ----------

def extract_pdf_text(path: Path) -> Tuple[Optional[str], str]:
    """Extract text from a PDF. Returns (text, status). status is "ok" or an error message."""
    ok, reason = pypdf_available()
    if not ok:
        return None, reason
    if not path.exists():
        return None, f"file not found: {path}"
    if not path.is_file():
        return None, f"not a file: {path}"

    try:
        import pypdf
        reader = pypdf.PdfReader(str(path))
        pages = []
        for i, page in enumerate(reader.pages):
            try:
                page_text = page.extract_text() or ""
            except Exception as exc:
                page_text = f"[page {i+1} extraction failed: {type(exc).__name__}]"
            pages.append(page_text)
        return "\n\n=== Page Break ===\n\n".join(pages), "ok"
    except Exception as exc:
        return None, f"pypdf error: {type(exc).__name__}: {exc}"


def iter_pdf_files(target: Path, recursive: bool) -> Iterable[Path]:
    if target.is_file():
        yield target
        return
    if not target.is_dir():
        return
    pattern = "**/*.pdf" if recursive else "*.pdf"
    yield from sorted(target.glob(pattern))


# ---------- CLI ----------

def main() -> int:
    _configure_stdio_for_unicode()
    parser = argparse.ArgumentParser(description="Extract text from PDF files into a vault-friendly .txt sibling")
    parser.add_argument("target", help="PDF file OR directory containing PDFs")
    parser.add_argument("--out", type=Path, help="Output path (single-file mode only; default: sibling .txt)")
    parser.add_argument("--recursive", action="store_true", help="When target is a directory, walk it recursively")
    parser.add_argument("--skip-existing", action="store_true", help="Skip files whose .txt sibling already exists")
    parser.add_argument("--stdout", action="store_true", help="Print extracted text to stdout instead of writing to disk (single-file mode only)")
    args = parser.parse_args()

    ok, reason = pypdf_available()
    if not ok:
        sys.stderr.write(f"extract_pdf: {reason}\n")
        return 2

    target = Path(args.target)
    if not target.exists():
        sys.stderr.write(f"target not found: {target}\n")
        return 1

    if target.is_file() and args.stdout:
        text, status = extract_pdf_text(target)
        if text is None:
            sys.stderr.write(f"extraction failed: {status}\n")
            return 1
        sys.stdout.write(text)
        return 0

    pdfs = list(iter_pdf_files(target, recursive=args.recursive))
    if not pdfs:
        sys.stderr.write(f"no PDFs found at {target}\n")
        return 1

    extracted = 0
    skipped = 0
    failed = 0
    for pdf in pdfs:
        out_path = args.out if (args.out and target.is_file()) else pdf.with_suffix(".txt")
        if args.skip_existing and out_path.exists():
            skipped += 1
            continue
        text, status = extract_pdf_text(pdf)
        if text is None:
            sys.stderr.write(f"  FAIL  {pdf.name}: {status}\n")
            failed += 1
            continue
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
        char_count = len(text)
        print(f"  ok    {pdf.name} → {out_path.name}  ({char_count:,} chars)")
        extracted += 1

    print()
    print(f"summary: {extracted} extracted, {skipped} skipped, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
