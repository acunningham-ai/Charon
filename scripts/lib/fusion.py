"""Reciprocal Rank Fusion + pure-Python BM25 — dependency-free hybrid retrieval.

A two-arm, embedding-free ranker: an Okapi BM25 lexical arm over note text plus
any additional pre-ranked lists the caller supplies, fused by Reciprocal Rank
Fusion. Both arms here are non-embedding:

  - lexical: Okapi BM25 over note text (pure stdlib; no model, no network)
  - structural: the caller's graph-proximity ranking (the vault-graph /
    communities) fused in as another ranked list

Because RRF works on positions rather than raw scores, it blends unlike rankers
without any score normalisation, and an arm that returns nothing simply drops out.
Embedding-free by design — Claude Code only; no embedding model is installed
(see `.claude/rules/skill-authoring.md`).
"""
from __future__ import annotations

import math
import re
from collections import Counter
from typing import Dict, Iterable, List, Sequence, Tuple

_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOP = {
    "the", "a", "an", "and", "or", "of", "to", "in", "is", "it", "for", "on",
    "with", "as", "at", "by", "be", "this", "that", "are", "was", "from", "but",
}


def tokenize(text: str) -> List[str]:
    return [t for t in _TOKEN_RE.findall(text.lower()) if t not in _STOP and len(t) > 1]


def reciprocal_rank_fusion(ranked_lists: Sequence[Sequence[str]], k: int = 60) -> List[Tuple[str, float]]:
    """Fuse ranked lists of item ids by RRF. Returns [(id, score)] desc by score.

    Each list is ordered best-first. An id at 1-based rank r in a list contributes
    1/(k + r). Missing from a list = no contribution from it. k=60 is the standard
    default (Cormack et al.); it damps the weight of deep ranks.
    """
    scores: Dict[str, float] = {}
    for lst in ranked_lists:
        for rank, item in enumerate(lst, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(scores.items(), key=lambda kv: kv[1], reverse=True)


class BM25:
    """Okapi BM25 over a fixed document set. Pure stdlib; no embeddings.

    docs: sequence of (doc_id, text). Query with .rank(query) → [(doc_id, score)]
    best-first (only docs scoring > 0).
    """

    def __init__(self, docs: Sequence[Tuple[str, str]], k1: float = 1.5, b: float = 0.75):
        self.k1, self.b = k1, b
        self.doc_ids: List[str] = []
        self.doc_tokens: List[List[str]] = []
        self.doc_freqs: List[Counter] = []
        df: Counter = Counter()
        for doc_id, text in docs:
            toks = tokenize(text)
            self.doc_ids.append(doc_id)
            self.doc_tokens.append(toks)
            freqs = Counter(toks)
            self.doc_freqs.append(freqs)
            for term in freqs:
                df[term] += 1
        self.n = len(self.doc_ids)
        self.avgdl = (sum(len(t) for t in self.doc_tokens) / self.n) if self.n else 0.0
        self.idf: Dict[str, float] = {
            term: math.log(1 + (self.n - d + 0.5) / (d + 0.5)) for term, d in df.items()
        }

    def rank(self, query: str) -> List[Tuple[str, float]]:
        q_terms = [t for t in tokenize(query) if t in self.idf]
        if not q_terms or not self.n:
            return []
        out: List[Tuple[str, float]] = []
        for i, doc_id in enumerate(self.doc_ids):
            freqs = self.doc_freqs[i]
            dl = len(self.doc_tokens[i])
            score = 0.0
            for term in q_terms:
                f = freqs.get(term, 0)
                if not f:
                    continue
                denom = f + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1))
                score += self.idf[term] * (f * (self.k1 + 1)) / denom
            if score > 0:
                out.append((doc_id, score))
        out.sort(key=lambda kv: kv[1], reverse=True)
        return out


def hybrid_rank(
    query: str,
    docs: Sequence[Tuple[str, str, str]],
    extra_arms: Iterable[Sequence[str]] = (),
    k: int = 60,
) -> List[Tuple[str, float, List[str]]]:
    """Fuse a body-BM25 arm + a title/heading-BM25 arm (+ any caller arms) via RRF.

    docs: (doc_id, title, body). `extra_arms`: additional pre-ranked id lists —
    e.g. a graph-proximity ranking of the SAME doc_ids from our vault-graph, or a
    community-cluster ordering. All fused, embedding-free.

    Returns [(doc_id, fused_score, matched_by)] best-first, where matched_by names
    which arms contributed ('body', 'title', 'graph', ...) for provenance.
    """
    body_rank = [d for d, _ in BM25([(i, b) for i, _, b in docs]).rank(query)]
    title_rank = [d for d, _ in BM25([(i, t) for i, t, _ in docs]).rank(query)]
    arms: List[Tuple[str, Sequence[str]]] = [("body", body_rank), ("title", title_rank)]
    for idx, arm in enumerate(extra_arms):
        arms.append((f"arm{idx}", list(arm)))

    fused = reciprocal_rank_fusion([a for _, a in arms], k=k)
    membership: Dict[str, List[str]] = {}
    for label, arm in arms:
        for item in arm:
            membership.setdefault(item, []).append(label)
    return [(doc_id, score, membership.get(doc_id, [])) for doc_id, score in fused]
