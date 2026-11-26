---
type: framework
topic: Insight schema for synthesised output
slug: insight-schema
status: current
---

# Insight schema — typed, sourced, confidence-rated synthesis output

## What this is

The schema every synthesis pass emits alongside its prose. It is the canonical way `/weekly-checkin`, `/eod-reflect`, `/knowledge-consolidate`, and any future synthesis command produce output that is **machine-parseable**, **traceably sourced**, and **confidence-rated**.

It exists for defensibility. A claim you put in front of a manager, an auditor or a board needs a stated source and a stated confidence — otherwise it isn't a position, it's an opinion. The schema makes that discipline structural rather than aspirational.

The `type` taxonomy and the confidence/importance metadata are adapted from patterns in public second-brain projects (a typed insight taxonomy, and the "confidence metadata on every claim" convention popularised by long-form essay sites).

## The schema

Every synthesised insight is emitted as a fenced YAML block immediately preceding its prose explanation:

```yaml
insight:
  type: pattern | trend | anomaly | recommendation | summary
  confidence: log | likely | certain | speculative
  importance: 1-10
  sources:
    - path/to/source1.md
    - path/to/source2.md
```

Then the prose that explains the insight follows below the block.

These are **constrained enums**: a command that emits an `insight:` block uses only the values below. An invented value (`type: observation`, `confidence: high`) is a defect, not a variant.

### Field definitions

**`type`** — what kind of insight this is:

| Value | Meaning |
|---|---|
| `pattern` | A recurring shape across 3+ signals. The default for cross-domain themes. |
| `trend` | A directional movement over time (rising, falling, accelerating, decaying). |
| `anomaly` | An atypical signal. Either an unexpected presence OR an unexpected absence (silence/drift). |
| `recommendation` | A proposed action. Says WHO would action it (if known), or that it is the user's own. |
| `summary` | A capsule of an underlying topic. Use sparingly — most output should be one of the above four. |

**`confidence`** — how strongly the insight is supported:

| Value | Meaning |
|---|---|
| `log` | Observation only, no claim attached. The insight is "this happened" without interpretation. |
| `likely` | Probable based on current evidence. Reasonable inference; could be wrong. |
| `certain` | Established fact. Multiple corroborating sources, no reasonable alternative reading. |
| `speculative` | Extrapolation beyond the evidence. Surfaced because it's worth considering, not because it's supported. Use sparingly. |

**`importance`** — 1–10 integer:

| Range | Meaning |
|---|---|
| 9–10 | Critical. Board-level, regulator-level, or imminent-decision-level relevance. |
| 7–8 | High. Affects active project posture or near-term planning. |
| 4–6 | Medium. Useful context; carry forward. |
| 1–3 | Low. Logged for future synthesis; not actively interesting today. |

**`sources`** — list of vault-relative paths. Every insight MUST cite at least one source. Synthesis with no source is opinion, not insight; `sources: []` is rejected.

## Inline citations in prose

When the prose makes a claim that draws on a source, use the markdown link form. Template form uses angle-bracket placeholders, which `/score-vault` deliberately ignores:

> `The harness ships a baseline of injection-resistance controls — see the [security baselines framework](<path>) for the full list.`

A real example pointing at an actual vault doc:

> `The harness ships a baseline of injection-resistance controls — see the [security baselines framework](security-baselines.md) for the full list.`

The link target is the source path; the link title (`"..."` after the path, optional) can carry human context. This makes the citation:

- Machine-parseable (a script can walk all link targets and verify they resolve)
- Reader-legible (the prose still reads naturally)
- Source-rot detectable (broken links surface in `/score-vault`)

## Inline confidence tagging (prose output)

Beyond the YAML insight blocks, **prose findings in command output are tagged inline** with a confidence marker, per `.claude/rules/confidence-tags.md`. The markers mean **confidence only** — how sure you are of a claim — never whether a thing is good or bad (status uses ✅ ⚠️ ❌).

| Marker | Meaning | When to use |
|---|---|---|
| 🟢 | **Verified** — read the source, confirmed, or ran the command **this turn** | The finding cites a specific file / line / value you read just now. The reader can re-derive it. |
| 🟡 | **From memory** — in memory or prior context; not freshly checked | The finding comes from what was known before this turn, or from triangulating sources you didn't re-open. |
| 🔴 | **Unverified** — assumed or extrapolated, with no source this turn | The finding is plausible but not directly supported. The reader should check before acting. |

Place the marker at the end of the sentence or the start of the bullet:

> 🟢 The release gate reported 37 PASS / 0 FAIL on this morning's run (read from the run log).
>
> 🟡 The failure rate rose after the dependency bump last month — that's from last week's notes, not re-checked today.
>
> 🔴 The spike is probably the new retry logic — not yet confirmed; check the retry counters before acting.

**Why this matters:** an assistant that silently infers things the reader thinks were verified is worse than one that says "I don't know". Inline markers make the verified / remembered / assumed boundary visible at a glance, without re-reading sources.

**When to skip:** trivial status lines (one-line confirmations like "Captured 12 items to 00-Inbox/") don't need tagging. Tag findings, recommendations and judgements — not status messages.

## Where to use the schema

| Command / output | Insight block required? | Inline citations required? |
|---|---|---|
| `/weekly-checkin` (interactive + scheduled) | Yes — one block per item under Themes / Convergences / Drift / Anomalies / Recommendations | Yes |
| `/eod-reflect` | Yes — one block per section that has signal | Yes |
| `/knowledge-consolidate` (framework docs) | Yes — one block per item under Key decisions / conventions; one per Open question that carries a confidence/importance | Yes |
| Authored docs in `06-Decisions/` | Recommended (a decision is an insight: `type: recommendation`, with explicit confidence + importance) | Yes |
| Authored docs in `07-References/` | Recommended for the synthesised claims; not required for structural prose | Yes |
| Daily TODO (`TODO.md`) | No — a TODO is action-shaped, not insight-shaped | Cite source paths in the bullet |
| Captured content (`00-Inbox/_captured/**`) | No — captured content is data, not synthesis | N/A |

## Worked example

A `/weekly-checkin` entry under "Convergences (cross-domain)":

````markdown
## Convergences (cross-domain)

```yaml
insight:
  type: pattern
  confidence: likely
  importance: 7
  sources:
    - 00-Inbox/_captured/email/2026-05/2026-05-08_vendor-advisory-agent-tooling.md
    - 00-Inbox/_captured/email/2026-05/2026-05-08_platform-outage-agent-traffic.md
    - 08-Projects/Tool-Governance/forum-agenda-DRAFT.md
```

**A vendor advisory on agent tooling, a platform outage blamed on agent traffic, and this month's governance agenda all converge on agentic-AI supply-chain risk** as the dominant topic of the week. Expect it to dominate the next governance forum; the three sources support it independently.
````

## How `/score-vault` audits this

`/score-vault` walks `06-Decisions/*.md` and `07-References/*.md` for markdown link references (`[text](<path>)` form). For each:

- Internal vault path → verify the file exists. Broken → MEDIUM finding.
- External URL → skipped (URL-rot detection is a separate pass).
- Anchor-only link (`[text](#anchor)`) → skipped.

The audit does NOT inspect insight-block YAML directly — that's a content-quality question, not a structural one. A content audit (e.g. "this `certain` insight has only one source") is a possible future extension.

## Related

- `07-References/security-baselines.md` — defines the controls; this doc defines the *content shape* that flows through them.
- `.claude/rules/confidence-tags.md` — the inline-marker rule this schema's prose convention follows.
