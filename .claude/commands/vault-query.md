---
name: vault-query
description: Natural-language graph queries over the Charon vault knowledge graph. Ask things like "what's connected to X?", "what's the path from A to B?", or "tell me about X". Wraps scripts/vault_query.py with assistant-driven NL parsing.
---

Adam wants a natural-language graph query. Use the `vault-query` skill.

The skill parses Adam's question into one of four subcommands and invokes `python scripts/vault_query.py`:

- `search <query>` — fuzzy-find entities by name
- `explain <name>` — entity + its 1-hop neighbours with relationship labels
- `neighbours <name> --depth N [--dfs]` — BFS or DFS around a starting node
- `path <source> <target>` — shortest path between two entities

Output is text by default; pass `--json` for structured output the skill can fold into a natural-language answer.

Requires the optional kuzu + networkx deps (`pip install -r requirements-graph.txt`) and a populated vault graph (run `python scripts/extract_entities.py` first). The skill detects when those preconditions aren't met and prints a clear pointer.
