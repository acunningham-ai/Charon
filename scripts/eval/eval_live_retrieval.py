#!/usr/bin/env python3
"""eval_live_retrieval.py — measure the retrieval that ACTUALLY injects context.

WHY THIS EXISTS
---------------
`retrieval_eval.py` measures `fusion.py` (BM25 / hybrid), which powers `/recall`.
But the thing that decides what reaches a session's context is a *different*
system: `scripts/hooks/memory-retrieve.py`, a UserPromptSubmit hook with its own
entity/slug scorer, its own SCORE_FLOOR / RELATIVE_FLOOR, and a hard
MAX_INJECT_BYTES budget.

Discovered 2026-09-08: `memory-retrieve.py` contains no reference to `fusion.py`
at all. So the goldset baseline (bm25 recall@10 0.92) said nothing about whether
the live path works. Two independent retrieval systems, one measured, the other
not. This closes that.

THE METRIC THAT MATTERS HERE IS NOT recall@10
---------------------------------------------
For the live hook, "was the target in the top 10" is close to meaningless,
because only what fits in MAX_INJECT_BYTES is actually shown to the model.
Everything past the budget is invisible no matter how well it ranked. So this
reports THREE things:

  recall@k        - did the scorer rank it at all (comparable to retrieval_eval)
  recall@injected - did the target survive the byte budget (the real question)
  dropped         - how often the budget was the binding constraint

A gap between recall@k and recall@injected is a *budget* problem, not a
*ranking* problem, and the fix is different (raise/adapt the cap vs. retune the
scorer). Telling those apart is the whole point.

USAGE
    python scripts/eval/eval_live_retrieval.py --goldset scripts/eval/goldset.jsonl
    python scripts/eval/eval_live_retrieval.py --goldset ... --k 5 --verbose

Read-only. Never writes to the retrieval log — this is an evaluator, not a run.
"""
import argparse
import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import metrics  # noqa: E402

HOOK_PATH = Path(__file__).resolve().parents[1] / "hooks" / "memory-retrieve.py"


def load_hook():
    """Import the hook module despite its hyphenated filename."""
    spec = importlib.util.spec_from_file_location("memory_retrieve_hook", HOOK_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load %s" % HOOK_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def as_path(slug: str) -> str:
    """Normalise a slug to the goldset's path form.

    Memory entries are bare slugs (`feedback_x`); vault entries already carry a
    path with an extension.
    """
    return slug if slug.endswith(".md") else slug + ".md"


def injected_slugs(hook, top, neighbours, entries):
    """The slugs that would SURVIVE the byte budget and reach the model.

    Mirrors the hook's own render path rather than reimplementing it, so this
    cannot drift from production behaviour.
    """
    try:
        text, tier, dropped = hook.render(top, neighbours, entries)
    except Exception:
        text, tier, dropped = "", "error", len(top)
    out = []
    for _, slug, _ in top:
        # A slug counts as injected only if it actually appears in the rendered
        # payload — that is what the budget did or did not admit.
        if slug and slug in text:
            out.append(slug)
    return out, len(text.encode("utf-8")), tier, dropped


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--goldset", required=True)
    ap.add_argument("--k", type=int, default=10)
    ap.add_argument("--verbose", action="store_true")
    args = ap.parse_args()

    hook = load_hook()
    index = hook.load_index()
    entries = (index or {}).get("entries") or {}
    if not entries:
        sys.stderr.write(
            "error: retrieval index empty or missing at %s\n"
            "       run scripts/build_memory_retrieval_index.py first\n" % hook.INDEX_PATH
        )
        return 2

    rows = []
    for line in Path(args.goldset).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            rows.append(json.loads(line))
    if not rows:
        sys.stderr.write("error: empty goldset\n")
        return 2

    agg = {"r_k": [], "p_k": [], "mrr": [], "ndcg": [], "r_inj": []}
    dropped = 0
    tiers = {}
    misses_ranked, misses_budget = [], []

    for row in rows:
        q, rel = row["query"], row["relevant"]
        top, neigh, stats = hook.select(index, q)
        ranked = [as_path(s) for _, s, _ in top]
        inj_slugs, nbytes, tier, dropped_n = injected_slugs(hook, top, neigh, entries)
        inj = [as_path(s) for s in inj_slugs]

        r_k = metrics.recall_at_k(ranked, rel, args.k)
        r_inj = metrics.recall_at_k(inj, rel, max(1, len(inj)))
        agg["r_k"].append(r_k)
        agg["p_k"].append(metrics.precision_at_k(ranked, rel, args.k))
        agg["mrr"].append(metrics.mrr(ranked, rel))
        agg["ndcg"].append(metrics.ndcg_at_k(ranked, rel, args.k))
        agg["r_inj"].append(r_inj)
        tiers[tier] = tiers.get(tier, 0) + 1
        if dropped_n:
            dropped += 1

        if r_k == 0.0:
            misses_ranked.append(q)
        elif r_inj == 0.0:
            misses_budget.append(q)

        if args.verbose:
            print("  r@%d=%.2f r@inj=%.2f mrr=%.2f  ranked=%d inj=%d %db  %s"
                  % (args.k, r_k, r_inj, metrics.mrr(ranked, rel),
                     len(ranked), len(inj), nbytes, q[:46]))

    n = len(rows)
    mean = lambda xs: sum(xs) / max(1, len(xs))  # noqa: E731
    print("\nLIVE ARM (memory-retrieve.py) over %d queries, %d index entries" % (n, len(entries)))
    print("  recall@%-3d       %.3f   <- did the scorer rank it" % (args.k, mean(agg["r_k"])))
    print("  recall@injected  %.3f   <- did it survive the %dB budget (THE REAL ONE)"
          % (mean(agg["r_inj"]), hook.MAX_INJECT_BYTES))
    print("  MRR              %.3f" % mean(agg["mrr"]))
    print("  nDCG@%-3d         %.3f" % (args.k, mean(agg["ndcg"])))
    print("  detail tiers     %s   <- 'full' = no budget pressure" % dict(sorted(tiers.items())))
    print("  coverage lost    %d/%d queries (last-resort path only)" % (dropped, n))

    gap = mean(agg["r_k"]) - mean(agg["r_inj"])
    if gap > 0.01:
        print("\n  >> BUDGET PROBLEM: %.1f%% of queries rank the target but never show it."
              % (100 * gap))
        print("     Fix is the cap/adaptive budget, not the scorer.")
    if misses_ranked:
        print("\n  RANKING MISSES (scorer never found it) — %d:" % len(misses_ranked))
        for q in misses_ranked:
            print("     -", q[:88])
    if misses_budget:
        print("\n  BUDGET MISSES (ranked but cut) — %d:" % len(misses_budget))
        for q in misses_budget:
            print("     -", q[:88])
    return 0


if __name__ == "__main__":
    sys.exit(main())
