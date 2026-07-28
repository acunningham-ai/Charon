---
name: Thoroughness over false efficiency
keywords:
  - "false efficiency"
  - "efficiency"
  - "trim"
  - "streamline"
  - "condense"
  - "shorten"
  - "save tokens"
  - "reduce tokens"
  - "fewer tokens"
---

# Thoroughness over false efficiency

Completeness and reliability come before token/step "efficiency." Never trade the
quality that matters — not missing a trigger, not forgetting context, being
thorough — for a cheap saving. Call that **false efficiency**.

## Apply

- Don't trim, gate, or skip always-on discipline (the `always: true` rules,
  session-start context loading, save-on-mention, verification/validation passes)
  to save tokens or steps. Their recurring cost is the price of never missing a
  trigger — worth paying.
- A saving is acceptable **only if it is provably lossless** — no directive,
  trigger, or check removed. If you can't prove it's lossless, keep the fuller
  version.
- When efficiency and completeness conflict, default to completeness and say so.

## Why

The harness earns its value by not dropping context or triggers. A saving that
shaves reliability off that guarantee is a net loss — optimising a cheap metric
(tokens) at the expense of the one that matters (thoroughness).
