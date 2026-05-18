---
name: Save operational facts in the same turn — don't batch
always: true
---

# Save on mention — same turn, not end of session

When the user states an operational fact, **write to the right memory file in the same turn**. Acknowledge in one clause: *"saving the X rule to Y now"*. Never batch. Never wait for end of session.

## Triggers (any of these → write before turn ends)

- Username / hostname / IP / port / path / password
- Service-restart sequence ("restart X" / "Y also needs restart")
- Deploy gotcha ("this broke because…")
- Workflow rule ("from now on…" / "always…" / "never…" / "for me personally…")
- Degraded mode / temporary state
- Named bug / incident

## Where to write

| Fact type | Destination |
|---|---|
| Operational system fact | Project's `CLAUDE.md` |
| Cross-cutting workflow rule | `feedback_*.md` in memory |
| Time-bound project state | `project_*.md` with absolute date |
| Credential | **Never plaintext.** Store in a secrets directory (default `~/.secrets/<name>.json`); memory / CLAUDE.md *points at it*, never quotes it |

**Co-change:** new memory file → `MEMORY.md` index update same turn (orphaned files don't fire).

**Tags:** if the `save-on-mention.py` hook surfaces them, render inline at top of body: `Tags: [env] [convention]`. Allowed: `correction` / `gotcha` / `fix` / `pattern` / `env` / `convention`. Max 3 per fact.

Distinct from `scripts/hooks/save-on-mention.py` (detection sidecar) — the .md rule is the behavioural discipline; the .py is the candidate-detection layer.
