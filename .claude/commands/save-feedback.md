---
description: Save a correction or preference to memory the right way (frontmatter, index update, type routing)
argument-hint: "[the feedback statement, or leave blank to use last user message]"
allowed-tools: Read, Write, Edit, Glob, Grep
---

# /save-feedback — encode the save-on-mention rule

You are saving an operational fact, correction, or preference to long-term memory. This implements the **save-on-mention** rule from `CLAUDE.md` — the same turn the fact is mentioned, not at session end.

## Input
$ARGUMENTS

If $ARGUMENTS is empty, use the most recent thing the user said in this session that looked like feedback / a correction / a stated preference. If multiple candidates, ask the user which.

## Routing — pick the right type

| Type | When | File prefix |
|---|---|---|
| **feedback** | Cross-cutting workflow rule, "from now on…", "stop doing X", "this approach worked" | `feedback_*.md` |
| **project** | Time-bound state about an initiative (status, deadline, decision in motion) | `project_*.md` |
| **user** | The user's role, expertise, preferences, knowledge | `user_*.md` |
| **reference** | Pointer to where info lives in an external system | `reference_*.md` |

If the fact is an **operational system fact** (host, path, credential reference, restart sequence, deploy gotcha, named bug) and it belongs to a specific project, route it to that project's `CLAUDE.md` instead — not memory. Credentials NEVER go in memory or CLAUDE.md; they go to the user's secrets directory (`~/.secrets/` by default) and memory points at them.

## Process

### 1. Check for existing memory to update
```
Glob: <memory-root>/{type}_*.md
Grep for related keywords in the body
```
If there's an existing memory on the same topic, **update it** rather than create a new one. Show the user the diff before saving.

### 2. Write the memory file
Path: `<memory-root>/{type}_{slug}.md` — memory root is configured during first-run (defaults to `~/.claude/projects/<project-slug>/memory/`).

Frontmatter:
```yaml
---
name: {short title}
description: {one-line — used to decide relevance in future conversations}
type: {feedback|project|user|reference}
---
```

Body structure for **feedback** and **project** types (load-bearing — do not paraphrase, the validator hook checks for these):
```markdown
{The rule or fact, leading sentence}

**Why:** {the reason — past incident, strong preference, deadline, stakeholder ask}

**How to apply:** {when/where this guidance kicks in — concrete trigger}
```

For **project** type, convert any relative dates to absolute (e.g. "Thursday" → "YYYY-MM-DD"). Today's date is `currentDate` in context.

### 3. Update `MEMORY.md` index
File: `<memory-root>/MEMORY.md`

Add ONE line in the right section, format:
```
- [Title](filename.md) — one-line hook (~150 chars max)
```

`MEMORY.md` is an index — never write content into it, only the pointer line.

### 4. Acknowledge inline
Per the save-on-mention rule, tell the user what you saved in one clause:
> *"Saved the X rule to feedback_X.md, indexed in MEMORY.md."*

Don't make a ceremony of it. One clause. So the user knows it landed.

## Self-checks before writing
- Is this already in an existing memory? (If yes, update — don't duplicate.)
- Does it pass the "what NOT to save" filter? (Code patterns, git history, file paths derivable from the repo, ephemeral task state — DON'T save.)
- For feedback: is there a **Why** line with the actual reason the user gave? (Not your inference — their words. If unclear, ask.)
- Did you co-change `MEMORY.md`? (The validator hook will fail if you wrote a memory file but the index doesn't reference it.)

## See also

- `save-on-mention.md` (always-fire rule) — the principle this skill operationalises
- `.claude/commands/push-fact.md` — surgical updates to existing memory entries
- `07-References/security-baselines.md` C-8 — credentials never in memory or CLAUDE.md
