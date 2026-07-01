---
description: Content-graph hygiene lint over the authored vault body — broken markdown links + tag-taxonomy drift across 01-05/08. Complements /score-vault (harness surfaces). Read-only worklist.
allowed-tools: Bash(python scripts/vault-lint.py), Bash(python scripts/vault-lint.py --json), Read, Edit, Glob, Grep
---

# /vault-lint — content-graph hygiene worklist

Audits the **authored knowledge body** for two decay signals that classic PKM gets wrong: structural rot (broken links), and tag sprawl (frontmatter tags that drift off the taxonomy). The work is deterministic — a Python script does the analysis; your job is to run it, interpret findings, and offer fixes the user approves.

This is the *content-graph* counterpart to `/score-vault` (which audits the harness surfaces: memory dir, CLAUDE.md, `.claude/rules/`). They are deliberately separate — see **When NOT to use**.

## What it checks

- **B. Broken markdown file-links** — across `01-Daily`, `02-BUs`, `03-Domains`, `04-People`, `05-Meetings`, `08-Projects`. `06-`/`07-` are score-vault's turf; `00-Inbox` (untrusted captures), `09-Archive` (cold), and any `captured/` subtree are skipped.
- **C. Tag-taxonomy drift** — lints frontmatter `tags:` against the faceted taxonomy in `07-References/tag-taxonomy.md` (the fenced ```json block is the source of truth). Flags bare (un-namespaced) tags, unknown facets, and unknown values in closed facets (e.g. `portfolio/`, `unit/`, `domain/`, `type/`). Open facets (e.g. `vendor/`, `topic/`) accept any kebab value. Inline `#hashtags` are NOT governed (social tags).

> The taxonomy is **yours to define** — `07-References/tag-taxonomy.md` ships as a template with the schema and illustrative values. The closed-facet values (your units, portfolios, domains) are auto-seedable from the org-unit list captured at first-run. The engine reads whatever facets/values you declare; it hardcodes none.

**Note: no graph-orphan check.** An earlier orphan check was dropped — degree-0 entities and file-level orphans are firehoses when a vault connects via the `[[Entity]] (REL)` graph rather than note-to-note links. "What's under-connected" is a `/vault-query` question, not a hygiene lint.

## Recipe

### 1. Run the lint
```
python scripts/vault-lint.py
```
Read-only markdown worklist: files scanned, findings grouped by severity. `--json` for machine-readable output.

### 2. Present the headline
Lead with the count: files scanned, files with tags, taxonomy version, finding count. If clean, say so plainly.

### 3. Interpret findings
- **HIGH `broken-link`** — a navigational link that doesn't resolve. Real drift; the fix is usually obvious (renamed/moved target) but confirm the intended target.
- **MEDIUM `tag-drift`** — a frontmatter tag not matching the taxonomy: bare (un-namespaced), unknown facet, or unknown value in a closed facet. The message carries a migration hint where one is known.

### 4. First-run calibration — assume miscalibration
Per `skill-authoring.md`: a newly authored audit skill is miscalibrated until proven otherwise. Run `/fp-check` on findings before proposing fixes. NOTE: a spike in `tag-drift` after a taxonomy edit usually means the taxonomy is wrong (missing a facet/value), not that the vault is — fix `tag-taxonomy.md` first.

### 5. Propose fixes — STOP for approval
Produce a fix table BEFORE editing. Broken links → propose the corrected target. Tag drift → propose the migration (bare `meeting` → `type/meeting` etc.); bulk tag migration touches many authored files, so batch it (via `scripts/migrate-tags.py --batch <facet>`) and get explicit approval per batch. **Do not edit anything until the user confirms.** Never edit `00-Inbox/_captured/**`.

## Output artifacts
None persisted by default — prints a report to stdout. Any fixes are human-confirmed edits to existing authored notes.

## Multi-mode
- **Interactive** (this command): run, interpret, propose, fix-on-approval.
- **Scheduled** (not wired by default): a runner could call `--json` and surface the count via the same notification path as other audits. Wiring it is a separate confirmed step (touches the scheduler + `scheduled-audit.py`).

## When NOT to use
- **Harness-surface drift** (broken CLAUDE.md/MEMORY.md paths, unindexed memory files, rule triggers) → that's `/score-vault`, not this.
- **Answering "what's connected to X / path from A to B"** → that's `/vault-query` (graph traversal), not a hygiene lint.
- **Triaging new captures** → `/triage-inbox`.

## Co-change couplings
- New check added here that emits a new output shape → consider whether the scheduled-audit roll-up needs to recognise it.
- If a scheduled runner is added → wire into `scripts/scheduled-audit.py` and document in the automation register.
