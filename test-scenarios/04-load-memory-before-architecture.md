---
id: 04
slug: load-memory-before-architecture
category: identity-architecture
tests: session-start-ritual memory load before architecture answer
setup_required: yes
---

# 04 — Load memory before architecture answer

## Setup

Place a memory file at `<HARNESS_MEMORY_ROOT>/reference_identity_architecture.md` with content that overrides the training-data default. Example:

```markdown
---
name: Identity architecture
description: How users authenticate across the user's org-units
type: reference
---
# Identity architecture

Each org-unit runs its own OAuth provider (Entra / Google Workspace / Okta — varies by unit). **There is no central IdP across all org-units.** Cross-unit access uses one of:

- Multi-tenant OAuth apps with per-unit consent
- B2B guest invitations between unit tenants
- Per-unit signing keys + token exchange

The federated reality is non-obvious from training data — central-IdP is the natural assumption. This file exists to override that default.
```

Also add a line to `MEMORY.md`:
```
- [Identity architecture](reference_identity_architecture.md) — federated, not central
```

## Prompt

> "I'm building a tool that needs to authenticate users across all my org-units. Walk me through the identity flow."

## Pass criteria

- Returns: "Your org-units are **federated** — each runs its own identity provider. There is no central tenant to sign into."
- Cites `reference_identity_architecture.md`.
- Discusses real cross-unit options: multi-tenant OAuth app / B2B guest / per-unit signing keys.
- Confidence 🟢 (read memory this turn) or 🟡 (in prior session context).

## Fail criteria

- Describes a central-IdP / SSO flow as if a central tenant exists.
- Returns Entra/Okta/Auth0 flow without acknowledging the federated reality.
- Returns the answer without citing the memory file.
- Proposes a single-tenant solution as the primary path.

## Partial credit

- Acknowledges federation but doesn't surface the multiple cross-unit options: **PARTIAL**.
- Cites memory but uses central-IdP framing as the recommended path: **PARTIAL FAIL**.

## Why this scenario exists

Identity architecture for cross-unit controls is a recurring question (governance tooling, dashboards, exposure monitoring). The federated reality is non-obvious from training data — central-IdP is the default training-data assumption. Memory exists specifically to override that default. Tests whether the override fires.

## Cleanup

Remove `reference_identity_architecture.md` and the MEMORY.md line after the run.
