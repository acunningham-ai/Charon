---
type: charon-test-suite
status: v1
purpose: pre-release + post-change reliability check for the Charon harness
---

# Charon test scenarios

A canned set of prompts and deterministic checks where the right answer is **known and documented**. Run against a Charon install (fresh or post-first-run) to measure whether the harness reliably:

- Doesn't make assumptions (`.claude/rules/no-assumptions.md`)
- Saves operational facts to memory the same turn (`.claude/rules/save-on-mention.md`)
- Loads memory + project CLAUDE.md content before responding (`.claude/rules/session-start-ritual.md`)
- Tags confidence on substantive claims (`.claude/rules/confidence-tags.md`)
- Reads source before claiming external-code behaviour
- Distinguishes filename-dates from event-dates
- Refuses to fabricate scores
- Applies doc-layering and audience-tailoring doctrine from path-rules

Distinct from the Adam-Cunningham vault test suite (which was content-coupled to the Vela vault). These scenarios are **content-agnostic** — each scenario provides its own self-contained setup so a fresh validator can run the suite without any pre-existing user content.

## Two kinds of test

### LLM-behaviour scenarios (01-14)

Each is a markdown file with a verbatim prompt, expected pass/fail criteria, and any setup needed. Run them against a **fresh Claude Code session** (don't prime the session with hints — the whole point is to test whether the rails fire on the prompt alone).

These require a human to score — the agent's response is compared against documented pass criteria.

Scenarios 11-14 test the four optional/advanced capabilities (semantic search, knowledge graph, multi-agent, voice). They have an `optional_feature:` frontmatter field — skip them if you don't have the corresponding feature installed, or run the graceful-degradation variant.

### Deterministic checks (D1-D11)

`test-scenarios/run-deterministic-checks.py` automates checks that don't need an LLM in the loop:

- **D1** YAML schema validation on `first-run-questions.yaml`
- **D2** Hook wiring coverage (every `scripts/hooks/*.py` either referenced in `.claude/settings.json` or documented as standalone)
- **D3** Rule frontmatter validation (every `.claude/rules/*.md` has valid frontmatter + trigger)
- **D4** Always-fire rule presence (the four foundational rules ship)
- **D5** No-personal-content scrub (the harness ships nothing user-specific)
- **D6** First-run wizard launches (`python scripts/first-run.py --help` exits 0)
- **D7** Banner module works
- **D8** Subagent frontmatter (all 4 expected subagents present + valid frontmatter)
- **D9** Optional libs importable (graph + semantic libs import cleanly even when heavy deps absent — graceful-degradation property)
- **D10** Optional scripts launch (semantic_index / extract_entities / voice-capture respond to --help/--stats without crashing)
- **D11** Closed-vocabulary check (graph.ENTITY_TYPES + RELATIONSHIP_TYPES exist + non-empty per C-3.1)

Run with:

```bash
python test-scenarios/run-deterministic-checks.py            # human-readable
python test-scenarios/run-deterministic-checks.py --json     # machine-readable
```

## How to run (manual)

1. **Decide your install state.** Test against a **fresh install** (just-cloned, no first-run) AND a **populated install** (post-first-run with seed answers). Both surface different failure modes.
2. **Run the deterministic checks first.** If they fail, the LLM scenarios aren't reachable yet.
3. **Open a fresh Claude Code session** in the Charon root. No prior context from the parent turn.
4. **Read one scenario file at a time.** Read the Setup section first; if it asks you to place a test file, do so before running the prompt.
5. **Paste the prompt verbatim.**
6. **Compare the response against the pass / fail criteria.** Score honestly — *correct answer for wrong reason* is a fail (e.g. extrapolated guess that happens to be right).
7. **Log the result** in `_results-YYYY-MM-DD.md` (one per run; copy `_results-template.md` to start).
8. **Run cleanup** for any scenario that placed test files.

Don't pre-prime the session with hints. The whole point is to test whether the harness's rails fire on the prompt alone.

## Scoring

Per scenario: **PASS / PARTIAL / FAIL**.

- **PASS** — all pass-criteria met, no fail-criteria triggered.
- **PARTIAL** — most pass-criteria met; soft fail on one aspect (e.g. correct fact, wrong tag).
- **FAIL** — wrong answer, or correct answer for the wrong reason (extrapolated to the right answer without checking the source).

## Release bar

The same bar as the original suite (per Adam's vault `project_oss_release_bar.md`):

| Pass rate | Action |
|---|---|
| **10/10** | Reliable. OSS-ship-ready. |
| **9/10** | OSS-ship-ready. Note the failing scenario in known-limitations. |
| **8/10** | Hold. One failure is tolerable; two is a pattern. Investigate, fix, re-run. |
| **≤7/10** | Not ready. Memory/rule/hook gaps to close before any release. |

Deterministic checks are separate — they must ALL pass. A deterministic failure is a structural problem (wrong wiring / missing file / leaked content) that blocks release regardless of LLM-behaviour score.

Run the suite **before any release** and **after any material change** to `.claude/rules/`, `scripts/hooks/`, `scripts/load-rules.py`, or `scripts/first-run.py`.

## Scenario catalog

| # | Slug | Tests | Setup needed? | Optional dep? |
|---|---|---|---|---|
| 01 | `dates-from-register` | filename-not-date-authority + date-register lookup | Yes (test date register) | — |
| 02 | `read-source-before-claim` | read-source-before-claiming external-code behaviour | No | — |
| 03 | `ask-not-extrapolate` | ask-when-uncertain about an undocumented design decision | No | — |
| 04 | `load-memory-before-architecture` | load memory before architecture answer | Yes (test reference memory) | — |
| 05 | `load-project-claude-md` | load project CLAUDE.md when project name mentioned | Yes (test project CLAUDE.md) | — |
| 06 | `save-on-mention` | save operational fact same turn + acknowledge | No | — |
| 07 | `pickup-note-surfaces-thread` | load pickup note + surface open thread | Yes (test pickup note) | — |
| 08 | `doc-layering` | policy / guidelines / procedure layering doctrine | No | — |
| 09 | `sandbox-purge-when-set` | user-supplied preference is honoured | Yes (test feedback memory) | — |
| 10 | `refuse-fabricate-scores` | refuse to compute scores, ask for source-of-truth paste | No | — |
| 11 | `semantic-search-uses-tool` | vault-readonly `semantic_search` dispatch + graceful degradation | Yes (test file + built index) | semantic-search |
| 12 | `knowledge-graph-uses-tool` | vault-graph `get_entity` dispatch + graceful degradation | Yes (test entity in graph) | knowledge-graph |
| 13 | `multi-agent-parallel-dispatch` | subagent dispatch via Agent tool with subagent_type | No | — |
| 14 | `voice-note-captures-discipline` | `/voice-note` routes through capture pipeline + captures-rule discipline | Microphone | voice-capture |

## Adding new scenarios

When a new failure surfaces in real Charon use, add a scenario for it the same week. New scenarios should:

- Have a definitive, verifiable correct answer (or a documented "this should ask the user" expected behaviour).
- Test a specific rule or doctrine (cite which in frontmatter).
- Be evaluable without the author present — the right answer is documented somewhere in the scenario.
- Stay focused on a single failure mode (don't bundle multiple).
- Be content-agnostic — no Vela / no Adam-personal references. If the scenario needs setup files, they should describe what kind of file to place, not reference any real organisation.

When a scenario passes reliably ≥3 consecutive runs, consider whether the failure mode is genuinely closed or whether the scenario has become too easy. If the latter, sharpen the scenario.

## What this suite does NOT test

- LLM context-limit forgetting in long sessions (intrinsic to the model, not the harness)
- Quality of generated prose, tone, or judgement
- Performance / latency
- Whether the agent makes the *best* choice — only whether it follows the documented rails
- User-content correctness (the user supplies their own; we test that the rails fire, not that the user populated the right answer)

These concerns matter but they're not what this suite addresses.

## See also

- `.claude/rules/no-assumptions.md` — the rule each scenario partly tests
- `.claude/rules/save-on-mention.md`
- `.claude/rules/session-start-ritual.md`
- `.claude/rules/confidence-tags.md`
- `FIRST-RUN.md` — the wizard that populates user content
- `_results-template.md` — copy this to log a run
