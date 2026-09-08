"""Information-retrieval metrics — pure stdlib, no deps, no embeddings.

recall@k / precision@k / MRR / nDCG@k for binary relevance (a doc is relevant
or not). Used by retrieval_eval.py to trend vault search quality over time.
Deterministic; has a known-answer self-test (`python metrics.py`).
"""
from __future__ import annotations

import math
from typing import Iterable, List, Sequence


def recall_at_k(ranked: Sequence[str], relevant: Iterable[str], k: int) -> float:
    rel = set(relevant)
    if not rel:
        return 0.0
    hits = sum(1 for d in ranked[:k] if d in rel)
    return hits / len(rel)


def precision_at_k(ranked: Sequence[str], relevant: Iterable[str], k: int) -> float:
    rel = set(relevant)
    if k <= 0:
        return 0.0
    hits = sum(1 for d in ranked[:k] if d in rel)
    return hits / k


def mrr(ranked: Sequence[str], relevant: Iterable[str]) -> float:
    rel = set(relevant)
    for i, d in enumerate(ranked, start=1):
        if d in rel:
            return 1.0 / i
    return 0.0


def ndcg_at_k(ranked: Sequence[str], relevant: Iterable[str], k: int) -> float:
    rel = set(relevant)
    dcg = sum(1.0 / math.log2(i + 1) for i, d in enumerate(ranked[:k], start=1) if d in rel)
    ideal_hits = min(len(rel), k)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_hits + 1))
    return (dcg / idcg) if idcg else 0.0


def _selftest() -> int:
    ranked = ["a", "b", "c", "d"]
    rel = ["b", "d"]
    assert recall_at_k(ranked, rel, 4) == 1.0
    assert recall_at_k(ranked, rel, 2) == 0.5
    assert precision_at_k(ranked, rel, 2) == 0.5
    assert mrr(ranked, rel) == 0.5              # first relevant at rank 2
    assert mrr(["b", "a"], rel) == 1.0
    assert abs(ndcg_at_k(["b", "d"], rel, 2) - 1.0) < 1e-9   # perfect order
    assert ndcg_at_k(["x", "y"], rel, 2) == 0.0
    print("metrics selftest: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(_selftest())
