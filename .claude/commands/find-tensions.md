---
description: "Surface CONTRADICTIONS across vault notes on a topic — where two sources assert incompatible facts (dates/numbers/verdicts). Writes a `type: tension` note citing BOTH sources; never averages, never picks a winner, never edits the sources. You resolve."
argument-hint: "<topic to check for contradictions> (or run right after /knowledge-consolidate on the same topic)"
allowed-tools: Read, Grep, Glob, Write, Bash(python scripts/recall.py:*)
---

# /find-tensions — surface contradictions in the corpus

Finds where the vault **disagrees with itself** on a topic — two notes asserting
incompatible facts (a date, a number, a verdict, an ownership) — and records each
as a `type: tension` note that cites both sources side by side. It **surfaces**,
never resolves: contradictions are for you to adjudicate, never silently averaged
away.

## Process

1. **Gather sources.** `python scripts/recall.py "<topic>" --k 12` + a `Grep` for the
   topic's key terms across the authored vault. Collect the candidate notes.
2. **Read them** and extract concrete, checkable claims (dates, figures, verdicts,
   named owners, states) — not vibes.
3. **Find genuine contradictions** — same subject, **incompatible** assertions.
   Different emphasis / scope / point-in-time is NOT a contradiction (a note that
   was true then and is superseded now is a *supersession*, note it as such, not a
   tension). Be conservative: only flag real conflicts.
4. **Write one `type: tension` note per contradiction** to
   `07-References/tensions/<YYYY-MM-DD>-<slug>.md` (create the dir if absent):
   ```yaml
   ---
   type: tension
   topic: "<topic>"
   status: open            # open | resolved
   sources: ["<path A>", "<path B>"]
   date: <YYYY-MM-DD>      # computer time is authority
   ---
   ```
   Body: **Claim A** (path A, quoted) · **Claim B** (path B, quoted) · **Why they
   conflict** · **Not resolved here — surfaced for you.** Never state a winner.
5. **If none found, say so** — do not manufacture a tension to look useful.
6. **Report** the tensions found with paths; leave resolution to you.

## Output artifacts

- `07-References/tensions/<date>-<slug>.md` per contradiction (`type: tension`).
- NEVER edits the source notes. NEVER sets `status: resolved` itself.

## When NOT to use

- **Synthesise a topic into a framework doc** → `/knowledge-consolidate` (run
  `/find-tensions` as its *follow-on* to catch conflicts in what it synthesised).
- **Stress-test a plan against the record** → `/grill`.
- **Stress-test a decision** → `/devils-advocate`.
- **Rank/find notes** → `/recall`.

## Co-change couplings

- Introduces the **`type: tension`** frontmatter shape → consider teaching
  `/score-vault` + the tag taxonomy to recognise it.
- `/knowledge-consolidate` should offer to run this as a follow-on on the topic it
  just synthesised.
- A resolved tension is your call — when you adjudicate, set `status: resolved`
  and route the correction via `/push-fact` / `/save-feedback`.
