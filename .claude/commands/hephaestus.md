---
description: "Hephaestus — the tune-up seat (god of the forge; keeps your harness + vault in working order). One door to maintenance: a TUNE-UP that runs the health + hygiene detectors and synthesises ONE prioritised 'what's broken / what's messy / what could be better' report — instead of remembering six chores. Routes to harness-doctor / score-vault / vault-lint / harness-improve / curate-skills / telemetry-summary / harness-watch-review. Surfaces + proposes; never auto-fixes."
argument-hint: "[tune-up | health | hygiene | improve | curate | telemetry | watch-review]  (default: tune-up)"
allowed-tools: Read, Grep, Glob, Skill
---

# /hephaestus — the tune-up seat

**One door to keeping the workshop in order.** Instead of remembering to run the
doctor, then score-vault, then vault-lint, then check for improvements, you ask
Hephaestus for a **tune-up** and get **one prioritised report**: what's broken, what's
messy, what could be better — most-impactful first, with the exact command to fix
each. He's the *maintenance/health* seat alongside Athena (knowledge), Helios (your
day), Prometheus (the outside world), and Calliope (your outbound).

The verbs keep working standalone — they ARE his modes. Additive front door.

## Input
$ARGUMENTS

Parse a leading mode word. **Default `tune-up`** — the compound synthesis.

## Modes

| Mode | What happens |
|---|---|
| `tune-up` (default) | **The compound value** — run the read-only health + hygiene detectors, then synthesise ONE prioritised report (see recipe). Not six dumps. |
| `health` | Delegate to `/harness-doctor` (health detectors + coverage self-report). |
| `hygiene` | Delegate to `/score-vault` (+ `/vault-lint` for content-graph links/tags). |
| `improve` | Delegate to `/harness-improve` (where the harness could do what it does *better*). |
| `curate` | Delegate to `/curate-skills` (archive stale/dormant skills, reversible). |
| `telemetry` | Delegate to `/telemetry-summary` (hook counts / tokens / cost over N days). |
| `watch-review` | Delegate to `/harness-watch-review` (review a shadow window for promote/kill). |

## The tune-up — run, then synthesise (this is the value)

1. **Health** — `/harness-doctor`: what's broken or blind (failed detectors, static-validity
   breaks, capture/scheduled-task health, coverage blind spots).
2. **Hygiene** — `/score-vault` (harness-surface hygiene score + findings) + `/vault-lint`
   (broken authored links + tag-taxonomy drift).
3. **Could-be-better** — surface the *headline* `/harness-improve` opportunities +
   `/curate-skills` dormant candidates (name them; don't run the deep survey unless asked).
4. **The one report** — a single prioritised list, most-impactful first, in three bands:
   - **Broken** → fix now (with the command).
   - **Messy** → clean up (with the command).
   - **Could improve** → consider (point at `/harness-improve` / `/curate-skills` / `/promote-rule`).
   End with the **single highest-value fix** to do first. A tune-up report no individual
   command gives you.

## Where the detectors actually run (load-bearing)

The tune-up executes its detectors **in this command's main-context run** (which has
the shell). If ever driven from an isolated sub-agent with no Bash, `Skill` only
loads a detector's instructions — it can't execute the Python — so a detector may
not run. **If a detector can't run, report the gap; never infer or hand-simulate its
findings and present them as detector output.**

## Surface, never auto-fix (load-bearing)

Hephaestus **reports and proposes** — he does not apply fixes, archive skills, promote
rules, or rewrite anything. Each item names the command *you* run to act. This mirrors
the self-healing discipline (surface-not-autofix) and Athena/Helios's human-gate.
There is no auto-apply path in Charon: every fix is yours to run deliberately.

## When NOT to use

- **Find/relate/record knowledge** → Athena (`/athena`).
- **Your day / triage / todo** → Helios (`/helios`).
- **Security-review some code** → `/review`.
- **Actually applying a fix** → run the command Hephaestus names. He surfaces the need
  and the remedy; the apply is always your deliberate step, never his.

## Backward-compat (nothing removed)

`/harness-doctor`, `/harness-improve`, `/harness-watch-review`, `/score-vault`,
`/vault-lint`, `/curate-skills`, `/telemetry-summary` all keep working unchanged — they
ARE Hephaestus's modes. Additive front door.

## Co-change couplings

- New health/hygiene/improvement verb → add a row here + the agent persona (`.claude/agents/hephaestus.md`).
- Seat pattern: exemplar #3 after Athena (`/athena`) and Helios (`/helios`).
