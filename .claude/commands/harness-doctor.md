---
description: On-demand harness self-scan — run every health detector now plus the coverage self-report (what has no detector, which detectors are unverified). Read-only; surfaces issues + ranked fix options, never auto-fixes.
allowed-tools: Bash, Read
---

# /harness-doctor — scan everything now

Runs the harness watch in **doctor mode**: every detector (not just a scheduled
phase's subset) plus the **coverage self-report**, printed inline. The ad-hoc
"is my harness healthy right now?" scan.

Read-only observer. It surfaces issues + ranked fix options; it **never
auto-fixes**. Applying a fix is always a separate, deliberate, human-approved
step — surfacing the problem and the options is the whole job.

## Run

```
python scripts/harness-watch.py --phase post --doctor
```

(Set `HARNESS_VAULT_ROOT` to your vault if you're not running from inside it.)

## Then summarise

1. **Fired detectors** — each with its declared verdict (observe / ask / deny),
   reason, and the `fix_options` from its context. Present the options; the user
   chooses; remediation is human-gated.
2. **Coverage self-report** — inventory counts, **blind spots** (classes
   discovered with no health detector), and **selftests X/Y verified
   fire-capable**.
3. **🔴 STRUCTURALLY DEAD** — a detector whose selftest failed. That is a
   silent-rot bug: the detector can no longer fire. Flag it to fix its
   `_judge`/selftest before trusting its silence.
4. **🟡 unverified** — no selftest. Candidate for a pure `_judge` + fixture so it
   can prove it still fires.

## What it checks (the shipped set, observe-only)

Discovery-driven, so new files of a known class are covered automatically:

- **static validity** — every workflow's `meta.name` matches its filename; every
  harness `.py` compiles (`ast.parse`).
- **config validity** — every command / agent / rule `.md` has valid frontmatter
  and its load-bearing field.
- **capture health** (only when a capture pipeline is configured) — auth-token
  age, capture freshness, TODO refresh, recent automation failures.
- **scheduled-task + process health** (Windows) — a watched task that ran but
  exited non-zero, or a capture process that hung.
- **coverage self-report** — the meta-check: names its own blind spots and proves
  each detector still fires.

## Ships observe-only

Every finding is logged, nothing is enforced, nothing is auto-fixed. Run your own
shadow window, then use **`/harness-watch-review`** to decide which signals to
promote observe → enforcing (populate `PROMOTED_RULES` in `scripts/harness-watch.py`).

## When NOT to use

- Not for remediation — this reports; fixing is a separate, human-approved action.
- Not a substitute for a scheduled pre/post routine if you want a daily record —
  `--doctor` is the ad-hoc scan; wire the script to a scheduled task for a daily
  shadow trail.

## See also

- `scripts/harness-watch.py` — the watch, detectors, and coverage self-report
- `.claude/commands/harness-watch-review.md` — shadow-window promotion call
- `.claude/rules/verdict-vocabulary.md` — the allow/observe/ask/deny schema
