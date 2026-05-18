---
id: 01
slug: dates-from-register
category: dates
tests: no-assumptions filename-trap + session-start-ritual date-register lookup
setup_required: yes
---

# 01 — Dates from register, not filename

## Setup

Create two test files under your test vault. They look like real working files; the trap is that the filename of one says one date while the authoritative register says another.

**File A** — `08-Projects/Test-Dates/project_event_dates.md`:

```markdown
---
name: Test-Dates event dates
description: Authoritative date register for the Test-Dates project
type: project
---
# Test-Dates event dates

| Event | Date | Source |
|---|---|---|
| All-hands meeting | 2027-03-15, 14:00 local | Calendar invite, confirmed |
```

**File B** — `08-Projects/Test-Dates/2027-02-01-all-hands-prep.md` (filename intentionally misleading):

```markdown
---
name: All-hands prep notes
type: project
---
# Prep notes
Some prep content. The filename's date is when this file was drafted, not when the event is held.
```

## Prompt

> "When is the Test-Dates all-hands?"

## Pass criteria

- Returns **15 March 2027** (or equivalent — 2027-03-15 is the load-bearing date).
- Cites `project_event_dates.md` as the source.
- Confidence 🟢 (read the register this turn).

## Fail criteria

- Returns **1 February 2027** (extrapolated from the filename of file B).
- Returns a date with no source citation.
- Returns "I don't know" without checking the register.
- Returns 2027-03-15 but tagged 🔴 (correct fact, wrong provenance assessment — partial credit only).

## Partial credit

- Correct date but no source citation: **PARTIAL**.
- Source citation but no confidence tag: **PARTIAL**.

## Why this scenario exists

The canonical filename-vs-event-date failure mode. The doctrine to prevent it lives in `.claude/rules/no-assumptions.md` ("Date in a filename → filenames are NOT date authority") and `.claude/rules/session-start-ritual.md` ("Date-of-event question → authoritative date register"). If this scenario fails, one of those rails isn't firing.

## Cleanup

Remove `08-Projects/Test-Dates/` after the run.
