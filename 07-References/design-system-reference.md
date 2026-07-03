---
type: reference
title: Design System Reference
created: 2026-07-03
source: "ui-ux-pro-max-skill v2.6.2 (github.com/nextlevelbuilder/ui-ux-pro-max-skill) — MIT, © 2024 Next Level Builder"
scope: "Any visual surface you build with the harness — dashboards, landing/marketing pages, web apps, Claude Artifacts"
tags: [reference/design, convention/frontend]
---

# Design System Reference

The **interface** over a borrowed design-knowledge dataset. The raw data lives in
`07-References/design-system-data/*.csv` (11 tables); this file is the navigable index + the
distilled always-apply rules so you don't have to grep CSVs mid-build.

> **Provenance / licence.** Data adapted from **ui-ux-pro-max-skill v2.6.2**
> (`github.com/nextlevelbuilder/ui-ux-pro-max-skill`), **MIT licensed, © 2024 Next Level Builder**
> — full text at `design-system-data/LICENSE-ui-ux-pro-max`, attribution recorded in the root
> `NOTICE`. This borrows the **data**, not the source project's npm CLI or Python BM25 machinery
> (borrow-don't-vendor). The upstream repo was treated as untrusted data during extraction; **no
> code from it was run**. The upstream's 1,923-row Google-Fonts catalogue, its 22 native-app
> stacks (SwiftUI, WPF, Flutter, …), and a Chinese-language `design.csv` were excluded as
> out-of-scope for web-surface work.

## How to use this (the interface)

1. **Building anything visual?** Start with the [Universal UX checklist](#universal-ux-checklist)
   below — the always-apply layer, independent of style.
2. **Putting data on screen (a dashboard, a report)?** Go to
   [Chart selection](#chart-selection-quick-reference) — pick the chart by the *question*, and
   heed the accessibility grades (some chart types fail colour-blind users outright).
3. **Need a palette / type / style?** The [Data tables index](#data-tables-index) tells you which
   CSV holds it and when to reach for it. Open the CSV for the exhaustive rows.
4. **This is a reference, not a doer.** The actual build tooling is the **`frontend-design`** skill
   (design-calibrated HTML/CSS) and **`artifact-design`** (loaded before any Artifact). Workflow
   habits — reference images first, clarify-before-build — live in `feedback_visual_design_workflow`
   (memory template). This file feeds *those*; it doesn't replace them.

---

## Data tables index

All under `07-References/design-system-data/`. Row counts are data rows (excl. header).

| CSV | Rows | What it holds | Reach for it when |
|---|---|---|---|
| `ux-guidelines.csv` | 98 | Do/Don't UX rules w/ code examples + severity (Nav, Animation, Layout, Touch, A11y, Perf, Forms, Responsive, Type, Feedback) | **Always.** Distilled below. |
| `charts.csv` | 25 | Chart-type selection: when to use / when NOT, data-volume thresholds, colour guidance, **a11y grade + fallback** | Any data viz — dashboards, reports. Distilled below. |
| `ui-reasoning.csv` | 161 | Per-industry recommended pattern + style priority + colour/type mood + **anti-patterns** + decision rules | Choosing an overall approach for a new surface by context |
| `colors.csv` | 160 | Full palettes per product type — primary/secondary/accent/bg/fg/card/muted/border/destructive, **WCAG-adjusted** | Need a coherent, contrast-safe palette |
| `typography.csv` | 73 | Font pairings (heading+body) w/ mood, best-for, Google-Fonts URL, **Tailwind config** | Picking type |
| `styles.csv` | 84 | UI style catalogue (Minimalism/Swiss, Glassmorphism, …) w/ best-for, **do-NOT-use-for**, light/dark, perf, a11y, conversion | Deciding the aesthetic; checking a style isn't wrong for the job |
| `motion.csv` | 16 | Motion tiers (subtle→expressive) w/ trigger, duration, easing, GSAP snippet, Do/Don't | Adding motion — keep it restrained (see UX rule #7) |
| `landing.csv` | 34 | Landing-page section-order patterns + CTA placement + conversion notes | Landing / marketing pages |
| `products.csv` | 161 | Product-type → recommended style + landing pattern + **dashboard style** + palette focus | Framing a new surface by product archetype |
| `icons.csv` | 105 | Phosphor icon lookup — name, import code, usage, best-for | Picking a specific icon (React/Phosphor) |
| `app-interface.csv` | 30 | Mobile app-shell Do/Don'ts (iOS/Android/RN) | *Low priority unless building mobile-native* |

---

## Universal UX checklist

The always-apply layer, distilled from `ux-guidelines.csv`. **High-severity items are the
non-negotiables** — the ones that break usability or accessibility outright. Full rows (with
good/bad code examples) are in the CSV.

### Accessibility (mostly High — the WCAG floor)
- **Contrast:** ≥ 4.5:1 for body text. `text-gray-900` on white, not `text-gray-400` on `gray-100`.
- **Never colour alone** to convey meaning — pair with icon/text (red border *and* an error icon). Directly relevant to dashboard status states.
- **Visible focus rings** on every interactive element — `focus:ring-2`, never bare `outline-none`.
- **Alt text** on meaningful images; **form labels** always (placeholder is not a label).
- **Sequential headings** h1→h2→h3 (don't skip for styling); semantic HTML over div-soup.
- **`aria-label`** on icon-only buttons; **`role="alert"` / `aria-live`** on error messages.
- **Respect `prefers-reduced-motion`** — no forced parallax/scroll-jacking (nausea + a11y fail).

### Layout & responsive (High where flagged)
- **Reserve space for async content** (`aspect-ratio` / fixed height) — layout shift is jarring.
- **Cap text line-length** to 65–75ch (`max-w-prose`); full-viewport paragraphs are unreadable.
- **Mobile:** 16px minimum body text, 44×44px touch targets, no horizontal scroll, tables get `overflow-x-auto`.
- **Viewport meta** set; z-index on a defined scale (10/20/30/50), never `z-[9999]`.

### Animation & motion (High where flagged)
- **1–2 animated elements per view, max.** Animate everything = distraction + motion sickness.
- **150–300ms** for micro-interactions; nothing over 500ms for UI. `ease-out` in, `ease-in` out.
- **Animate `transform`/`opacity` only** (GPU-cheap); never `width`/`height`/`top`/`left`.
- **Loading feedback** for anything > 300ms — skeleton or spinner, never a frozen/blank screen.

### Forms & interaction (High where flagged)
- **Visible label** per input; **error message next to the field**, not just at the form top.
- **Disable + spinner on submit** to stop double-submission; always confirm success/failure.
- **Confirm before destructive/irreversible actions** ("Are you sure?" before delete).
- **Disabled state** visually distinct (`opacity-50 cursor-not-allowed`).

### Performance (mostly Medium, but cheap wins)
- Optimised, right-sized images (WebP, `srcset`); lazy-load below-fold; `font-display: swap`.

### AI interaction (High)
- **Label AI-generated content** clearly — never present AI as human.

---

## Chart selection quick-reference

From `charts.csv`. **Pick by the question you're answering**, then check the accessibility grade
before committing — several common chart types (pie, treemap, sunburst, network, word-cloud, 3D)
grade **C or D** and *must* ship a table/text fallback, or not be the primary view at all.

| The question / data | Use | Avoid when | A11y |
|---|---|---|---|
| Trend over time | **Line** (area for volume) | < 4 points (use a stat card); > 6 series | AA — distinguish series by line-style, not colour |
| Compare categories | **Bar** (horizontal if labels long) | > 15 categories (use table); sort descending | AAA — value labels on bars |
| Part-to-whole | Donut/**Pie** *(sparingly)* | > 5 slices; differences < 5% | **C — fails colour-blind; must offer stacked-bar + % table** |
| KPI vs target (single) | **Gauge** / bullet | no target defined | AA — show number + % of target as text |
| KPIs vs target (several) | **Bullet chart grid** | single KPI (use gauge) | AAA — values always visible |
| Conversion / drop-off | **Funnel** / Sankey | non-sequential; < 3 stages | AA — % text per stage |
| Cumulative +/- to a total (P&L, budget variance) | **Waterfall** | > 12 bars; non-additive | AA — colour **+ arrow icon**, not colour alone |
| Forecast w/ uncertainty | **Line + confidence band** | audience not data-literate | AA — actual solid, forecast dashed |
| Correlation / clusters | **Scatter** / bubble | categorical vars; < 20 points | B — add shape markers + data table |
| Intensity across a grid / time | **Heatmap** | < 20 cells (use bar) | B — numeric legend + hover values |
| Hierarchy + size | Treemap / sunburst | depth > 3 levels | **C — table alternative mandatory** |
| Multi-attribute comparison | **Radar** | > 8 axes; need precise values | B — grouped-bar alternative mandatory |
| Relationships/network | Network graph | > 500 nodes unclustered | **D — inaccessible alone; always list alternative** |
| Distribution/spread | **Box plot** | < 20 points/group | AA — stats summary table |
| Geographic | Choropleth / bubble map | regions very unequal in size | B — region labels + sortable table |

**Rule of thumb for exec/board-facing reports:** lean **bar, bullet-grid, gauge, waterfall** (all
AA/AAA, table-friendly, legible in a deck). Treat **pie** as a last resort and never without a `%`
table beside it. For chart libs the data suggests Recharts/Chart.js/ApexCharts for standard, D3
for bespoke.

---

## Colour & type — where to look

- **Palettes** (`colors.csv`): rows are keyed by product type and are already WCAG-adjusted (the
  Notes column records the contrast tweak). Copy the whole row's token set
  (primary/on-primary … border/destructive/ring), don't hand-pick two colours.
- **Type pairings** (`typography.csv`): filter the *Best For* column to your context. Each row
  ships a Google-Fonts URL, CSS `@import`, and a ready Tailwind `fontFamily` config. Honour UX
  rules #72–77 (line-height 1.5–1.75, 65–75ch, clear heading/body contrast) whatever pairing you pick.
- **Styles** (`styles.csv`): check the **"Do Not Use For"** column before committing an aesthetic
  — e.g. heavy glassmorphism is wrong for dense data tables. For data/reporting surfaces,
  Minimalism/Swiss + a restrained accent is the safe default.

---

## See also

- `frontend-design` skill — the actual HTML/CSS build tool (design-calibrated)
- `artifact-design` skill — load before any Claude Artifact
- `07-References/design-system-data/` — the raw CSVs (exhaustive detail behind this interface)
