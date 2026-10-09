#!/usr/bin/env python3
"""md_to_docx.py - render an authored vault markdown doc as a clean, styled .docx.

WHY THIS EXISTS
---------------
Not everyone you hand a document to reads markdown. A one-off conversion done by
a throwaway script leaves no reusable artefact, so the next "can I have this as a
Word doc?" has to be reverse-engineered from the last output. This is the
reusable converter: python-docx only, no Word, no pandoc.

HOUSE STYLE (a neutral default; change the constants below to suit)
- Page: US Letter (python-docx default)
- Margins: 0.9in left/right, 0.8in top/bottom
- Body: Calibri 10.5pt (the Normal style)
- Cover (all centred): title 34pt bold navy / subtitle 17pt grey /
  entity 19pt bold red / meta lines 10.5pt grey / marker note 10pt grey
- Heading 1 recoloured navy (Word's default blue reads too bright next to the cover)
- Tables: "Light Grid Accent 1", header row bold
- Fill-in markers rendered bold red so they are impossible to miss on paper
- A real TOC field (right-click > Update Field in Word)

USAGE
    python scripts/md_to_docx.py --in <file.md> --out <file.docx> \\
        --title "Incident Response Plan" --subtitle "Head Office" \\
        --entity "EXAMPLE ORGANISATION" \\
        --classification "Classification: Internal" \\
        --marker-note "Fields shown in red are unresolved and require a decision."

    # marker regex defaults to the [CONFIRM ...] / [TO POPULATE ...] family
    --marker-regex '\\[(?:CONFIRM|TO POPULATE|[A-Z]+ TO POPULATE)[^\\]]*\\]'

SCOPE / LIMITS
- Deliberately a *presentation* converter, not a markdown engine. It handles what
  authored vault docs actually use: ATX headings, GFM pipe tables, - bullets
  (one nest level), 1. numbered lists, > blockquotes, --- rules, and inline
  **bold** / *italic* / `code` / marker spans.
- Hard-wrapped source lines are joined into single paragraphs (the vault wraps ~100 cols).
- YAML frontmatter is stripped. A leading H1 is dropped when it duplicates the cover title.
- Not handled (add if a doc needs it): images, footnotes, nested tables, task lists,
  reference links, HTML blocks.
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    from docx import Document
    from docx.enum.section import WD_SECTION
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Inches, Pt, RGBColor
except ImportError:  # pragma: no cover
    sys.exit("python-docx is required:  pip install python-docx")

# ---------------------------------------------------------------- house style
NAVY = RGBColor(0x1F, 0x30, 0x50)
GREY = RGBColor(0x59, 0x59, 0x59)
RED = RGBColor(0xB7, 0x00, 0x11)

BODY_FONT = "Calibri"
BODY_PT = 10.5
TABLE_STYLE = "Light Grid Accent 1"

DEFAULT_MARKER = r"\[(?:CONFIRM|TO POPULATE|[A-Z]+ TO POPULATE)[^\]]*\]"

# ---------------------------------------------------------------- inline text
# Split on marker / bold / italic / code, keeping the delimiters.
_INLINE = re.compile(
    r"(\*\*.+?\*\*"          # bold
    r"|(?<!\*)\*[^*\n]+?\*"  # italic (single asterisk, not part of **)
    r"|`[^`\n]+?`)"          # inline code
)


def add_inline(paragraph, text: str, marker_re: re.Pattern | None, base_bold=False):
    """Append `text` to `paragraph`, honouring bold/italic/code/marker spans."""
    # Markers win over everything else, and may sit inside backticks in source.
    if marker_re:
        pieces = []
        pos = 0
        for m in marker_re.finditer(text):
            pieces.append(("plain", text[pos:m.start()]))
            pieces.append(("marker", m.group(0)))
            pos = m.end()
        pieces.append(("plain", text[pos:]))
    else:
        pieces = [("plain", text)]

    for kind, chunk in pieces:
        if not chunk:
            continue
        if kind == "marker":
            run = paragraph.add_run(chunk)
            run.bold = True
            run.font.color.rgb = RED
            continue
        # strip stray backticks that hugged a marker, e.g. `[CONFIRM]`
        for part in _INLINE.split(chunk):
            if not part:
                continue
            if part.startswith("**") and part.endswith("**") and len(part) > 4:
                run = paragraph.add_run(part[2:-2])
                run.bold = True
            elif part.startswith("`") and part.endswith("`") and len(part) > 2:
                run = paragraph.add_run(part[1:-1])
                run.font.name = "Consolas"
                run.font.size = Pt(BODY_PT - 0.5)
            elif (
                part.startswith("*")
                and part.endswith("*")
                and len(part) > 2
                and not part.startswith("**")
            ):
                run = paragraph.add_run(part[1:-1])
                run.italic = True
            else:
                run = paragraph.add_run(part.replace("`", ""))
            if base_bold:
                run.bold = True


# ---------------------------------------------------------------- doc scaffold
def strip_frontmatter(text: str) -> str:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            return text[text.find("\n", end + 1) + 1:]
    return text


def build_document() -> Document:
    doc = Document()
    sec = doc.sections[0]
    sec.left_margin = sec.right_margin = Inches(0.9)
    sec.top_margin = sec.bottom_margin = Inches(0.8)

    normal = doc.styles["Normal"]
    normal.font.name = BODY_FONT
    normal.font.size = Pt(BODY_PT)

    # Word's default Heading 1 blue clashes with the navy cover.
    for name, colour in (("Heading 1", NAVY), ("Heading 2", NAVY)):
        try:
            doc.styles[name].font.color.rgb = colour
        except KeyError:
            pass
    return doc


def add_cover(doc, title, subtitle, entity, meta_lines, marker_note):
    def centred(text, size, colour, bold=False):
        p = doc.add_paragraph()
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        r = p.add_run(text)
        r.font.size = Pt(size)
        r.font.color.rgb = colour
        r.bold = bold
        return p

    doc.add_paragraph()
    centred(title, 34, NAVY, bold=True)
    if subtitle:
        centred(subtitle, 17, GREY)
    if entity:
        centred(entity, 19, RED, bold=True)
    for line in meta_lines:
        centred(line, BODY_PT, GREY)
    if marker_note:
        doc.add_paragraph()
        centred(marker_note, 10, GREY)


def add_toc(doc):
    doc.add_page_break()
    doc.add_heading("Contents", level=1)
    p = doc.add_paragraph()
    fld = OxmlElement("w:fldSimple")
    fld.set(qn("w:instr"), r'TOC \o "1-3" \h \z \u')
    hint = OxmlElement("w:r")
    t = OxmlElement("w:t")
    t.text = "Right-click here and choose 'Update Field' to build the contents."
    hint.append(t)
    fld.append(hint)
    p._p.append(fld)
    doc.add_page_break()


# ---------------------------------------------------------------- md -> docx
def is_table_row(line: str) -> bool:
    return line.lstrip().startswith("|") and line.count("|") >= 2


def split_row(line: str):
    cells = line.strip().strip("|").split("|")
    return [c.strip() for c in cells]


def is_separator(line: str) -> bool:
    return bool(re.fullmatch(r"\s*\|?[\s:|-]+\|?\s*", line)) and "-" in line


def render(md: str, doc, marker_re):
    lines = strip_frontmatter(md).splitlines()
    i = 0
    dropped_first_h1 = False
    para_buf: list[str] = []
    buf_kind = None  # None | 'p' | 'quote'

    def flush():
        nonlocal para_buf, buf_kind
        if not para_buf:
            buf_kind = None
            return
        text = " ".join(s.strip() for s in para_buf).strip()
        para_buf = []
        if not text:
            buf_kind = None
            return
        p = doc.add_paragraph()
        if buf_kind == "quote":
            p.paragraph_format.left_indent = Inches(0.25)
        add_inline(p, text, marker_re)
        buf_kind = None

    while i < len(lines):
        raw = lines[i]
        line = raw.rstrip()
        stripped = line.strip()

        # blank -> paragraph break
        if not stripped:
            flush()
            i += 1
            continue

        # horizontal rule -> ignore (visual separator only)
        if re.fullmatch(r"-{3,}|\*{3,}|_{3,}", stripped):
            flush()
            i += 1
            continue

        # HTML comment line -> skip
        if stripped.startswith("<!--"):
            flush()
            i += 1
            continue

        # heading
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            flush()
            level, text = len(m.group(1)), m.group(2).strip()
            if level == 1 and not dropped_first_h1:
                dropped_first_h1 = True  # cover already carries the title
                i += 1
                continue
            h = doc.add_heading(level=min(level, 4))
            add_inline(h, text, marker_re)
            i += 1
            continue

        # table
        if is_table_row(line):
            flush()
            block = []
            while i < len(lines) and is_table_row(lines[i]):
                block.append(lines[i])
                i += 1
            rows = [split_row(b) for b in block if not is_separator(b)]
            if rows:
                ncols = max(len(r) for r in rows)
                table = doc.add_table(rows=0, cols=ncols)
                try:
                    table.style = TABLE_STYLE
                except KeyError:
                    table.style = "Table Grid"
                for ri, row in enumerate(rows):
                    cells = table.add_row().cells
                    for ci in range(ncols):
                        txt = row[ci] if ci < len(row) else ""
                        cell = cells[ci]
                        cell.text = ""
                        add_inline(
                            cell.paragraphs[0],
                            txt.replace("<br>", " "),
                            marker_re,
                            base_bold=(ri == 0),
                        )
                doc.add_paragraph()
            continue

        # blockquote
        if stripped.startswith(">"):
            content = re.sub(r"^>\s?", "", stripped)
            if re.match(r"^[-*]\s+", content) or re.match(r"^\d+\.\s+", content):
                flush()
                text = re.sub(r"^(?:[-*]|\d+\.)\s+", "", content)
                p = doc.add_paragraph(style="List Bullet")
                p.paragraph_format.left_indent = Inches(0.5)
                # A quoted list item is usually hard-wrapped across several
                # '>' lines. Absorb the continuations, or the item splits into a
                # bullet plus an orphan paragraph (seen on a real IR plan export).
                i += 1
                cont = []
                while i < len(lines):
                    nxt = lines[i].strip()
                    if not nxt.startswith(">"):
                        break
                    nxt_body = re.sub(r"^>\s?", "", nxt)
                    if not nxt_body.strip():
                        break
                    if re.match(r"^(?:[-*]|\d+\.)\s+", nxt_body):
                        break
                    cont.append(nxt_body.strip())
                    i += 1
                add_inline(p, " ".join([text] + cont), marker_re)
                continue
            elif not content.strip():
                flush()
            else:
                if buf_kind not in (None, "quote"):
                    flush()
                buf_kind = "quote"
                para_buf.append(content)
            i += 1
            continue

        # bullets (one nest level)
        m = re.match(r"^(\s*)[-*]\s+(.*)$", line)
        if m:
            flush()
            indent, text = len(m.group(1)), m.group(2)
            style = "List Bullet 2" if indent >= 2 else "List Bullet"
            try:
                p = doc.add_paragraph(style=style)
            except KeyError:
                p = doc.add_paragraph(style="List Bullet")
            # absorb continuation lines of this bullet
            i += 1
            cont = []
            while i < len(lines):
                nxt = lines[i]
                if not nxt.strip():
                    break
                if re.match(r"^\s*(?:[-*]|\d+\.)\s+", nxt) or nxt.lstrip().startswith(("#", "|", ">")):
                    break
                cont.append(nxt.strip())
                i += 1
            add_inline(p, " ".join([text] + cont), marker_re)
            continue

        # numbered list
        m = re.match(r"^(\s*)\d+\.\s+(.*)$", line)
        if m:
            flush()
            p = doc.add_paragraph(style="List Number")
            i += 1
            cont = []
            while i < len(lines):
                nxt = lines[i]
                if not nxt.strip():
                    break
                if re.match(r"^\s*(?:[-*]|\d+\.)\s+", nxt) or nxt.lstrip().startswith(("#", "|", ">")):
                    break
                cont.append(nxt.strip())
                i += 1
            add_inline(p, " ".join([m.group(2)] + cont), marker_re)
            continue

        # plain paragraph line (hard-wrapped)
        if buf_kind not in (None, "p"):
            flush()
        buf_kind = "p"
        para_buf.append(stripped)
        i += 1

    flush()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="src", required=True)
    ap.add_argument("--out", dest="dst", required=True)
    ap.add_argument("--title", default="")
    ap.add_argument("--subtitle", default="")
    ap.add_argument("--entity", default="")
    ap.add_argument("--meta", action="append", default=[], help="extra centred cover line (repeatable)")
    ap.add_argument("--classification", default="")
    ap.add_argument("--marker-note", default="")
    ap.add_argument("--marker-regex", default=DEFAULT_MARKER)
    ap.add_argument("--no-toc", action="store_true")
    args = ap.parse_args()

    src = Path(args.src)
    if not src.is_file():
        return print(f"not found: {src}") or 1
    md = src.read_text(encoding="utf-8")

    marker_re = re.compile(args.marker_regex) if args.marker_regex else None

    doc = build_document()
    meta = list(args.meta)
    if args.classification:
        meta.append(args.classification)
    add_cover(doc, args.title or src.stem, args.subtitle, args.entity, meta, args.marker_note)
    if not args.no_toc:
        add_toc(doc)
    render(md, doc, marker_re)

    out = Path(args.dst)
    out.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(out))
    print(f"wrote {out}  ({out.stat().st_size:,} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
