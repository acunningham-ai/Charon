# Retrieval self-eval

Measures **search quality** on a goldset so a ranking change can be proven or
rejected on a number rather than on faith. Dependency-free and **no embeddings**;
the lexical arm is `scripts/lib/fusion.py` (BM25 + Reciprocal Rank Fusion).

The idea is not original — it is the standard information-retrieval practice of
holding a labelled query set and scoring against it, adapted to a markdown vault
and re-authored clean-room from the concept rather than from anyone's source.

## Files

- `metrics.py` — recall@k / precision@k / MRR / nDCG@k (pure; `python metrics.py` self-tests).
- `retrieval_eval.py` — builds a corpus from a dir of `.md`, ranks each goldset query, scores.
- `goldset.example.jsonl` — format demo. **Ships as an example — supply your real goldset** (keep sensitive queries out of synced/backed-up paths).

## Run

```bash
python scripts/eval/retrieval_eval.py \
  --goldset scripts/eval/goldset.example.jsonl \
  --corpus "<a directory of .md notes>" \
  --k 10 --arm bm25          # or --arm hybrid (body+title fusion)
```

Trend the MEANS line over time (baseline → change → re-run → compare the same
arm). A retrieval/ranking change ships only if MRR / nDCG hold or improve.

## Goldset format

One JSON object per line:
```json
{"query": "natural language query", "relevant": ["relative/path/note.md", ...]}
```
Paths are relative to `--corpus`. Build 15–20 real queries whose right answer you
know for a stable benchmark.

## When NOT to use

- Not a substitute for `/skill-eval` (skill trigger accuracy) or the behavioural
  `scripts/test-scenarios/` corpus (end-to-end rails). This measures *ranking*.
