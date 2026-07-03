---
paths:
  - "08-Projects/*Dashboard*/**"
  - "08-Projects/*Web*/**"
  - "08-Projects/*Site*/**"
  - "**/*.html"
  - "**/*.tsx"
  - "**/*.jsx"
  - "**/*.svelte"
keywords:
  - "dashboard"
  - "landing page"
  - "chart"
  - "data viz"
  - "colour palette"
  - "color palette"
  - "font pairing"
  - "ui design"
  - "ux"
  - "mockup"
  - "frontend design"
---

# Design rules

Auto-loaded when building a visual surface (dashboards, landing/marketing pages, charts,
Artifacts, web UI). The full interface is **`07-References/design-system-reference.md`** — open it
for the UX checklist, chart-selection quick-ref, and palette/type/style pointers. Raw data:
`07-References/design-system-data/*.csv`. (Data adapted from `ui-ux-pro-max-skill`, MIT © 2024
Next Level Builder — see root `NOTICE`.)

## Before you build

1. **Clarify first, reference first.** Ask 4–6 questions (style, fonts, sections, motion level,
   tone) and gather reference screenshots before building — the two habits `frontend-design`
   doesn't do on its own.
2. **The actual build tool is the `frontend-design` skill** (and `artifact-design` for Artifacts).
   This rule + the reference feed those; they don't replace them.

## Always-apply floor (don't ship without these)

- **Contrast ≥ 4.5:1** body text; **never colour alone** for meaning (pair icon/text) — matters
  for every dashboard status state.
- **Visible focus rings**, real form labels, alt text, sequential headings, `aria-label` on
  icon-only buttons, respect `prefers-reduced-motion`.
- **Motion restrained:** 1–2 animated elements per view, 150–300ms, `transform`/`opacity` only.
- **Reserve space for async content** (no layout shift); cap text to 65–75ch; loading feedback
  for anything > 300ms.

## Charts (dashboards / reports)

Pick the chart by the **question**, then check its accessibility grade in
`design-system-reference.md#chart-selection-quick-reference`. Exec/board-facing surfaces lean
**bar / bullet-grid / gauge / waterfall** (AA–AAA, table-friendly). **Pie is a last resort** and
never without a `%` table beside it; treemap/network/3D need a table fallback or aren't the
primary view.

## See also

- `07-References/design-system-reference.md` — the interface (open on any visual build)
- `frontend-design` / `artifact-design` skills — the build tools
