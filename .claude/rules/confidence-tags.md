---
name: Confidence tags on substantive claims
always: true
---

# Confidence tags

Tag substantive factual claims so the user can see what's grounded vs assumed.

## Tags

- 🟢 **verified** — read the source / confirmed / ran the command **this turn**
- 🟡 **medium** — in memory or prior context; not freshly checked
- 🔴 **unverified** — assumed or extrapolated, with no source this turn. Needs a check before acting. (Not "bad" — see below.)

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

## Coloured circles mean CONFIDENCE only — status uses ✅ ⚠️ ❌

Added 2026-10-08 after user feedback: a red circle was being used both for "unverified" and for "bad /
failing / missing", so a reader could not tell a guess from a problem. Users found it confusing.

| You are saying… | Use | Never |
|---|---|---|
| how sure you are of a claim | 🟢 verified · 🟡 from memory · 🔴 unverified | — |
| whether a thing is good or bad | ✅ passing / done · ⚠️ needs attention / open / partial · ❌ failing / missing / blocked | a coloured circle |

- Severity scales (blocking / amber / green, pass / warn / fail, RED / YELLOW / GREEN clause tags) are
  **status** → ❌ / ⚠️ / ✅.
- Urgent, overdue or open items are **status** → ⚠️ / ❌, not 🔴.
- The two combine: `❌ 3 tests failed 🟢` is a bad result you verified; `⚠️ owner may have changed 🔴` is an
  open item you haven't checked.

## Anti-patterns

- Tagging every sentence (noise)
- Defaulting to 🟢 to look confident — the bar is *verified this turn*, not *I'm pretty sure*
- 🔴 honesty > 🟢 dishonesty
