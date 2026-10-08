---
description: Turn a logged harness FAILURE into a decision-ready {root cause + ranked fix options} note under 00-Inbox/_harness/. Surface-only — you decide with /harness-fix, and /harness-heal names a pre-approved fix where one fits. You run it; nothing schedules it.
argument-hint: "[--drain | --event <id> | --selftest | --dry-run | --seal]"
allowed-tools: Bash(python scripts/harness_autoreview.py *), Read, Glob
---

# /harness-review — review the harness's own failures

The review step of the self-healing loop:

> failure → **review** → ranked options → **you pick** (`/harness-fix`) → gated apply → monitor

`/harness-doctor` runs the read-only detectors; `/harness-heal` is the gated apply. This sits
between them: it takes a **logged failure** and produces an evidence-cited root cause plus 2–4
ranked fix options, so you choose a fix instead of diagnosing from scratch.

**You run it.** Every failed scheduled run is queued automatically by `scripts/hooks/on-error.py`
(`ENQUEUE_REVIEW = True`), but nothing reviews the queue until you run `/harness-review --drain`.
The harness watch tells you when the queue has backed up (`review-queue-backlog`).

## observe ≠ act

The engine is **surface-only**: it writes ONE note per failure and takes no action. It may NAME a
pre-approved remediation id, but it **never imports or calls** the apply module
(`harness_autoheal.py`). `--selftest` proves that by parsing its own source.

## Modes

| Command | What it does |
|---|---|
| `/harness-review --drain` | Review pending queued failures (5 per run; any deferred are named, not dropped). Near-identical failures in the same hour are reviewed once. |
| `/harness-review --event <id>` | Review one queued failure by `event_id`. |
| `/harness-review --dry-run` | Show what would be reviewed; invoke nothing. |
| `/harness-review --selftest` | Assert observe ≠ act (no apply-module import). |
| `/harness-review --seal` | Record the hashes of the three control files (one-time setup, and after any deliberate edit to them). |

## First-time setup

The engine refuses to run until its control files are sealed. Read the three files in
`scripts/harness-review/` (the prompt, the write allowlist, the read-deny settings), then:

```
python scripts/harness_autoreview.py --seal
```

The hashes go to your secrets dir, outside the repo, so a tampered control file can't also rewrite
its own expected hash. Re-seal after any deliberate edit; an unexpected mismatch means don't run it.

## Each review is a hardened, unattended `claude -p`

- **C-1** hardened prompt (`scripts/harness-review/harness-review.txt`): the failing log tail is
  treated as UNTRUSTED data, protected files are named, one output target.
- **C-2** tools limited to `Read Write Glob Grep` (no Bash, web, agents or MCP).
- **C-3** write-path allowlist: it can only write `00-Inbox/_harness/*-review-*.md`.
- **C-4** `$1.50` budget and 420 s timeout per failure; 5 per drain.
- **C-5** post-run audit, plus a run-scoped read-deny layer (`~/.secrets`, `~/.ssh`, `~/.aws`,
  settings, CLAUDE.md, rules).

## Output

`00-Inbox/_harness/<date>-review-<event_id>.md` (`type: harness-auto-review`,
`trust: harness-generated`) with **What failed · Root cause · Ranked fix options ·
Recommendation**. Decide on it with `/harness-fix`.

## When NOT to use

- **To apply a fix** → `/harness-fix` records your decision; `/harness-heal` is the gated apply.
- **To scan for what's broken now** → `/harness-doctor`.
- **To find what could be better** (not a failure) → `/harness-improve`.

## Co-change couplings

- A remediation added to `scripts/harness-autoheal-allowlist.json` appears in the engine's
  reference list automatically.
- Any change to the engine or its control files → `/secure-code-review` + `/owasp-agentic-review`
  + `/owasp-llm-review` first (an unattended model on the failure path is the highest bar), then
  re-seal.
