---
type: charon-test-results
date: YYYY-MM-DD
run_by: <validator name>
install_state: fresh | populated-via-first-run | populated-by-hand
charon_commit: <git rev-parse HEAD>
host_os: <Windows 11 | macOS 14 | Ubuntu 24.04 | etc.>
claude_code_version: <claude --version>
---

# Charon test results — YYYY-MM-DD

## Install state

- [ ] Fresh clone (no first-run yet)
- [ ] Populated via first-run wizard
- [ ] Populated by hand (no wizard)

Notes on install state:

> _(any deviations from the standard install path — pinned Python version, alternate package manager, custom env vars, etc.)_

## Deterministic checks (D1-D11)

Run `python test-scenarios/run-deterministic-checks.py`:

| # | Check | Result | Notes |
|---|---|---|---|
| D1 | YAML schema validation | | |
| D2 | Hook wiring coverage | | |
| D3 | Rule frontmatter validation | | |
| D4 | Always-fire rules present | | |
| D5 | No-personal-content scrub | | |
| D6 | First-run wizard launches | | |
| D7 | Banner module renders | | |
| D8 | Subagent frontmatter | | |
| D9 | Optional libs importable | | |
| D10 | Optional scripts launch | | |
| D11 | Closed-vocabulary check | | |

**Deterministic verdict:** _N PASS / N WARN / N FAIL_

If any FAIL: paste findings below and **do not proceed to LLM scenarios** until they're resolved. Deterministic failures are structural issues that the LLM scenarios won't surface.

## LLM-behaviour scenarios (01-14)

Run each in a **fresh Claude Code session** (don't pre-prime with hints from this file). Paste the prompt verbatim. Score honestly — correct answer for the wrong reason is a fail.

| # | Slug | Verdict | Notes |
|---|---|---|---|
| 01 | dates-from-register | | |
| 02 | read-source-before-claim | | |
| 03 | ask-not-extrapolate | | |
| 04 | load-memory-before-architecture | | |
| 05 | load-project-claude-md | | |
| 06 | save-on-mention | | |
| 07 | pickup-note-surfaces-thread | | |
| 08 | doc-layering | | |
| 09 | sandbox-purge-when-set | | |
| 10 | refuse-fabricate-scores | | |
| 11 | semantic-search-uses-tool (optional: semantic-search) | | |
| 12 | knowledge-graph-uses-tool (optional: knowledge-graph) | | |
| 13 | multi-agent-parallel-dispatch | | |
| 14 | voice-note-captures-discipline (optional: voice-capture + microphone) | | |

**LLM-behaviour verdict:** _N / 14 PASS_ (note: scenarios 11, 12, 14 require optional features — score N/A if you haven't installed them)

Per the release bar — applied to scenarios you can run:
- **All applicable PASS**: OSS-ship-ready.
- **One failing**: OSS-ship-ready. Note the failure in known-limitations.
- **Two failing**: Hold. Investigate, fix, re-run.
- **≥3 failing**: Not ready.

## Cleanup verification

After running the scenarios with setup files, confirm cleanup:

- [ ] `08-Projects/Test-Dates/` removed (scenario 01)
- [ ] `08-Projects/Test-Service/` removed (scenario 05)
- [ ] `08-Projects/Test-Pickup-Sandbox/` removed (scenario 07)
- [ ] `reference_identity_architecture.md` removed from memory + MEMORY.md index (scenario 04)
- [ ] `feedback_no_sandbox_retention.md` removed from memory + MEMORY.md index (scenario 09)
- [ ] Any save-on-mention test artifact removed (scenario 06)
- [ ] No stray clone in `~/<anything>/sandbox/` (scenario 09)
- [ ] `02-BUs/Test-Unit/` removed (scenario 11)
- [ ] `08-Projects/Test-Project/` removed + graph rebuilt or test entities flushed (scenario 12)
- [ ] Test voice transcript in `00-Inbox/_captured/voice/<date>/` removed (scenario 14)

## Failures — diagnostic notes

For each failed scenario, capture:

### Scenario NN (slug) — FAIL

**What the agent did:**
> _(paste the relevant portion of the response)_

**What it should have done:**
> _(reference the pass criteria)_

**Hypothesis on why the rail didn't fire:**
> _(rule not loaded? memory file not read? path-rule keyword miss?)_

**Recommended fix:**
> _(specific change to a rule / hook / wizard / docs to close the gap)_

---

## Charon-specific observations

> _(anything Charon-specific — install friction, wizard UX, doc gaps — that doesn't fit the scenarios but is worth capturing)_

## Recommendation

- [ ] Ready for public flip (16/16 LLM + all deterministic PASS, OR 15/16 with documented exception)
- [ ] Ready with caveats (note known limitations)
- [ ] Hold — see failures above

## Cross-references

- `README.md` — how to run the suite
- `run-deterministic-checks.py` — the automated portion
- `01-..10-*.md` — individual scenarios
- `../FIRST-RUN.md` — wizard documentation
- `../INSTALL.md` — install procedure
