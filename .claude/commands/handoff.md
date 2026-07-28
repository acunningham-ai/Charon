---
description: "Cross-session baton: capture the current thread's state to a dated handoff note and produce a paste-ready 'next-session kickoff prompt'. Integrates with the MEMORY.md Pickups list. Writes one note + one index line; asks before touching MEMORY.md."
argument-hint: "<project/thread name> (or omit to infer from the session)"
allowed-tools: Read, Write, Edit, Grep, Glob
---

# /handoff — deliberate cross-session baton

Ends a working session by writing a transferable summary so the next session (or
a post-`/clear` context) resumes without re-deriving. Distinct from `/eod-reflect`
(daily synthesis) and `/refresh-todo` (TODO regen): `/handoff` is a *mid-project
baton* whose headline deliverable is a **paste-ready kickoff prompt**.

## Input

Project/thread from `$ARGUMENTS`; if empty, infer from what this session worked
on (name it back for confirmation before writing).

## Process

1. **Assemble state** (read-only first): what was done this session, current
   status, open threads, the highest-value artifacts (by path), and the single
   next action. Pull from the session's actual work + any `08-Projects/<project>/`
   notes + the relevant memory `project_*.md`.
2. **Write the handoff note** → `08-Projects/<project>/handoffs/<YYYY-MM-DD>-<slug>.md`
   (create the `handoffs/` dir if absent). Frontmatter:
   `type: handoff`, `project:`, `date:` (absolute — computer time is authority),
   `status:`, `generated_by: claude-code /handoff`. Body: **Done / Open threads /
   Highest-value artifacts (paths) / Next action.**
3. **Update the Pickups pointer** — this is the harness's live baton. Propose a
   one-line update to `MEMORY.md` → `## 📌 Pickups (read first)` for this project
   (date + one-line status + ▶ next action). **Show the diff and ask before
   editing MEMORY.md** (it's the index — never silent-write).
4. **Emit the kickoff prompt.** End the response with a fenced, self-contained
   **"Next-session kickoff prompt"** to paste after `/clear`: it names the
   project, the handoff-note path, the 2-3 highest-value artifacts with a
   *"read these first, don't re-derive"* line, and the single next action.

## Output artifacts

- `08-Projects/<project>/handoffs/<date>-<slug>.md` (the note).
- A proposed `MEMORY.md` Pickups line (applied only on your yes).
- The inline kickoff prompt (not written to disk unless asked).

## When NOT to use

- **End-of-day reflection across all threads** → `/eod-reflect`.
- **Rebuild the TODO list from captures** → `/refresh-todo`.
- **Record a single durable fact/preference** → `/push-fact` / `/save-feedback`.

## Co-change couplings

- New handoff note → propose the `MEMORY.md` Pickups line same turn (orphaned
  notes don't fire the baton).
- If the handoff surfaces a durable rule/fact, route it to memory via
  `/save-feedback` / `/push-fact` — the handoff note is transient state, not the
  system of record.
