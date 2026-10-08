---
description: "Human-gated auto-heal (PROPOSE-ONLY). Surface a pre-approved, reversible fix for a detected harness issue: validate it against a closed list, check its preconditions, and report. Executes nothing in this release."
argument-hint: "[--list | <remediation-id>]  e.g. /harness-heal R1-capture-rerun"
allowed-tools: Bash(python scripts/harness_autoheal.py *), Read
---

# /harness-heal — human-gated auto-heal (propose-only)

The last step of the self-healing loop, for a **small, pre-approved** set of fixes: the watch
detects → this surfaces a proposal → you approve → apply from a **closed list** → deterministic
post-check → confirm, or roll back and escalate.

**This release is propose-only.** `scripts/harness_autoheal.py` runs with `PROPOSE_ONLY = True`:
`apply()` executes **nothing** — it records the request and returns. The live apply path is
deliberately not implemented; it will be built behind its own security review once propose-only
use has produced real evidence.

**observe ≠ act:** the harness watch is read-only and never calls this module. Auto-heal is
reachable **only** through this command, run by you.

## Usage

- `/harness-heal` or `/harness-heal --list` → the allowlisted remediations and the
  `PROPOSE_ONLY` state.
- `/harness-heal <remediation-id>` → validate it against the closed list, run the never-auto
  check and the precondition gate, and report whether preconditions are met. **Takes no action.**

Wraps `python scripts/harness_autoheal.py` (`--list` / `--propose <id>`). Never compose commands:
`scripts/harness-autoheal-allowlist.json` is the only source of fixes.

## The remediation list (closed)

| id | Trigger | Action | Post-check | Reversibility |
|---|---|---|---|---|
| `R1-capture-rerun` | `capture-gap` | re-run your scheduled capture (`scheduled-capture.bat` / `.sh`) | `captured.json` mtime advanced | additive, no rollback needed |

Preconditions checked first: no `REAUTH-NEEDED.flag` (auth healthy) and no `fetch-mail.lock`
(not already running).

## Controls (in code, not convention)

1. **Closed list** — no model-composed commands, ever.
2. **Precondition gate** — re-checked at apply time.
3. **Per-apply human approval.**
4. **Deterministic post-check, no blind retry.**
5. **Reversible only** — no safe rollback means not eligible.
6. **Append-only audit** — one `state/verdict/*.jsonl` line per propose/apply.
7. **Hard-coded never-auto list** — re-auth, service restarts, secrets, memory / CLAUDE.md /
   rules, payroll and board-facing data are refused even if listed.

## When NOT to use

- **For a fix that isn't on the list** — out of scope by design. Add one by a deliberate edit,
  then `/secure-code-review` it.
- **To restart a service, re-auth, or edit memory, rules or secrets** — hard-blocked.
- **As the detector** — that's `/harness-doctor` and the scheduled watch.

## Co-change couplings

- Add or rename a remediation → `/secure-code-review` it, and keep `trigger_rule` matching a rule
  the watch emits.
- Any future live apply path → its own review gate before `PROPOSE_ONLY` changes.
