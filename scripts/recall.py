#!/usr/bin/env python3
"""/recall backend — hybrid (BM25 + title) retrieval over the authored vault.

Dependency-free, NO embeddings by design (Claude Code only); uses
scripts/lib/fusion.py. Walks the authored vault notes (skips untrusted captures,
archive, code, dotdirs), ranks by fused body+title BM25, prints the top-k with
path, title, matched-by provenance, and a snippet.

Usage:
  python scripts/recall.py "your query" [--k 8] [--root <dir>] [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Tuple

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE / "lib"))
import fusion  # noqa: E402

# Directory names excluded from recall (untrusted / non-knowledge / code).
_SKIP_DIRS = {
    "_captured", "09-Archive", ".obsidian", ".claude", "scripts",
    "capture-pipeline", "node_modules", ".git", "_Templates", "templates",
    "__pycache__", ".harness-cache",
}


def _skip(path: Path, root: Path) -> bool:
    rel_parts = path.relative_to(root).parts
    return any(p in _SKIP_DIRS for p in rel_parts)


def build_corpus(root: Path) -> List[Tuple[str, str, str]]:
    docs: List[Tuple[str, str, str]] = []
    for p in sorted(root.rglob("*.md")):
        if _skip(p, root):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        title = next((ln.lstrip("# ").strip() for ln in text.splitlines() if ln.startswith("#")), p.stem)
        docs.append((str(p.relative_to(root)).replace("\\", "/"), title, text))
    return docs


def _snippet(body: str, query: str) -> str:
    terms = set(fusion.tokenize(query))
    for ln in body.splitlines():
        s = ln.strip()
        if not s or s.startswith("#") or s.startswith("---"):
            continue
        if terms & set(fusion.tokenize(s)):
            return s[:160]
    for ln in body.splitlines():
        s = ln.strip()
        if s and not s.startswith(("#", "---")):
            return s[:160]
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description="Hybrid recall over the authored vault.")
    ap.add_argument("query")
    ap.add_argument("--k", type=int, default=8)
    ap.add_argument("--root", default=str(_HERE.parent))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = Path(args.root)
    docs = build_corpus(root)
    if not docs:
        sys.stderr.write("recall: no notes found under root\n")
        return 1
    body_by_id = {i: b for i, _, b in docs}
    title_by_id = {i: t for i, t, _ in docs}

    ranked = fusion.hybrid_rank(args.query, docs)[: args.k]
    if args.json:
        print(json.dumps([
            {"path": i, "title": title_by_id[i], "score": round(s, 5),
             "matched_by": m, "snippet": _snippet(body_by_id[i], args.query)}
            for i, s, m in ranked
        ], indent=2))
    else:
        if not ranked:
            print(f"recall: no matches for {args.query!r} across {len(docs)} notes")
            return 0
        print(f"recall: top {len(ranked)} of {len(docs)} notes for {args.query!r}\n")
        for rank, (i, s, m) in enumerate(ranked, 1):
            print(f"{rank}. {title_by_id[i]}  [{'+'.join(m)}]")
            print(f"   {i}")
            snip = _snippet(body_by_id[i], args.query)
            if snip:
                print(f"   … {snip}")
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
