---
type: reference
title: Design Contract Template (DESIGN.md-style)
created: 2026-07-16
source: "Schema adapted from nexu-io/open-design DESIGN.md (github.com/nexu-io/open-design, Apache-2.0). A11y floor, design-dials intake, and CSV pointers are harness additions. Attribution recorded in the root NOTICE."
scope: "Fill one per real surface — a dashboard, a landing/marketing page, a web app, a recurring Artifact family. The committed 'this IS our look' contract an agent renders to."
tags: [reference/design, convention/frontend]
---

# Design Contract Template — `DESIGN.md` for one surface

**What this is.** A *brand contract*: one file that **commits** to a single coherent look for
**one surface**, so a coding agent (or a design tool) renders in-brand without re-choosing every
build. This is the **commitment layer** — the counterpart to
[`design-system-reference.md`](design-system-reference.md), which is the **selection layer** (how
to *choose* a good look + the a11y floor). Workflow: **choose using the reference/CSVs → pin the
choices here → hand this file to the build.**

**How to use.** Copy this file next to the surface it governs (a repo, a project folder), rename it
`DESIGN.md`, and fill every `‹placeholder›`. Delete the guidance blockquotes once filled. One
surface = one contract; don't try to make one file serve dashboards *and* marketing.

> **Non-negotiable, every contract:** the [Universal UX checklist](design-system-reference.md#universal-ux-checklist)
> is baked in below as hard floor — WCAG AA minimum, never colour alone, visible focus rings,
> `prefers-reduced-motion` honoured. A contract may raise the bar; it may never drop below it.

---

## 0. Design dials (intake)

Set these first — they constrain everything downstream.

- **DESIGN_VARIANCE:** ‹1–10› — 1 safe/conventional → 10 bold/experimental. *(data/reporting surfaces sit low; marketing can push higher)*
- **MOTION_INTENSITY:** ‹1–10› — 1 near-static → 10 lively. Caps how much motion §7 allows. *(dashboards low; landing pages mid)*
- **VISUAL_DENSITY:** ‹1–10› — 1 airy/whitespace → 10 dense/data-rich. *(data dashboards high; marketing low)*

## 1. Surface & intent

- **Surface:** ‹what this is — e.g. "analytics dashboard"›
- **Audience:** ‹who reads it›
- **One-line intent:** ‹the feeling + job in a sentence›
- **A11y target:** WCAG **AA** floor (AAA on primary text/contrast where it matters). ‹note any raise›

## 2. Colour palette & roles

> Copy a **whole row** from `design-system-data/colors.csv` (WCAG-adjusted). Don't hand-pick two colours.

| Role | Value | Contrast note |
|---|---|---|
| Background | ‹#hex› | |
| Foreground / text | ‹#hex› | ≥ 4.5:1 on bg |
| Primary | ‹#hex› | |
| On-primary | ‹#hex› | ≥ 4.5:1 on primary |
| Secondary / accent | ‹#hex› | |
| Card / surface | ‹#hex› | |
| Muted / border | ‹#hex› | |
| Destructive | ‹#hex› | pair with icon/text — **never colour alone** |
| Focus ring | ‹#hex› | visible on every interactive element |

**Status-state rule:** every status (ok/warn/critical) is **colour + icon + text**, never colour
alone — the dashboard-relevant a11y floor.

## 3. Typography

> From `design-system-data/typography.csv` — filter *Best For* to your context. Each row ships a
> Google-Fonts URL + Tailwind config.

- **Headings:** ‹font› — scale ‹e.g. 40/32/24/20/16›
- **Body:** ‹font› — 16px min, line-height **1.5–1.75**, measure **65–75ch** (`max-w-prose`)
- **Mono (if any):** ‹font›
- **Tailwind `fontFamily`:** ‹paste config›

## 4. Components

Specify the recurring components. Each gets: radius, shadow/elevation, and **all states incl. focus + disabled**.

- **Buttons:** ‹radius / padding / primary+secondary / hover / focus-ring / disabled `opacity-50 cursor-not-allowed`›
- **Cards / stat tiles:** ‹radius / border / elevation level›
- **Inputs:** ‹visible label always (placeholder ≠ label) / error message beside field / focus ring›
- **Nav:** ‹pattern›
- **Status pills / badges:** ‹colour+icon+text per §2 rule›

## 5. Layout & spacing

- **Spacing scale:** ‹8px base recommended›
- **Container width:** ‹e.g. ~1200px›
- **Grid:** ‹columns / gutters›
- **Density:** honour VISUAL_DENSITY from §0

## 6. Depth & elevation

- **Elevation levels:** ‹0 flat → n; shadow tokens or ring-based›
- **Rule:** consistent levels; don't invent one-off shadows per component.

## 7. Motion

> Gate everything by MOTION_INTENSITY (§0). Use [`motion-presets.md`](motion-presets.md) (zero-dep,
> reduced-motion baked in) and the tiers in `design-system-data/motion.csv`, not ad-hoc animation.

- **Allowed presets / tier:** ‹list from motion-presets by interaction, capped by §0›
- **Floor:** 150–300ms micro-interactions; **`transform`/`opacity` only**; 1–2 animated elements
  per view max; `prefers-reduced-motion` honoured.

## 8. Data-viz defaults *(if the surface shows data)*

> Pin the defaults so charts don't get re-litigated per build.

- **Default chart types:** ‹bar / bullet-grid / gauge / waterfall / line — all AA/AAA & table-friendly›
- **Rule:** pick by the *question* via [Chart selection](design-system-reference.md#chart-selection-quick-reference);
  any C/D-grade chart (pie/treemap/network/…) ships a table+% fallback or isn't the primary view.

## 9. Do's & Don'ts (anti-patterns)

> Include the chosen style's **"Do Not Use For"** from `design-system-data/styles.csv`.

**Do:** ‹surface-specific›
**Don't:** ‹surface-specific — e.g. "no glassmorphism on dense tables"; "no cool blues if warm-brand"›

## 10. Agent prompt guide

The standing instruction to hand the agent, plus worked examples — this is what makes the contract
*operable*.

> **System line:** "Render to this `DESIGN.md`. Honour every token, the a11y floor, and the design
> dials. If a request conflicts with the contract, flag it — don't silently override. Build tool:
> `frontend-design` skill; load `artifact-design` before any Artifact."

**Example prompts:**
- ‹"Build the KPI row — 4 stat tiles per §4, status via colour+icon+text per §2."›
- ‹"Landing hero per §1 intent, VARIANCE from §0, motion capped per §7."›

---

## See also

- [`design-system-reference.md`](design-system-reference.md) — the selection layer this contract draws from (CSVs, chart a11y, UX floor)
- [`motion-presets.md`](motion-presets.md) — the allowed-motion source for §7
- `feedback_visual_design_workflow` (memory template) — reference-images-first + clarify-before-build; this contract is the *output* of that clarify step
- `frontend-design` / `artifact-design` skills — the build tools §10 hands off to
