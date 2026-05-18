---
name: Confidence tags on substantive claims
always: true
---

# Confidence tags

Tag substantive factual claims so the user can see what's grounded vs assumed.

## Tags

- 🟢 **verified** — read the source / confirmed / ran the command **this turn**
- 🟡 **medium** — in memory or prior context; not freshly checked
- 🔴 **assumed** — extrapolated. Needs check before acting.

## Tag when

- Paths / function names / line numbers
- Dates / deadlines / owners / hostnames / ports / credentials
- Behaviour of external code / third-party tools / repo contents
- Summaries of prior session context ("last session we agreed X")
- Numbers in reports / mocks / external-bound material
- "X already exists" / "Y doesn't support Z" / "the API for that is W"
- Recommendations whose merit depends on a factual premise being right

## Don't tag

- Conversational text / framing / transitions
- Recommendations clearly framed as such ("I'd suggest...", "consider...", "my read is...")
- Restatements of the user's prompt
- Structural elements (headings, table formatting)
- Opinions where framing already signals subjectivity

## Placement

Inline at sentence end ("forum is 20 May 2026 🟢"), bullet prefix ("- 🟡 ..."), or as a table column.

## Anti-patterns

- Tagging every sentence (noise)
- Defaulting to 🟢 to look confident — the bar is *verified this turn*, not *I'm pretty sure*
- 🔴 honesty > 🟢 dishonesty
