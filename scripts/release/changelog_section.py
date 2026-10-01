#!/usr/bin/env python3
"""Print one version's section of CHANGELOG.md -- the body of its GitHub Release.

Why this exists
---------------
Every Charon release is documented in CHANGELOG.md with what was added and why.
GitHub's Releases page is where most people look first, and for 57 tags it was
empty: the notes existed, but not where readers go. This extracts a version's
section verbatim, so the Release page and the CHANGELOG can never disagree --
there is one source, and the page is generated from it.

Usage:
    python scripts/release/changelog_section.py 0.31.0            # print the section
    python scripts/release/changelog_section.py v0.31.0 --check   # exit 1 if missing/empty

Publishing (done as part of every release -- see VERSIONING.md):
    python scripts/release/changelog_section.py vX.Y.Z --out notes.md
    gh release create vX.Y.Z --verify-tag --title "vX.Y.Z" --notes-file notes.md
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parents[2] / "CHANGELOG.md"
HEADING = re.compile(r"^## \[(?P<ver>[^\]]+)\]")


def section(version: str, text: str) -> str:
    """The body under `## [version]`, up to the next `## [` heading. '' if absent."""
    want = version.lstrip("v")
    out, inside = [], False
    for line in text.splitlines():
        m = HEADING.match(line)
        if m:
            if inside:
                break
            inside = m.group("ver") == want
            continue
        if inside:
            out.append(line)
    # The footer compare-links ([x]: https://...) sit after the last section.
    while out and (not out[-1].strip() or re.match(r"^\[[^\]]+\]: https?://", out[-1])):
        out.pop()
    return "\n".join(out).strip("\n")


def main() -> int:
    ap = argparse.ArgumentParser(description="Print a version's CHANGELOG section.")
    ap.add_argument("version", help="e.g. 0.31.0 or v0.31.0")
    ap.add_argument("--check", action="store_true", help="exit 1 if the section is missing or empty")
    ap.add_argument("--out", help="write the notes to this file (UTF-8) instead of stdout")
    args = ap.parse_args()

    body = section(args.version, CHANGELOG.read_text(encoding="utf-8"))
    if args.check:
        return 0 if body.strip() else 1
    if not body.strip():
        print(f"no CHANGELOG section for {args.version}", file=sys.stderr)
        return 1
    data = (body + "\n").encode("utf-8")
    if args.out:
        Path(args.out).write_bytes(data)
    else:
        # Bytes, not text: a Windows console defaults to cp1252, which cannot encode
        # the arrows and ticks the CHANGELOG uses -- printing text crashed on 31 of 57.
        sys.stdout.buffer.write(data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
