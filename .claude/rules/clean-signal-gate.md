---
keywords:
  - self-healing
  - self-improving
  - auto-heal
  - autonomous loop
  - learning loop
  - self-correct
  - MAPE
  - agentic loop
---

# Clean-signal gate

Auto-loaded when working on autonomous/agentic loops (self-healing, self-improving,
learning loops). This is the governance rule behind every self-* capability in
Charon — read it *before* building or extending a loop, not after.

Keyword-gated by default so it fires on the work regardless of where your project
folders live. Add a `paths:` block if you want it to fire on a specific directory too.

## The gate (apply before building or extending ANY autonomous loop)

**No loop runs on an unverified signal.** First question, every time: *what is the
signal, and is it verified?* If it is not verified → the work in front of you is
"fix the signal," not "build the loop."

| Loop type | Requirement |
|---|---|
| **Self-healing** (auto-action) | The failure mode must be **idempotent + reversible**; success is confirmed by a **deterministic post-check**, never the model's own say-so. Never auto: credential re-auth, service restarts, content mutation. |
| **Self-improving** (learning) | Must learn only from a **verified ground-truth source**. An unverified or own-output signal produces model collapse and self-reinforcing poisoning. |

## Why (research-grounded)

- LLMs cannot reliably self-correct without **external verification**.
- Training on own/unverified output → **model collapse / data autophagy**.
- Learning from poisoned input → a **self-reinforcing poisoning loop**, very hard to
  break once established.
- Blast radius scales with the system: the more action-capable or regulated the
  system, the more non-negotiable the gate.

## How to tell a clean signal from a dirty one

| Signal | Verdict | Why |
|---|---|---|
| A deterministic filesystem/CI fact — a test passed, a scheduled job ran, a flag cleared, a hygiene finding count | **PASSES** — safe to build a loop on | No model judgement anywhere in the signal; the post-check can be equally deterministic ("did the recurrence rate fall?"). |
| The model's own assessment of its own output ("I think that was better") | **FAILS** | This is the autophagy case. Never learn from it. |
| A human-adoption or usage metric where the underlying process is known-broken | **FAILS** — fix the process first | The metric measures the broken process, so the loop would faithfully learn the wrong lesson. Repair the signal, then revisit. |

The cleanest loops are the ones where **both** the input signal and the post-check
are deterministic. Prefer those for a first loop — they prove the machinery on a
signal nobody can argue with.

## Pairs with

- `verdict-vocabulary.md` — the shadow-before-enforce companion discipline: a new
  rule observes before it acts, so you learn its false-positive rate before it bites.
- `thoroughness-over-false-efficiency.md` — never trim a verification step to save
  tokens; the verification is what makes the loop safe.
- `/harness-doctor` (detect) and `/harness-improve` (propose) — the human-gated
  primitives this rule governs. Both surface and propose; neither auto-applies.
