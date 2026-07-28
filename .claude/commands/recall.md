---
description: "Hybrid (BM25 body+title, no-embeddings) recall over the AUTHORED VAULT NOTES (00-09 / projects / references) — returns the top notes for a natural-language query with path, provenance, and snippet. Read-only PULL. For the harness memory dir use search_memory; for how entities connect use vault-query."
argument-hint: "<what you're trying to find> [--k N]"
allowed-tools: Bash(python scripts/recall.py:*), Read
---

# /recall — hybrid retrieval over the vault

Finds the notes most relevant to a query by fusing a body-BM25 and a title-BM25
arm via Reciprocal Rank Fusion (`scripts/lib/fusion.py`). Dependency-free, **no
embeddings** (Claude Code only, by design). A ranked PULL over the authored
vault — complements the vault-graph (which answers *how things connect*) and
`search_memory` (which searches the harness memory dir).

## Run

```bash
python scripts/recall.py "$ARGUMENTS"
```

(Backend skips untrusted captures, archive, code, and dotdirs; ranks fused
body+title BM25; prints path + title + matched-by + snippet.) Add `--k N` for
more hits, `--json` for structured output.

## Use the results

Present the ranked hits, then — if the answer needs the actual content — `Read`
the top note(s) and answer grounded in them (cite `path`). Don't re-derive what a
hit already records.

## When NOT to use

- **How entities connect / paths between them** → `/vault-query` (graph BFS/DFS).
- **Searching the harness memory dir** → `search_memory` (vault-readonly MCP).
- **Recall over untrusted captures** → out of scope by design (captures excluded).

## Co-change couplings

- Ranking logic lives in `scripts/lib/fusion.py`; keep the two arms
  (body + title BM25) embedding-free per the Claude-only constraint.
