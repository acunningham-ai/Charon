---
name: harness-fix
description: Decide on a harness review's fix options — read the ranked options, pick one, and put it at the top of the dev queue. Records declines too, so a closed item stops coming back. Queues work; executes nothing.
argument-hint: "[--list | --queue | <event-id> <option-number>]  e.g. /harness-fix 20261002071500-scheduled-capture 1"
allowed-tools: Bash(python scripts/harness_fix.py *), Read
---

# /harness-fix — approve a harness fix

The decision stage of the self-healing loop. A failure is queued by `on-error.py`, reviewed into
a `{root cause + ranked options + trade-offs}` note by `/harness-review` — and this is where you
answer it.

## What it does NOT do

**Nothing is executed. Ever.** Accepting an option records the decision and puts it at the top of
the dev queue; a session then implements it under the normal gates (tests, `/secure-code-review`,
the write gates).

That's deliberate. Pre-approved remediations are canned *recovery* actions on a closed list. A
novel code fix ("change line 281 to `process.exitCode`") can never be on that list, because the
list has to exist before the failure does. This path does not import the auto-heal module.

## Usage

| Intent | Command |
|---|---|
| What needs my call? | `python scripts/harness_fix.py --list` |
| Approve option N | `python scripts/harness_fix.py --accept <event-id> --option N --note "why"` |
| Not worth doing | `python scripts/harness_fix.py --decline <event-id> --note "why"` |
| Not now, ask again later | `python scripts/harness_fix.py --defer <event-id>` |
| What's queued? | `python scripts/harness_fix.py --queue` |
| I implemented it | `python scripts/harness_fix.py --done <event-id>` |
| A block for your TODO | `python scripts/harness_fix.py --todo-block` |

With no arguments, run `--list`, then **read the note for each open proposal** before
summarising — the one-line recommendation is a pointer, not the argument. Present the options with
their trade-offs, say which you'd take and why, then wait for the user's pick. Never accept on
their behalf. If the user names an option conversationally ("take option 1 on the capture one"),
run the `--accept` and confirm what was queued.

## After an accept

Implementing it is ordinary work: read the option, make the change, test it, mark `--done`. The
note is a proposal a model wrote from a log, not authorisation to skip review — re-read the cited
file:line before changing it.

Decisions are kept in `state/harness-fixes/decisions.jsonl` (last write wins, so you can change
your mind).
