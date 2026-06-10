---
description: "Calliope — the writing seat. Composes the user's outbound writing in their voice across modes (post / bulletin / tweet / email). Drafts only, never sends."
argument-hint: "[mode] \"topic / angle / capture path\"  — e.g. bulletin \"<issue>\" · post \"<topic>\""
allowed-tools: Read, Write, Edit, Glob, Grep, Skill
---

# /calliope — the writing seat

Compose the user's outbound writing **in their voice**. Calliope is the **compose** stage
(Prometheus researches → Calliope writes → a delivery seat delivers). It **drafts only** — never
posts, emails, or sends. Every artefact is a draft for the user's approval.

The `voice`/`post` keywords auto-load the `voice-content` rule — **read it first; it's the voice
spine for every mode**, not just posts. Also load the user's `user_voice.md` profile.

## Input
$ARGUMENTS

Parse a leading **mode** (`post` | `bulletin` | `tweet` | `email`), then the topic / angle /
capture path. If no mode and the request is post-shaped, default to `post`. If nothing given, ask
what to write, or surface candidates from the latest Prometheus digest (`00-Inbox/_research/`).

## Routing

| Mode | What happens |
|---|---|
| `post` | Delegate to `/draft-linkedin` (the tuned drafter). |
| `bulletin` | Stakeholder/org-unit bulletin: advisory + three-things + capability-led (no tool-class except configured exceptions); scaffold `*-responses.md`; flag `PENDING SIGN-OFF`. **Never send.** |
| `tweet` | Inline short-form in the voice spine. |
| `email` | Outbound email draft: three-things up front, collaborative-but-firm. The user sends. |

Full mode rules + the safety-critical bulletin path live in `.claude/agents/calliope.md`. Read it
before drafting in `bulletin` mode.

## Hard rules (recap)
- **Draft only — never send.** Bulletins especially (broad blast radius, human-gated send).
- **Voice spine first** — `voice-content` rule + `user_voice.md` + ≥2 voice anchors.
- **Published artefacts immutable** (configured mutable-field set only).
- **No tool-class mandates** in stakeholder-facing artefacts (except configured exceptions).
- **Cite real events**; `[VERIFY: …]` rather than hallucinate.

## When NOT to use
- Research → `/prometheus` or `deep-research`. Inbox triage → the triage skill. Sending → not
  Calliope (no send capability by design).

## Backward-compat
`/draft-linkedin`, `/linkedin-reply`, `/linkedin-metrics` and any content runners keep working —
they ARE Calliope's `post` mode. Renaming the content folder/runners is optional cosmetic tidy-up.

## Co-change couplings
- New mode → update this file + `.claude/agents/calliope.md`.
- Voice-anchor location → from first-run; reflected in `voice-content`.
