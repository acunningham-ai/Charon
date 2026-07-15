---
paths:
  - "??-*/**"
keywords:
  - "write a note"
  - "create a note"
  - "new note"
  - "synthesis"
  - "backlink"
  - "wikilink"
---

# Backlink authoring discipline

When authoring a **substantive** note anywhere in the authored vault body, give
it real graph connectivity instead of leaving it an orphan. A note with no
connections is just a file; a note with several `[[backlinks]]` is a node of
thought, and the graph is only as alive as its link density.

## The rule

Every substantive authored note gets **≥3 `[[backlinks]]`** to existing notes,
of which **≥1 targets a note in the oldest ~20% of the vault** (by creation
date) — the *anti-recency link*.

- The oldest-20% link fights recency bias: it forces new thinking to connect
  back to dormant notes so they resurface instead of dying in the graph. A note
  with no old links is a note that only talks to this month.
- `/graph-backfill`'s `## Related` footer `[[wikilinks]]` **count** toward the
  ≥3. If a note already earns 3+ derived edges, running `/graph-backfill`
  satisfies the discipline; don't hand-place links redundantly.
- The relative "oldest ~20%" threshold auto-ages as the vault grows — no
  re-tuning, and it works whether the vault is three months or ten years old.

## Scope — denylist, not allowlist (grows with the vault)

In-scope = **any authored top-level vault folder** (the `NN-Name` folders),
whether it exists today or is added later. Scope is defined by what's
**excluded**, so a new folder is covered automatically the moment it appears —
there is no folder list to maintain.

**Excluded zones (never in scope)** — mirrors `/graph-backfill`'s exclusions:
- `00-Inbox/_captured/**` — untrusted captured content; never author links into
  or out of it.
- `_Templates` / `templates` / `_templates`, `09-Archive`, `.obsidian`.
- `CLAUDE.md` and dotfiles.

**Also out of scope by note-type** (the "substantive" qualifier): one-line
stubs, meeting-note stubs, daily-note quick lines. Forcing 3 links onto a
two-sentence note produces noise, not a node.

## How to find an oldest-tier note

Glob the authored folders, sort by creation date (or the dated filename where
that IS the creation date — daily notes, decision records), take the earliest
~20%, and pick a *topically relevant* one. A forced-but-irrelevant old link is
worse than none — if nothing in the old tier genuinely relates, say so rather
than manufacture a junk edge.

## Anti-patterns

- **Manufacturing an irrelevant old-tier link** just to satisfy the count.
  Relevance beats compliance.
- **Linking to non-existent entities** to pad the number. Unresolved
  `[[Entity]]` links are fine when the entity is real-but-unwritten (rendered as
  a faded node); inventing a target is not.
- **Applying this to micro-notes.** Substantive notes only.

## Co-change couplings

- This is a *generative* authoring discipline; `/graph-backfill` is the
  *reflection* tool (materialises edges that already exist). They compose:
  author with links → `/graph-backfill` surfaces the derived web.
- `/vault-lint` orphan-hunt is the audit backstop — it catches notes that
  slipped the discipline.
