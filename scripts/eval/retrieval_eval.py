#!/usr/bin/env python3
"""Retrieval self-eval — measure vault search quality on a goldset. No embeddings.

Builds a corpus from a directory of .md notes, runs each arm (bm25 / hybrid via
scripts/lib/fusion.py), and scores recall@k / precision@k / MRR / nDCG@k against a
goldset of (query -> relevant paths). Deterministic, dependency-free. Turns "did
that retrieval/ranking change help?" into a trended number.

Goldset JSONL — one object per line:
  {"query": "...", "relevant": ["relative/path/to/note.md", ...]}
Paths are relative to --corpus. Ships an EXAMPLE goldset; supply your real one
(keep it out of sync/backup if queries are sensitive).

Usage:
  python scripts/eval/retrieval_eval.py --goldset <file.jsonl> --corpus <dir> \
         [--k 10] [--arm bm25|hybrid]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

_HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(_HERE.parent / "lib"))  # scripts/lib for fusion
import fusion  # noqa: E402
import metrics  # noqa: E402  (same dir)
sys.path.insert(0, str(_HERE))


def build_corpus(corpus_dir: Path) -> List[Tuple[str, str, str]]:
    """Return [(rel_path, title, body)] for every .md under corpus_dir."""
    docs: List[Tuple[str, str, str]] = []
    for p in sorted(corpus_dir.rglob("*.md")):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = str(p.relative_to(corpus_dir)).replace("\\", "/")
        title = next((ln.lstrip("# ").strip() for ln in text.splitlines()
                      if ln.startswith("#")), p.stem)
        docs.append((rel, title, text))
    return docs


def rank(query: str, docs, arm: str) -> List[str]:
    if arm == "hybrid":
        return [d for d, _, _ in fusion.hybrid_rank(query, docs)]
    return [d for d, _ in fusion.BM25([(i, b) for i, _, b in docs]).rank(query)]


def load_goldset(path: Path) -> List[Dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            rows.append(json.loads(line))
    return rows


def main() -> int:
    ap = argparse.ArgumentParser(description="Vault retrieval self-eval.")
    ap.add_argument("--goldset", required=True)
    ap.add_argument("--corpus", required=True)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--arm", choices=["bm25", "hybrid"], default="bm25")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    corpus_dir = Path(args.corpus)
    docs = build_corpus(corpus_dir)
    gold = load_goldset(Path(args.goldset))
    if not docs or not gold:
        sys.stderr.write("error: empty corpus or goldset\n")
        return 1

    agg = {"recall": 0.0, "precision": 0.0, "mrr": 0.0, "ndcg": 0.0}
    per_query = []
    for row in gold:
        ranked = rank(row["query"], docs, args.arm)
        rel = row["relevant"]
        r = metrics.recall_at_k(ranked, rel, args.k)
        p = metrics.precision_at_k(ranked, rel, args.k)
        m = metrics.mrr(ranked, rel)
        n = metrics.ndcg_at_k(ranked, rel, args.k)
        agg["recall"] += r; agg["precision"] += p; agg["mrr"] += m; agg["ndcg"] += n
        per_query.append({"query": row["query"], "recall": r, "precision": p, "mrr": m, "ndcg": n})

    nq = len(gold)
    means = {k: round(v / nq, 4) for k, v in agg.items()}
    result = {"arm": args.arm, "k": args.k, "queries": nq, "corpus_docs": len(docs), "means": means}
    if args.json:
        print(json.dumps({"result": result, "per_query": per_query}, indent=2))
    else:
        print(f"arm={args.arm} k={args.k} queries={nq} corpus={len(docs)} docs")
        for pq in per_query:
            print(f"  r={pq['recall']:.2f} p={pq['precision']:.2f} mrr={pq['mrr']:.2f} ndcg={pq['ndcg']:.2f}  {pq['query'][:50]}")
        print(f"MEANS  recall@{args.k}={means['recall']}  precision@{args.k}={means['precision']}  MRR={means['mrr']}  nDCG@{args.k}={means['ndcg']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
