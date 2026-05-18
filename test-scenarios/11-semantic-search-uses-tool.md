---
id: 11
slug: semantic-search-uses-tool
category: retrieval
tests: vault-readonly semantic_search tool dispatch + graceful degradation
setup_required: yes
optional_feature: semantic-search
---

# 11 — Semantic search uses the MCP tool

## Setup

Verify the optional dep is installed:
```bash
pip install -r requirements-semantic.txt
```

Place a test file at `02-BUs/Test-Unit/decision-notes.md`:

```markdown
---
type: project
name: Test-Unit decision notes
---
# Test-Unit decision notes

We considered three vendor options for endpoint detection-and-response coverage.
Option A had the best price; Option B had the strongest integration story; Option C
had the cleanest privacy posture. We picked Option B because the cross-tenant
identity story was the deciding factor for our federated environment.
```

Build the semantic index:
```bash
python scripts/semantic_index.py
```

## Prompt

> "Find anything in my vault that discusses choosing between vendor options based on identity integration."

(Note: the exact phrase "identity integration" appears nowhere in the test file — keyword search misses this; semantic search should match because "cross-tenant identity story" is the relevant content.)

## Pass criteria

- Agent uses the `semantic_search` MCP tool from `vault-readonly` this turn.
- Returns the test file (`02-BUs/Test-Unit/decision-notes.md`) in the top results.
- Quotes or references the "cross-tenant identity story" content as the matching reason.
- Confidence 🟢 (read the file this turn after semantic search returned it).

## Fail criteria

- Agent uses only `search_memory` (keyword) and reports nothing found.
- Agent claims it can't search the vault — `semantic_search` is wired and the index is built.
- Agent fabricates content not in the test file.
- Returns a result without citing the file path.

## Partial credit

- Uses semantic_search but doesn't cite the matched file as source: **PARTIAL**.
- Uses semantic_search but quotes content that's not in the test file: **PARTIAL FAIL**.

## Graceful-degradation variant

Re-run after `pip uninstall sentence-transformers sqlite-vec` (or move the index file aside). Expected:

- Agent attempts `semantic_search`, receives the error response with the `hint: pip install -r requirements-semantic.txt` payload.
- Agent surfaces the error to the user verbatim — *"semantic search isn't enabled on this install; install with..."*. Does NOT pretend to have searched and report fake results.

## Why this scenario exists

Semantic search is the headline new retrieval capability and must (a) fire when available + (b) degrade gracefully when not. Tests both modes.

## Cleanup

Remove `02-BUs/Test-Unit/` after the run. If the test file was indexed, re-run `python scripts/semantic_index.py --rebuild` to flush the test entry.
