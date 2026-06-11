# Framework reference library

This folder holds the **curated framework reference material** that framework-aware skills read — most notably `/control-translate` in `framework` mode, which reads the relevant clauses/sections here before drafting stakeholder commentary.

**It ships empty on purpose.** Control catalogues and framework clause text are licence- and organisation-specific — Charon can't bundle them. You populate this folder with the framework(s) your org actually uses.

## What goes here

One file (or subfolder) per framework you want skills to reference. Suggested shape:

```
07-References/frameworks/
  README.md                  ← this file
  <framework-slug>.md         ← e.g. essential-eight.md, nist-csf-2.0.md, iso-27001.md, cps-234.md
```

Each framework file should carry, at minimum:

- The control/clause identifiers and their plain-language intent (enough for a skill to cite "what good looks like" without quoting copyrighted text verbatim).
- Your org's calibration where relevant (target maturity per control, which controls are critical).

Per the harness principle **rules teach structure, you supply content**: the skills know *how* to use a framework reference; you decide *which* framework and supply its substance.

## How skills use it

- **`/control-translate <scope> <target>` (framework mode)** — confirms a framework reference exists here, reads the relevant clauses for the topic, and grounds its stakeholder paragraph in that language. With this folder empty, framework mode has nothing to read and will tell you so — add your framework file first.
- Other framework-aware skills follow the same read-before-cite pattern.

## Sourcing tips

- Open frameworks (e.g. NIST CSF, OWASP) can be summarised here directly.
- Licensed frameworks (e.g. ISO standards) — store *your own* paraphrase / control-intent notes and calibration, not the copyrighted clause text.
- Open-source GRC projects publish machine-readable control catalogues you can adapt as a starting point.

## See also

- `.claude/commands/control-translate.md` — the primary consumer of this folder
- `07-References/security-baselines.md` — the harness's own C-1..C-9 control baseline (distinct from external compliance frameworks)
