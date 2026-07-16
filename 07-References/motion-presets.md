---
type: reference
title: Motion Presets (dependency-free CSS)
created: 2026-07-13
source: "Technique borrowed from transitions.dev (github.com/Jakubantalik/transitions.dev) — pattern re-derived, no code copied."
scope: "Copy-ready CSS transitions for any web surface you build with the harness — pages, dashboards, Artifacts"
tags: [reference/design, convention/frontend]
---

# Motion Presets (dependency-free CSS)

Copy-ready, **zero-dependency** CSS transitions **keyed by interaction pattern**. Complements
`design-system-data/motion.csv` (which is GSAP/JS, organised by abstract *tier*) by giving the
plain-CSS layer — no library, no build step, paste into any surface.

**Why this exists:** `frontend-design` teaches motion *taste* and `motion.csv` holds GSAP tiers,
but neither ships ready CSS snippets keyed to a concrete UI action (modal open, dropdown, toast).
This is that snippet library. It obeys the [Universal UX motion rules](design-system-reference.md#animation--motion-high-where-flagged):
`transform`/`opacity` only, 150–300ms micro-interactions, `ease-out` in / `ease-in` out, and it
bakes the `prefers-reduced-motion` guard into every preset.

> **Untrusted-source note:** the transitions.dev repo was treated as data during research; no code
> was run or copied. These snippets are re-authored to match the harness UX rules.

## Motion tokens (define once, at `:root`)

```css
:root {
  --t-fast: 150ms;      /* micro — hover, press, icon */
  --t-base: 220ms;      /* default UI transition       */
  --t-slow: 300ms;      /* entrances, larger surfaces  */
  --ease-out: cubic-bezier(0.16, 1, 0.3, 1);      /* enter: decelerate  */
  --ease-in:  cubic-bezier(0.4, 0, 1, 1);          /* exit: accelerate   */
  --ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1); /* gentle overshoot  */
}
```

## The reduced-motion guard (ship this once, globally)

Every preset below is written so this single guard neutralises it — no per-component work.

```css
@media (prefers-reduced-motion: reduce) {
  *, *::before, *::after {
    animation-duration: 0.01ms !important;
    animation-iteration-count: 1 !important;
    transition-duration: 0.01ms !important;
    scroll-behavior: auto !important;
  }
}
```

---

## Presets (keyed by interaction)

### 1. Modal / dialog — fade + scale-in
```css
.t-modal { opacity: 0; transform: scale(0.96); transition: opacity var(--t-base) var(--ease-out), transform var(--t-base) var(--ease-out); }
.t-modal[data-open="true"] { opacity: 1; transform: scale(1); }
```

### 2. Backdrop / overlay — fade
```css
.t-backdrop { opacity: 0; transition: opacity var(--t-base) var(--ease-out); pointer-events: none; }
.t-backdrop[data-open="true"] { opacity: 1; pointer-events: auto; }
```

### 3. Dropdown / menu — slide-down + fade
```css
.t-dropdown { opacity: 0; transform: translateY(-6px); transition: opacity var(--t-fast) var(--ease-out), transform var(--t-fast) var(--ease-out); }
.t-dropdown[data-open="true"] { opacity: 1; transform: translateY(0); }
```

### 4. Toast / notification — slide-in from edge
```css
.t-toast { opacity: 0; transform: translateX(1rem); transition: opacity var(--t-base) var(--ease-out), transform var(--t-base) var(--ease-out); }
.t-toast[data-open="true"] { opacity: 1; transform: translateX(0); }
```

### 5. Accordion / collapse — height via grid-rows (no max-height hack)
```css
.t-collapse { display: grid; grid-template-rows: 0fr; transition: grid-template-rows var(--t-base) var(--ease-out); }
.t-collapse[data-open="true"] { grid-template-rows: 1fr; }
.t-collapse > * { overflow: hidden; }
```

### 6. Tab / content — crossfade
```css
.t-tabpanel { opacity: 0; transition: opacity var(--t-fast) var(--ease-out); }
.t-tabpanel[data-active="true"] { opacity: 1; }
```

### 7. Card — hover lift
```css
.t-card { transition: transform var(--t-fast) var(--ease-out), box-shadow var(--t-fast) var(--ease-out); }
.t-card:hover { transform: translateY(-2px); box-shadow: 0 8px 24px rgb(0 0 0 / 0.10); }
```

### 8. Button — press feedback
```css
.t-press { transition: transform var(--t-fast) var(--ease-out); }
.t-press:active { transform: scale(0.97); }
```

### 9. Icon — chevron rotate (accordion/expander affordance)
```css
.t-chevron { transition: transform var(--t-fast) var(--ease-out); }
[data-open="true"] .t-chevron { transform: rotate(180deg); }
```

### 10. Tooltip — fade
```css
.t-tooltip { opacity: 0; transition: opacity var(--t-fast) var(--ease-out); }
.t-tooltip[data-show="true"] { opacity: 1; }
```

### 11. Skeleton — loading shimmer
```css
.t-skeleton { background: linear-gradient(90deg, #eee 25%, #f5f5f5 37%, #eee 63%); background-size: 400% 100%; animation: t-shimmer 1.4s ease infinite; }
@keyframes t-shimmer { 0% { background-position: 100% 0; } 100% { background-position: -100% 0; } }
```

### 12. Section — entrance on reveal (add `data-inview="true"` via IntersectionObserver)
```css
.t-reveal { opacity: 0; transform: translateY(12px); transition: opacity var(--t-slow) var(--ease-out), transform var(--t-slow) var(--ease-out); }
.t-reveal[data-inview="true"] { opacity: 1; transform: translateY(0); }
```

### 13. Spring pop-in (badges, confirmations — use sparingly)
```css
.t-pop { opacity: 0; transform: scale(0.8); transition: opacity var(--t-base) var(--ease-out), transform var(--t-base) var(--ease-spring); }
.t-pop[data-open="true"] { opacity: 1; transform: scale(1); }
```

---

## Usage rules (inherit the UX floor)
- **≤1–2 animated elements per view** (UX rule #86). These are a menu, not a fireworks kit.
- **`transform`/`opacity` only** — every preset obeys this; don't add `width`/`top`/`left`.
- **Toggle via a data-attribute** (`data-open`, `data-active`, `data-inview`) so state is declarative and testable — JS just flips the attribute.
- **Reduced-motion is already handled** by the global guard — don't duplicate it per component.

## See also
- `design-system-reference.md` — the design interface (this is linked from its index + See also)
- `design-system-data/motion.csv` — GSAP/tier motion (the JS-dependency counterpart)
- `frontend-design` skill — the build tool; feed it these tokens/presets
