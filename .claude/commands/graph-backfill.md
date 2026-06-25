---
description: Materialise the knowledge-graph edges as `## Related` [[wikilink]] footers in your notes, so Obsidian's graph view reflects the real entity web. Footer-only, idempotent, dry-run by default.
argument-hint: "[optional: --apply to write, default is a dry-run preview]"
allowed-tools: Bash, Read
---

# /graph-backfill — write the derived graph back into your notes

Your vault has **two graphs**. Obsidian's graph view draws only the `[[wikilinks]]` physically present in note bodies — but the rich entity web (who works on what, which tool affects which unit, how decisions connect) lives in the **derived** knowledge graph built by `extract_entities.py`. That web is never written back into the notes, so Obsidian can't see it.

This command closes the gap: for each note, it appends a delimited `## Related` footer of `[[wikilinks]]` to the entities that note connects to. **Prose is never touched** — only the marked block. Re-runs replace the block (idempotent), and a note whose edges have gone has its stale block removed.

It is the **final stage of the graph-build sequence**:

```
extract_entities.py  →  cluster_vault.py  →  vault_graph_html.py  →  graph_link_backfill.py
```

## How to run

Preview first (no files written):

```bash
python scripts/graph_link_backfill.py
```

Then apply once the sample blocks look right:

```bash
python scripts/graph_link_backfill.py --apply
```

Useful flags:
- `--min-conf 0.8` — only materialise edges at/above this extraction confidence (default `0.8`).
- `--keep-fileish` — keep targets that look like file paths/extensions (default drops them as graph-node noise).
- `--limit N` — process only the first N notes (handy for a canary run).
- `--sample N` — show N rendered blocks in dry-run.

## Scope

Generic by design — no folder taxonomy assumed. Every note that has extracted edges gets a footer, **except**: untrusted captured content (frontmatter `trust: untrusted`), templates, dotfile dirs (`.obsidian`, `.charon`, `.git`), and any `CLAUDE.md`.

## Preconditions

Requires the optional graph deps (`pip install -r requirements-graph.txt`) and a populated graph (run `python scripts/extract_entities.py` first). The script prints a clear pointer if either is missing. Unresolved `[[Entity]]` links are expected and fine — Obsidian renders them as faded nodes, so the full web shows even before every entity has a backing note.
