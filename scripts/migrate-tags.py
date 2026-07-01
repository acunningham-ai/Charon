#!/usr/bin/env python
"""migrate-tags.py — faceted-tag migration for authored frontmatter.

Rewrites bare/legacy frontmatter `tags:` to the faceted taxonomy in
07-References/tag-taxonomy.md. Companion to /vault-lint Check C: the lint
DETECTS drift, this RESOLVES it. Deterministic, batchable, dry-run by default.

Resolution order for each tag:
  1. Static migration map from the taxonomy (`meeting` -> `type/meeting`, ...).
  2. Folder-derived context for bare `unit` / `portfolio` / `domain`:
       - unit     <- 02-BUs/_Portfolio-<Grp>/<Unit>/...    -> unit/<slug(Unit)>
       - portfolio<- 02-BUs/_Portfolio-<Grp>/...           -> portfolio/<grp>
       - domain   <- 03-Domains/<Domain>/...               -> domain/<slug(Domain)>
     Derived unit/domain values are validated against the taxonomy's closed lists;
     an underivable or invalid one is LEFT ALONE (reported, not guessed).
  3. Already-faceted and taxonomy-valid tags are left untouched.

Batches (--batch): unit | type | domain | portfolio | tag | all
Modes: default = dry-run (unified diff to stdout); --apply writes in place.

Only touches authored dirs (01-Daily, 02-BUs, 03-Domains, 04-People,
05-Meetings, 08-Projects), never `captured/` subtrees or 00-Inbox/09-Archive.

Usage:
  python scripts/migrate-tags.py --batch unit            # dry-run diff
  python scripts/migrate-tags.py --batch unit --apply    # write
"""
import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.harness_paths import vault_root  # noqa: E402

VAULT_ROOT = vault_root()
LINT_DIRS = ("01-Daily", "02-BUs", "03-Domains", "04-People", "05-Meetings", "08-Projects")
CAPTURED_SEGMENTS = {"captured", "_captured", "_audit"}
TAXONOMY_DOC = VAULT_ROOT / "07-References" / "tag-taxonomy.md"

FRONTMATTER_RE = re.compile(r"^(---\s*\n)(.*?)(\n---)", re.DOTALL)
JSON_BLOCK_RE = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)


def _read(p):
    try:
        return p.read_text(encoding="utf-8")
    except Exception:
        return ""


def _slug(s):
    return re.sub(r"[^a-z0-9-]", "", s.strip().lower().replace(" ", "-"))


def load_taxonomy():
    m = JSON_BLOCK_RE.search(_read(TAXONOMY_DOC))
    tax = json.loads(m.group(1))
    facets = tax["facets"]
    closed = {n: set(s.get("values", [])) for n, s in facets.items() if s.get("closed")}
    return tax.get("migrations", {}), facets, closed


def _facet_of(target):
    """The facet a resolved tag belongs to (for batch filtering)."""
    return target.split("/", 1)[0] if "/" in target else None


def derive_contextual(tag, rel: Path, closed):
    """Resolve bare unit/portfolio/domain from the file's folder. None if not derivable."""
    parts = rel.parts
    if tag == "unit" and parts[0] == "02-BUs":
        # .../_Portfolio-<Grp>/<Unit>/<file>
        for i, p in enumerate(parts):
            if p.startswith("_Portfolio-") and i + 1 < len(parts) - 1:
                slug = _slug(parts[i + 1])
                if slug in closed.get("unit", set()):
                    return f"unit/{slug}"
        return None
    if tag == "portfolio" and parts[0] == "02-BUs":
        for p in parts:
            if p.startswith("_Portfolio-"):
                grp = _slug(p[len("_Portfolio-"):])
                if grp in closed.get("portfolio", set()):
                    return f"portfolio/{grp}"
        return None
    if tag == "domain" and parts[0] == "03-Domains" and len(parts) >= 2:
        slug = _slug(parts[1])
        if slug in closed.get("domain", set()):
            return f"domain/{slug}"
        return None
    return None


def resolve(tag, rel, migrations, facets, closed):
    """Return the target tag, or None to leave unchanged."""
    if "/" in tag:
        return None  # already faceted — Check C validates these separately
    if tag in migrations:
        return migrations[tag]
    return derive_contextual(tag, rel, closed)


def rewrite_tags_block(fm_body, transform):
    """Apply `transform(tag)->tag_or_same` to every tag in a frontmatter body.
    Handles inline `tags: [a, b]` and block `tags:\\n  - a` forms. Returns the
    new body and the list of (old, new) changes."""
    changes = []

    def _map(t):
        nt = transform(t)
        if nt and nt != t:
            changes.append((t, nt))
            return nt
        return t

    # Inline form
    inline = re.search(r"^(tags:\s*)\[(.*?)\]\s*$", fm_body, re.MULTILINE | re.DOTALL)
    if inline:
        items = [x.strip() for x in inline.group(2).split(",") if x.strip()]
        new_items = []
        for it in items:
            q = it[0] if it[:1] in "\"'" else ""
            bare = it.strip("\"'")
            new_items.append(f"{q}{_map(bare)}{q}")
        new_line = f"{inline.group(1)}[{', '.join(new_items)}]"
        fm_body = fm_body[: inline.start()] + new_line + fm_body[inline.end():]
        return fm_body, changes

    # Block form: rewrite each `  - <tag>` line under a tags: key
    lines = fm_body.split("\n")
    out = []
    in_tags = False
    for ln in lines:
        if re.match(r"^tags:\s*$", ln):
            in_tags = True
            out.append(ln)
            continue
        if in_tags:
            m = re.match(r"^(\s*-\s*)(.+?)\s*$", ln)
            if m:
                bare = m.group(2).strip("\"'")
                out.append(f"{m.group(1)}{_map(bare)}")
                continue
            else:
                in_tags = False
        out.append(ln)
    return "\n".join(out), changes


def _authored_files():
    for d in LINT_DIRS:
        root = VAULT_ROOT / d
        if not root.exists():
            continue
        for f in root.rglob("*.md"):
            rel = f.relative_to(VAULT_ROOT)
            if any(p.lower() in CAPTURED_SEGMENTS for p in rel.parts[:-1]):
                continue
            yield f, rel


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", default="all",
                    choices=["unit", "type", "domain", "portfolio", "tag", "all"])
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    args = ap.parse_args()

    migrations, facets, closed = load_taxonomy()

    def transform(tag, rel):
        target = resolve(tag, rel, migrations, facets, closed)
        if not target:
            return tag
        if args.batch != "all" and _facet_of(target) != args.batch:
            return tag
        return target

    total_files = 0
    total_changes = 0
    for f, rel in _authored_files():
        text = _read(f)
        m = FRONTMATTER_RE.search(text)
        if not m:
            continue
        body = m.group(2)
        new_body, changes = rewrite_tags_block(body, lambda t: transform(t, rel))
        if not changes:
            continue
        total_files += 1
        total_changes += len(changes)
        chg = ", ".join(f"{o} -> {n}" for o, n in changes)
        print(f"{'APPLIED' if args.apply else 'DRY'} {rel}: {chg}")
        if args.apply:
            new_text = text[: m.start(2)] + new_body + text[m.end(2):]
            f.write_text(new_text, encoding="utf-8")

    print()
    print(f"{'Applied' if args.apply else 'Would change'} {total_changes} tags "
          f"across {total_files} files (batch={args.batch}).")
    if not args.apply:
        print("Dry-run only. Re-run with --apply to write.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
