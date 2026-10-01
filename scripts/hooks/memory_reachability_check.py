#!/usr/bin/env python3
"""
Shared reachability primitive — "if I needed this memory, would I find it?"

Used by `enforce-memory-index-cochange.py` (the Stop-hook co-change) and by
`scripts/memory_reachability.py` (the corpus-wide report). ONE definition of
"orphan" so the real-time enforcer and the periodic detector cannot drift —
the same single-source discipline `score-vault.indexed_memory_names()` had, but
measuring the thing that matters.

The definition
--------------
A memory file is REACHABLE if, querying the corpus with the file's own
`description:` frontmatter — the question it exists to answer — the file comes
back in the top-K. A file that cannot retrieve itself by its own description
will not be retrieved when the question is asked for real.

This replaced "is it linked from MEMORY.md" on 2026-09-29. Measured over 422
files that day, linkage produced 5 false orphans and 0 true ones, and missed the
one genuinely unfindable file (empty description, dutifully linked).

Fail-open by contract: any error returns "nothing missing". This backs a hygiene
control, not a security gate, and a detector that breaks a turn is worse than no
detector.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

DEFAULT_K = 10

FM_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.DOTALL)
DESC_RE = re.compile(r"^description:\s*(.+?)\s*$", re.MULTILINE)
NAME_RE = re.compile(r"^name:\s*(.+?)\s*$", re.MULTILINE)


def _vault_root(memory_dir: Path) -> Path | None:
    """Find the vault (for scripts/lib/fusion.py) from this file's location."""
    here = Path(__file__).resolve().parent
    for cand in [here, *here.parents]:
        if (cand / "scripts" / "lib" / "fusion.py").is_file():
            return cand
    return None


def self_query(text: str, stem: str) -> str | None:
    """The question this file exists to answer, in its own words.

    Returns None when there is no usable `description:`. That is deliberately
    NOT backfilled from `name:` or the filename: a file called
    `zz_probe_unreachable.md` retrieves itself at rank 1 on its own unique slug
    while being useless to any real question. Falling back would have scored
    that file "reachable" and hidden exactly the defect this check exists to
    find. No description means no stated question, which means unreachable.
    """
    m = FM_RE.match(text)
    fm = m.group(1) if m else ""
    d = DESC_RE.search(fm)
    if d:
        v = d.group(1).strip().strip('"').strip("'")
        # A one-or-two-word description is a slug in disguise; it cannot carry
        # the words a real question will use.
        if len(v.split()) >= 3:
            return v
    return None


def unreachable_names(memory_dir: Path, candidates, is_deprecated=None, k: int = DEFAULT_K):
    """Of `candidates` (basenames in memory_dir), which cannot retrieve themselves?

    Returns a sorted list. Empty on any failure — fail open.
    """
    try:
        memory_dir = Path(memory_dir)
        root = _vault_root(memory_dir)
        if root is None:
            return []
        sys.path.insert(0, str(root / "scripts" / "lib"))
        import fusion  # noqa: E402

        docs, texts = [], {}
        for p in sorted(memory_dir.glob("*.md")):
            if p.name == "MEMORY.md":
                continue  # the index is about memories, not one of them
            try:
                t = p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            docs.append((p.name, t))
            texts[p.name] = t
        if not docs:
            return []

        bm = fusion.BM25(docs)

        out = []
        for name in candidates:
            p = memory_dir / name
            if name not in texts:
                continue
            if is_deprecated is not None:
                try:
                    if is_deprecated(p):
                        continue
                except Exception:
                    pass
            q = self_query(texts[name], p.stem)
            if q is None:
                out.append(name)   # no stated question -> unreachable by intent
                continue
            hits = [d for d, _ in bm.rank(q)][:k]
            if name not in hits:
                out.append(name)
        return sorted(out)
    except Exception:
        return []
