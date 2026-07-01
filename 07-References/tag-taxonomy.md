---
type: reference
title: "Tag taxonomy"
description: "Faceted tag taxonomy — the source of truth for /vault-lint Check C and scripts/migrate-tags.py. Edit the JSON block to match your org."
---

# Tag taxonomy

This is the faceted tag vocabulary for your vault's frontmatter `tags:`. It is
the **source of truth** for two tools:

- `/vault-lint` (Check C) — flags frontmatter tags that don't match this taxonomy.
- `scripts/migrate-tags.py` — rewrites bare/legacy tags to the faceted form.

**This file is yours to own.** The engine hardcodes no facet or value — it reads
whatever you declare in the fenced ```json block below. Replace the example
values with your own. The closed-facet values (`unit/`, `portfolio/`, `domain/`)
are **auto-seedable** from the org-unit list you gave at first-run — a working
starter taxonomy comes for free; extend it as your vault grows.

## The faceting model

A tag is `facet/value` (e.g. `type/meeting`, `unit/acme-widgets`). Two kinds of
facet:

- **Closed** (`"closed": true`) — only the listed `values` are valid. Use for
  controlled vocabularies you compare across: `type`, `unit`, `portfolio`,
  `domain`. An unknown value is flagged as drift.
- **Open** (`"closed": false`) — any kebab-case value is valid. Use for
  long-tail facets you don't want to police: `topic`, `vendor`.

`migrations` maps a legacy **bare** tag to its faceted target, so the migrator
can resolve `meeting` → `type/meeting` automatically. Bare `unit` / `portfolio`
/ `domain` tags are additionally resolved from the note's folder location where
possible (see `scripts/migrate-tags.py`).

## The taxonomy (edit this block)

> The values below are **illustrative examples** — replace them with your own.
> `unit` / `portfolio` / `domain` values should mirror your actual org-units,
> portfolios, and security domains.

```json
{
  "version": 1,
  "facets": {
    "type": {
      "closed": true,
      "values": ["meeting", "decision", "reference", "project", "person", "daily", "bulletin"]
    },
    "portfolio": {
      "closed": true,
      "values": ["example-portfolio-a", "example-portfolio-b"]
    },
    "unit": {
      "closed": true,
      "values": ["example-unit-one", "example-unit-two", "example-unit-three"]
    },
    "domain": {
      "closed": true,
      "values": ["identity", "vulnerability-management", "incident-response", "vendor-risk", "data-protection", "governance"]
    },
    "topic": {
      "closed": false
    },
    "vendor": {
      "closed": false
    }
  },
  "migrations": {
    "meeting": "type/meeting",
    "decision": "type/decision",
    "reference": "type/reference",
    "project": "type/project",
    "person": "type/person",
    "daily": "type/daily"
  }
}
```

## How the migrator derives closed-facet values from folders

`scripts/migrate-tags.py` resolves a bare `unit` / `portfolio` / `domain` tag
from the note's path when the value is derivable and valid against the closed
list above. It expects the default layout:

- `unit`      ← `02-BUs/_Portfolio-<Group>/<Unit>/…`  → `unit/<slug(Unit)>`
- `portfolio` ← `02-BUs/_Portfolio-<Group>/…`         → `portfolio/<slug(Group)>`
- `domain`    ← `03-Domains/<Domain>/…`               → `domain/<slug(Domain)>`

An underivable or invalid value is **left alone** (reported, not guessed). If
your folder layout differs, either rename to match or extend the derivation
logic — the engine never invents a value.
