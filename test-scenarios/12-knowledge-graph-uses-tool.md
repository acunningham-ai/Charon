---
id: 12
slug: knowledge-graph-uses-tool
category: retrieval
tests: vault-graph get_entity tool dispatch + graceful degradation
setup_required: yes
optional_feature: knowledge-graph
---

# 12 — Knowledge graph uses the MCP tool

## Setup

Verify the optional dep is installed:
```bash
pip install -r requirements-graph.txt
```

Confirm Anthropic API key is at `<HARNESS_SECRETS_DIR>/anthropic.json`.

Place a test file at `08-Projects/Test-Project/CLAUDE.md`:

```markdown
# Test-Project

Test-Project is owned by Jane Doe. It depends on the Acme-API tool for inbound webhooks
and on the BetaService database for persistence. Jane reports to Alex Kim, who heads
the Platform team.
```

Build the knowledge graph:
```bash
python scripts/extract_entities.py --paths 08-Projects/Test-Project/CLAUDE.md
```

Verify the entities are present:
```bash
python scripts/extract_entities.py --stats
```

(You should see nodes + edges; specifically entities for Test-Project, Jane Doe, Acme-API, BetaService, Alex Kim, Platform.)

## Prompt

> "What do we know about Jane Doe?"

## Pass criteria

- Agent calls the `get_entity` tool from `vault-graph` MCP this turn.
- Returns Jane Doe's relationships: WORKS_ON Test-Project, REPORTS_TO Alex Kim (or similar — depends on what Haiku extracted).
- Cites `08-Projects/Test-Project/CLAUDE.md` as the source file (from the relationship metadata).
- Confidence 🟢 (graph queried this turn).

## Fail criteria

- Agent ignores the knowledge graph and only does keyword search.
- Agent fabricates relationships not in the graph.
- Returns "I don't know about Jane Doe" when the graph clearly has her.
- Attempts a write through the MCP server — should be impossible (the server is read-only by construction, exposing only `get_entity` + `stats`) but flag if attempted.

## Partial credit

- Uses `get_entity` but doesn't cite the source file from edge metadata: **PARTIAL**.

## Graceful-degradation variant

Re-run with the graph dep absent (`pip uninstall networkx`). Expected:

- Agent calls `get_entity`, receives error response with `hint: pip install -r requirements-graph.txt`.
- Agent surfaces the error verbatim. Does not pretend to know about Jane Doe.

Re-run with networkx installed but graph file removed. Expected:

- Agent calls `get_entity`, receives error response with `hint: python scripts/extract_entities.py`.
- Agent surfaces the error.

## Why this scenario exists

The knowledge graph is the structured-recall layer. Tests that the agent reaches for it on entity-style questions ("what do we know about X") rather than defaulting to keyword search across raw markdown. Also tests the closed-vocabulary safety (write keywords blocked).

## Cleanup

Remove `08-Projects/Test-Project/`. Rebuild the graph with `python scripts/extract_entities.py --rebuild` to flush the test entries (or accept the test entities in your graph — they cost ~$0.001 to re-extract on next rebuild).
