---
id: 16
slug: vault-graph-pipeline
category: graph
tests: v0.8.0 graphify-borrow pipeline — community detection + HTML viewer + /vault-query + wiki generation
setup_required: yes
---

# 16 — v0.8.0 vault graph pipeline end-to-end

Tests that the v0.8.0 vault-graph improvements compose correctly: cluster the existing vault graph, generate an interactive HTML viewer, run a natural-language query, and (optionally) write per-community wiki docs. Skipped on installs without the optional `networkx` dep; gracefully reports the prereq when absent.

## Setup

Confirm the optional dep is installed:

```bash
python -c "import networkx; print('networkx', networkx.__version__)"
```

If it is missing, install:

```bash
pip install -r requirements-graph.txt
```

The vault graph must already have content. If `<vault>/.charon/knowledge-graph.json` doesn't exist yet, populate via:

```bash
python scripts/extract_entities.py
```

## Prompt to test

> Cluster my vault graph, then open the interactive HTML viewer, then explain what `<entity-name>` is connected to.

(Replace `<entity-name>` with any entity you know is in the graph.)

## Expected behaviour

1. The assistant invokes `python scripts/cluster_vault.py` first.
   - Output mentions Louvain, the community count, the size distribution, and the file written (`<vault>/.charon/graph-communities.json`).
2. The assistant invokes `python scripts/vault_graph_html.py` next.
   - Output reports the number of nodes / edges / communities written and the path: `<vault>/.charon/graph.html`.
   - The assistant offers the user the `file://` URL to open in a browser.
3. The assistant runs `python scripts/vault_query.py explain "<entity-name>"`.
   - Output shows the entity's neighbours with `→` (outgoing) / `←` (incoming) arrows and relationship labels.
4. Optionally — if the user asks for the wiki summary too — the assistant runs `python scripts/vault_wiki.py plan` first to show what would be written, then `vault_wiki.py generate` if confirmed.

## Anti-patterns to flag

- Running `vault_query.py explain` BEFORE the graph has been populated → should fail with "vault graph not found" message and a clear pointer to `extract_entities.py`.
- Skipping `cluster_vault.py` and trying to open `graph.html` straight away — viewer works but communities won't be coloured.
- Invoking an LLM to "guess" connections instead of using the actual graph traversal.
- Modifying the graph from any of these scripts. All four are read-only on the graph file (only `cluster_vault.py` writes to `.charon/graph-communities.json`; only `vault_wiki.py generate` writes to `07-References/communities/`).

## What's checked

- The four commands chain cleanly (no errors between them)
- Output paths land where the docs say they land
- Failures (missing graph file, missing optional deps) surface with usable error messages, not stack traces

## Cleanup

Nothing to clean up — the run is read-only on user content. The `.charon/graph-communities.json` and `graph.html` files are regenerable artifacts; safe to leave in place.

## Notes

This scenario exercises four of the five v0.8.0 borrows; multimodal extraction (chunk 5) has its own deterministic check (D19) since it requires fixture binaries.

Deterministic equivalents in `run-deterministic-checks.py`:
- D15 — Community detection
- D16 — HTML viewer rendering
- D17 — Vault query traversal
- D18 — Community wiki rendering
- D19 — Multimodal extractors presence + availability reporting
