---
name: Load context before responding
always: true
---

# Session-start ritual

Before the first tool call — and before responding to any prompt referencing a project, person, ongoing thread, or date — load the relevant memory **content** (not just the `MEMORY.md` index).

## Checklist

| Trigger | Load |
|---|---|
| Project name (any active initiative the user has named) | Project's `CLAUDE.md` in `08-Projects/<project>/` |
| Person (anyone named in the user's people register) | `reference_person_<slug>.md` or `reference_key_people.md` |
| Operational / deploy task | Recent shell history / prior session journals for prior creds + facts |
| "Last session" / "continue where we left off" / "remember when…" | Recent `memory/sessions/*.md` |
| Date-of-event question | Authoritative date register (e.g. `project_*_dates.md`) — never trust the filename |
| External tool / codebase reference | Source in the user's working trees (e.g. `~/Projects/<tool>/` or `~/reference/<tool>/`) |

**Skipped-ritual signals from the user:** *"why have you forgotten X"*, *"didn't we have Y"*, *"we discussed this before"*. If they say any of these, the ritual missed — apologise briefly, load now, continue.

**Open thread surfacing:** if loaded context reveals an open question from a prior session (e.g. a pickup note's open-thread list), surface it near the start of the response — don't silently inherit a stale plan.
