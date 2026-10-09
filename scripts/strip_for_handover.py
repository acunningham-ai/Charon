#!/usr/bin/env python3
"""strip_for_handover.py - turn an authored vault note into a standalone deliverable.

WHY THIS EXISTS
---------------
Vault notes carry harness lineage: YAML frontmatter naming a recording id,
`[[wikilinks]]` into the memory dir, confidence tags, a "## Related" footer, and
working sections such as a paste-ready email that are for you and nobody else.

None of that belongs in a document handed to a client, a colleague in another
team, a shared site or a board pack. The deliverable should stand alone: sever
the harness lineage, and keep traceability, design rationale and working notes
in the vault, never in the document. Done by hand each time, the stripping is
how a stray `[[feedback_...]]` or a confidence emoji reaches an external reader.
This script makes the check non-optional.

WHAT IT DOES
------------
1. Strips YAML frontmatter (use --keep-frontmatter to retain it).
2. Drops whole sections by heading text (--drop-section, repeatable). A section runs
   from its heading to the next heading of the same or higher level.
3. Rewrites wikilinks: `[[a|b]]` -> `b`. A target that looks like a harness memory
   slug (feedback_/project_/bugs_/reference_/user_) is removed entirely rather than
   humanised, because its humanised form is still lineage.
4. Collapses the blank runs left behind, and trims trailing rules.
5. AUDITS the result for residual lineage and EXITS 1 if any is found, naming the
   line. Failing loudly beats shipping a leak.

   Add your own lineage words (a recorder app, an internal tool or project name)
   with --audit-term, repeatable. They are matched as whole words, case-insensitive.

USAGE
    python scripts/strip_for_handover.py --in note.md --out clean.md \\
        --drop-section "PASTE-READY EMAIL" --drop-section "Related" \\
        --audit-term "MyRecorderApp"

    # then, for a .docx:
    python scripts/md_to_docx.py --in clean.md --out Doc.docx --title "..." ...

The authored note stays the single source of truth - regenerate, never hand-edit
the stripped copy.
"""

from __future__ import annotations

import argparse
import re
import sys

HARNESS_SLUG = re.compile(r"^(?:feedback|project|bugs|reference|user)_[a-z0-9_]+$", re.I)

# Residual-lineage patterns. Each is (label, compiled regex).
AUDIT = [
    ("unresolved wikilink", re.compile(r"\[\[|\]\]")),
    ("harness memory slug", re.compile(r"\b(?:feedback|project|bugs|reference)_[a-z0-9]+_[a-z0-9_]+\b", re.I)),
    ("confidence tag", re.compile(r"[\U0001F7E2\U0001F7E1\U0001F534]")),
    ("harness path", re.compile(r"\.claude[/\\]|scripts[/\\]hooks|CLAUDE\.md|MEMORY\.md|_captured|scratchpad")),
    ("recording id", re.compile(r"\b[0-9a-f]{32}\b")),
    ("vault section ref", re.compile(r"\b0[0-9]-(?:Inbox|Daily|BUs|Domains|People|Meetings|Decisions|References|Projects|Archive)\b")),
]

FRONTMATTER = re.compile(r"\A---\r?\n.*?\r?\n---\r?\n", re.S)
HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
WIKILINK = re.compile(r"\[\[([^\]|]+)(?:\|([^\]]+))?\]\]")


def strip_frontmatter(text: str) -> str:
    return FRONTMATTER.sub("", text, count=1)


def norm_heading(s: str) -> str:
    """Normalise a heading for comparison: drop markdown emphasis, punctuation, case."""
    s = re.sub(r"[*_`]", "", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s.lower())
    return " ".join(s.split())


def drop_sections(lines: list[str], targets: list[str]) -> tuple[list[str], list[str]]:
    """Remove each section whose heading matches a target. Returns (lines, dropped)."""
    wanted = {norm_heading(t) for t in targets}
    out: list[str] = []
    dropped: list[str] = []
    skip_level: int | None = None

    for line in lines:
        m = HEADING.match(line)
        if m:
            level = len(m.group(1))
            title = m.group(2)
            if skip_level is not None and level <= skip_level:
                skip_level = None  # section ended; fall through and consider this heading
            if skip_level is None and norm_heading(title) in wanted:
                skip_level = level
                dropped.append(title)
                continue
        if skip_level is None:
            out.append(line)
    return out, dropped


def rewrite_wikilinks(text: str) -> tuple[str, int]:
    """`[[a|b]]`->`b`; harness slugs removed entirely. Returns (text, removed_count)."""
    removed = 0

    def repl(m: re.Match) -> str:
        nonlocal removed
        target, label = m.group(1), m.group(2)
        if label:
            return label
        if HARNESS_SLUG.match(target.strip()):
            removed += 1
            return ""
        return target.replace("_", " ").replace("-", " ")

    return WIKILINK.sub(repl, text), removed


def tidy(text: str) -> str:
    """Clean up what removal left behind: orphaned separators and blank runs."""
    # A line that is now only separators/whitespace after link removal.
    text = re.sub(r"^[ \t]*[.,;:·•\-–—]+[ \t]*$", "", text, flags=re.M)
    # Leading/trailing separator debris on surviving lines.
    text = re.sub(r"[ \t]*·[ \t]*$", "", text, flags=re.M)
    text = re.sub(r"^[ \t]*·[ \t]*", "", text, flags=re.M)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"(?:\n\s*---\s*)+\Z", "\n", text)
    return text.strip() + "\n"


def audit(text: str, extra_terms: list[str] | None = None) -> list[tuple[int, str, str]]:
    """Return [(lineno, label, line)] for every residual-lineage hit.

    extra_terms are user-supplied lineage words (--audit-term), matched as whole
    words, case-insensitive. They can only ADD checks, never remove a built-in one.
    """
    checks = list(AUDIT)
    for term in extra_terms or []:
        term = term.strip()
        if term:
            checks.append(("custom term", re.compile(r"\b" + re.escape(term) + r"\b", re.I)))
    hits: list[tuple[int, str, str]] = []
    for i, line in enumerate(text.splitlines(), 1):
        for label, rx in checks:
            if rx.search(line):
                hits.append((i, label, line.strip()))
                break
    return hits


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Strip harness lineage from a vault note so it can stand alone."
    )
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", dest="dst", required=True)
    ap.add_argument(
        "--drop-section",
        dest="drop",
        action="append",
        default=[],
        metavar="HEADING",
        help="Heading text of a section to remove entirely. Repeatable.",
    )
    ap.add_argument("--keep-frontmatter", action="store_true")
    ap.add_argument(
        "--audit-term",
        dest="terms",
        action="append",
        default=[],
        metavar="WORD",
        help="Extra lineage word to audit for (e.g. a recorder or internal tool name). Repeatable.",
    )
    ap.add_argument(
        "--allow-residual",
        action="store_true",
        help="Report residual lineage but still write the file (exit 0). Use knowingly.",
    )
    args = ap.parse_args(argv)

    with open(args.src, encoding="utf-8") as fh:
        text = fh.read()

    if not args.keep_frontmatter:
        text = strip_frontmatter(text)

    lines = text.splitlines()
    if args.drop:
        lines, dropped = drop_sections(lines, args.drop)
        for d in dropped:
            print(f"  dropped section: {d}")
        missing = {norm_heading(t) for t in args.drop} - {norm_heading(d) for d in dropped}
        for m in sorted(missing):
            print(f"  WARNING: no section matched --drop-section {m!r}", file=sys.stderr)

    text, removed = rewrite_wikilinks("\n".join(lines))
    if removed:
        print(f"  removed {removed} harness wikilink(s)")
    text = tidy(text)

    hits = audit(text, args.terms)
    if hits:
        print(f"\n  AUDIT FAILED - {len(hits)} residual-lineage line(s):", file=sys.stderr)
        for lineno, label, line in hits[:20]:
            snippet = line[:110] + ("..." if len(line) > 110 else "")
            print(f"    L{lineno} [{label}] {snippet}", file=sys.stderr)
        if len(hits) > 20:
            print(f"    ... and {len(hits) - 20} more", file=sys.stderr)
        if not args.allow_residual:
            print("\n  NOT WRITTEN. Fix the source, or pass --allow-residual.", file=sys.stderr)
            return 1

    with open(args.dst, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)

    status = "with residual lineage" if hits else "clean"
    print(f"  wrote {args.dst} ({len(text.splitlines())} lines, {status})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
