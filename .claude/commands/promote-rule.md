---
description: Promotion-gradient skill — surface memory-rule candidates for promotion to path-specific rules or extraction into standalone skills
argument-hint: "<action> [args] — actions: status | review | promote <feedback_file.md> | extract <feedback_file.md> <new_skill_name> | remember <feedback_file.md>"
allowed-tools: Bash, Read, Edit, Write, Glob, Grep
---

# /promote-rule — memory → path-rule → skill promotion gradient

You are executing the CLAUDE.md Co-Change Coupling principle that says: *"Memory file with new feedback rule → consider promoting to path-specific rule under `.claude/rules/`"*. The principle existed; until now there was no skill to act on it. This is that skill.

## The promotion gradient

```
memory/feedback_*.md  (general workflow rule, recalled when relevant)
    │
    │  promoted when: referenced often, OR clearly path/keyword-scoped
    ▼
.claude/rules/*.md    (auto-injected by load-rules.py when paths/keywords match)
    │
    │  extracted when: the rule has become a repeatable workflow
    ▼
.claude/commands/*.md  (slash command — invokable, parameterised, repeatable)
```

The skill helps you move rules UP this gradient as patterns recur. It also handles the inverse — flagging stale entries for archival.

## Scope

$ARGUMENTS — required. The first token names the action; the rest are action-specific args.

| Action | Args | What it does |
|---|---|---|
| `status` | none | Report on the current state of the promotion layers — how many rules where, last-touched recency, candidates flagged. |
| `review` | none | List feedback rules that are promotion candidates with rationale. Read-only. |
| `promote <feedback_X.md>` | filename | Promote a feedback rule to a `.claude/rules/*.md` path-conditioned rule. Asks for the `paths:` / `keywords:` trigger before writing. |
| `extract <feedback_X.md> <command-name>` | filename, slash-command name | Scaffold a new `.claude/commands/<command-name>.md` from a feedback rule. Asks for command argument shape before writing. |
| `remember <feedback_X.md>` | filename | Mark a feedback rule as stale-archive-candidate or refresh its `last_used` if it's still active. |

If `$ARGUMENTS` is empty, stop and ask: *"Which action? Examples: `status`, `review`, `promote feedback_save_on_mention.md`, `extract feedback_quarterly_process.md /qr-check`, `remember feedback_old_rule.md`."*

## Recipe per action

### `status`

Quick inventory:
- Count of files in `<memory-root>/feedback_*.md`
- Count of files in `.claude/rules/*.md`
- Count of files in `.claude/commands/*.md` (excluding built-ins)
- Top 5 feedback rules referenced in recent sessions (grep session journals)
- Bottom 5 feedback rules NOT referenced in any session in the last 30 days

Output is a one-screen markdown table. Read-only.

### `review`

Identify promotion candidates. A rule is a candidate IF:
- It's been referenced in 3+ recent sessions (`memory/sessions/*.md` grep)
- AND its content clearly scopes to a path or keyword (e.g. mentions specific folders, file types, or trigger phrases)
- AND there isn't already a `.claude/rules/*.md` covering the same scope

For each candidate, show:
- Feedback rule filename + 1-line summary (from `description:` frontmatter)
- Recent reference count
- Suggested `paths:` and/or `keywords:` trigger
- Suggested new filename under `.claude/rules/`

Also flag staleness candidates: feedback rules with no session reference in 90+ days.

Read-only — does not promote, just surfaces.

### `promote <feedback_X.md>`

Walk through with the user:

1. Read the feedback rule. Show its content.
2. Propose: a new file at `.claude/rules/<slug>.md` with frontmatter `paths:` / `keywords:` triggers, and the rule body adapted (drop the "Why" + "How to apply" memory structure; keep the actionable text).
3. **STOP for confirmation.** Show the diff (new file content + memory file's proposed frontmatter update — typically adding `promoted_to: .claude/rules/<slug>.md` and `status: superseded` if fully migrated).
4. After confirmation: write the new rule file. Optionally update the feedback file's frontmatter to point at it.
5. Confirm via `/score-vault` — the new file should be picked up.

### `extract <feedback_X.md> <command-name>`

Walk through with the user:

1. Read the feedback rule. Show its content.
2. Propose: a new `.claude/commands/<command-name>.md` with:
   - `description:` derived from the rule
   - `argument-hint:` — ask the user what arguments the command takes
   - `allowed-tools:` — minimum set
   - Body recipe that ENACTS the rule (not just states it — extracts the actionable workflow into steps)
3. **STOP for confirmation.** Show the proposed command file.
4. After confirmation: write the command. Leave the feedback rule in place (it remains the conceptual reference; the command is the operational form).

### `remember <feedback_X.md>`

Lighter touch:
1. Read the rule.
2. Check session journals for any reference in the last N days (default 90).
3. If recently used: update the rule's `last_used:` frontmatter field with today's date. Done.
4. If unused in 90+ days: propose marking `status: candidate-for-archive` in frontmatter. **STOP for confirmation.** Don't auto-delete.

## Constraints

- **No silent edits.** Every action that writes a file requires the user's confirmation, except `status` and `review` (read-only) and `remember` on an active rule (just refreshes a date).
- **No deletions.** `remember` flags stale; it doesn't delete. Memory hygiene rule (CLAUDE.md "Self-Protection") prohibits deletion of memory files.
- **Promote preserves provenance.** When a rule moves layers, leave a breadcrumb: feedback file gets `promoted_to:` frontmatter; rule / command file gets a comment `<!-- promoted from memory/feedback_X.md on YYYY-MM-DD -->` near the top.
- **One action per invocation.** Don't chain `promote` then `extract` in a single run — that hides decisions.

## Done criteria

- The requested action ran.
- For write actions: the user confirmed before any file changes.
- For status / review: a clear one-screen summary returned.
- For successful promotions: `/score-vault` shows no new findings introduced.

## When to use

- After `/score-vault` flags a feedback rule that's been touched a lot but is still in memory.
- After a session where the user noticed themselves re-explaining the same rule across multiple turns — that's promotion-pressure signal.
- Periodically — every 1–2 months `/promote-rule status` as a hygiene pass.
- When building a new automation that needs a behaviour the rule describes — `/promote-rule extract feedback_X.md /new-skill` scaffolds the start.

## When NOT to use

- For brand-new rules — write them to memory first (`/save-feedback`), let them prove themselves over a few sessions before promoting.
- For rules that are personal / contextual (e.g. specific to a single project) — those stay in memory; promotion is for cross-cutting patterns.
- For rules that are already on a `.claude/rules/*` trigger — no further promotion needed unless you're extracting to a command.
