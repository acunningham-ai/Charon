---
name: vault-query
description: Natural-language graph queries over the Charon vault knowledge graph — BFS/DFS, shortest paths, neighbourhood expansion, entity explanation. Parses the user's plain-English question into the right scripts/vault_query.py subcommand and folds the result into a human-readable answer with file:line provenance.
---

# vault-query

You are running the **/vault-query** flow. The user asks a natural-language question about the vault; you turn it into a graph traversal and answer with what the graph says.

## When this fires

- *"What's connected to X?"*
- *"Tell me about X"* — when X is a person, project, BU, decision, etc.
- *"What's the path between A and B?"*
- *"Find me everything around X"*
- *"How does X relate to Y?"*

Triggers also include: `/vault-query`, "vault query", "graph query", "show me the connections".

## Routing — pick one of four subcommands

```bash
python scripts/vault_query.py <subcommand> [args] [--json]
```

| User intent | Subcommand | Example |
|---|---|---|
| "tell me about X" / "what does X do" / "who is X" | `explain` | `vault_query.py explain "<person-or-project-name>"` |
| "what's connected to X" / "what's around X" | `neighbours --depth 2` (BFS default) | `vault_query.py neighbours "<topic-or-project>" --depth 2` |
| "trace from X to Y" / "how is X related to Y" / "shortest path" | `path` | `vault_query.py path "<entity-A>" "<entity-B>"` |
| "find X" / can't find an exact match for X / spelling unsure | `search` | `vault_query.py search "<name-fragment>"` |

When user names an entity that isn't an exact match, **always start with `search`** to find the candidate names. Then confirm or pick the best match before running `explain` / `neighbours` / `path`.

## Procedure

### 1. Preconditions

Before running anything, verify the graph is available:

```bash
python scripts/vault_query.py search _check_ 2>&1 | head -3
```

If output starts with `vault-query unavailable:`, surface the reason to Adam and stop. Common reasons:

- `kuzu not installed` → tell Adam to run `pip install -r requirements-graph.txt`
- `networkx not installed` → same
- `vault graph not found` → tell Adam to run `python scripts/extract_entities.py` first

### 2. Parse the user's question into entity names

The user will say things like *"how is &lt;person&gt; connected to the &lt;project&gt; work?"*. Your job is to extract `<person>` and `<project>` as the two anchor entities, NOT to invent entity names.

Strategy:
- Pull the proper nouns / project names / titles out of the user's message
- If you're unsure of the exact match, run `vault_query.py search <fragment>` first
- Confirm the match with Adam before proceeding if it's ambiguous

### 3. Run the right subcommand

For `explain` / `neighbours` / `path`, pass `--json` so you can fold structured results into a natural-language answer:

```bash
python scripts/vault_query.py neighbours "<project-key>" --depth 2 --json
```

### 4. Compose the answer

Don't just dump the JSON. Synthesise it into a paragraph + supporting list. For example:

> The vault graph shows **`<project>`** has 14 connections at depth 1 and 47 at depth 2. The immediate cluster includes:
> - **`<person-A>`** (person, reviewer)
> - **`<document>`** (document, related policy)
> - **`<person-B>`** (person, legal contributor)
> - ... plus 11 more direct neighbours.
>
> At depth 2 the graph reaches: *(... summarise the secondary cluster ...)*

Include file:line provenance from the `edge.source_file` field whenever you mention a relationship — that's how Adam audits the answer.

### 5. If the answer is "no path / no neighbours / nothing found"

Be honest about it. Don't invent connections. Tell Adam:

> The graph has no path between *X* and *Y*. They live in different communities according to the current extraction. If you expect them to be connected, the extractor may have missed a relationship — run `python scripts/extract_entities.py --paths <relevant-files.md>` to re-extract those files.

## What this skill does NOT do

- ❌ Does NOT call the LLM to "guess" connections that aren't in the graph. Only what's extracted is real.
- ❌ Does NOT modify the graph. Read-only.
- ❌ Does NOT extract entities itself — that's `scripts/extract_entities.py` (a separate, cost-incurring run).
- ❌ Does NOT replace the MCP server (`scripts/mcp/vault-graph-server.py`). That stays available for tool-style queries; this skill is the user-facing natural-language entry point.

## Output examples

**explain:**

```
  <Person Name>  [person]
  6 neighbour(s):
    → <Project Name>  [project]  (REVIEWS)
    → <Document Name>  [document]  (REFERENCES)
    ← <Event Name>  [event]  (ATTENDED)
    ...
```

**path:**

```
  path (4 nodes):
    0. <Person A>  [person]
       └─ WORKS_ON
    1. <Project A>  [project]
       └─ REFERENCES
    2. <Project B>  [project]
       └─ REVIEWED_BY
    3. <Person B>  [person]
```

**neighbours:**

```
  18 entities via BFS
  depth 0 (1): <Starting Entity>
  depth 1 (6): <Neighbour 1>, <Neighbour 2>, <Neighbour 3>, ...
  depth 2 (11): <Second-hop Entity 1>, <Second-hop Entity 2>, ...
```
