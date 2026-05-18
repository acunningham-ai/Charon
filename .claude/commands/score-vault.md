---
description: Audit MEMORY.md / CLAUDE.md / .claude/rules/ against the filesystem; emit a hygiene score + finding list
allowed-tools: Bash, Read, Edit, Glob, Grep
---

# /score-vault — deterministic vault hygiene audit

You are auditing the harness for drift between the auto-loaded surfaces (CLAUDE.md, MEMORY.md, `.claude/rules/`, the memory directory) and the actual filesystem. The work is deterministic — a Python script does the analysis; your job is to run it, interpret the findings, and offer fixes.

## Recipe

### 1. Run the audit
```
python scripts/score-vault.py
```

The script returns a markdown report: hygiene score (0–100) + findings table grouped by severity. It is read-only — no files are modified.

### 2. Present the score to the user
Show the score and finding count at the top. If `100/100`, say so plainly — clean is a real result, not a script bug.

### 3. Interpret findings (only if any)
Group your commentary by severity:
- **CRITICAL** (broken CLAUDE.md paths): root CLAUDE.md auto-loads every session, so a broken path here is a session-start error. Highest priority.
- **HIGH** (broken memory-index links, broken cross-refs, missing scripts): structural drift that will cause confusion or wrong references in future work.
- **MEDIUM** (unindexed / deprecated-but-still-linked memory files, missing rule triggers): hygiene; fix in batches.
- **LOW** (missing frontmatter fields, unknown types): cosmetic; only fix if touching the file anyway.

### 4. Propose fixes — STOP for approval
Produce a fix table BEFORE editing:

| Finding | Proposed fix | Severity |
|---|---|---|
| … | … | … |

Ask: *"Apply these fixes?"* — **do not edit anything until the user confirms.**

If a finding requires the user's judgement (e.g. is this file actually deprecated, or just unindexed by mistake?), surface it as a question instead of proposing a default fix.

### 5. Apply fixes after confirmation
For each fix:
- **Broken MEMORY.md link → existing-but-renamed file:** update the MEMORY.md entry to point at the actual filename.
- **File on disk not in MEMORY.md:** either add an index entry OR mark `status: deprecated` in frontmatter (ask the user which).
- **Deprecated file still linked:** unlink from MEMORY.md.
- **Broken cross-reference:** update the citing file to point at the correct target, OR remove the reference if no target exists.
- **Missing CLAUDE.md path:** update CLAUDE.md to point at the actual path, OR remove the reference.
- **Missing frontmatter field:** add the field with a sensible value (ask the user if the value isn't obvious).

After applying, re-run `python scripts/score-vault.py` to confirm the score has lifted.

## Done criteria

- Audit ran successfully
- Score + findings presented to the user
- If findings: fix table was reviewed and approved before edits
- If fixes applied: re-run confirms score improvement
- No silent edits

## When to run

- After significant memory restructuring.
- Before sharing the vault layout (demoing the harness, onboarding a collaborator).
- Periodically — monthly is probably right.
- When something feels off in session-start context (e.g. a referenced file isn't loading).
