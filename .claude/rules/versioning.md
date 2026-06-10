---
description: "Versioning framework — semver with intent. MINOR for new capability, PATCH for update / feedback fix. -preview suffix during private validation. Auto-loads on release, tag, version, changelog, bump work."
paths:
  - "CHANGELOG.md"
  - "VERSIONING.md"
  - ".changelog/**"
  - "CHANGES.md"
  - "HISTORY.md"
keywords:
  - "version"
  - "release"
  - "tag"
  - "changelog"
  - "bump"
  - "semver"
  - "v0."
  - "v1."
---

# Project versioning — semver with intent

This rule auto-fires when you're cutting a release, tagging, updating a CHANGELOG, or asking which number to bump. Charon ships this convention so your projects benefit from the same discipline.

## The rule

Every project under this harness uses **semantic versioning** (`vMAJOR.MINOR.PATCH`):

| Bump | When | Examples |
|---|---|---|
| **MAJOR** (`v1.0.0` → `v2.0.0`) | Breaking change — a user has to change their integration | Removing a capability, renaming a published interface, first public release |
| **MINOR** (`v0.1.X` → `v0.2.0`) | **A new capability ships** that didn't exist before | New MCP server / rule / slash command / endpoint / provider going from skeleton to working |
| **PATCH** (`v0.1.0` → `v0.1.1`) | **An existing capability is improved** | Validator-feedback refinement, reliability work, bug fix, security hardening |

**During private validation:** all tags carry `-preview` suffix (`v0.X.Y-preview`). Drop at first public release.

## The authoring test

When opening a PR / cutting a release / writing a CHANGELOG entry, ask:

> *"Could a user describe this change as 'now I can do X' where X is something they couldn't do before?"*

- **Yes** → MINOR
- **No, it's** *"X works better / faster / more reliably / without bug Y"* → PATCH

## Patch-notes content standard (every entry)

A CHANGELOG entry is **patch notes**, not a terse "added X". The changelog is part of the documentation surface — a reader (a user deciding whether to adopt a capability, a contributor, future-you) should understand the change from the entry alone. **Every entry covers three things:**

1. **Capability** — what it does (the mechanics: the new command / agent / hook / behaviour).
2. **Intent** — what it's *for*; the job it does for the user.
3. **Why it matters** — why it's important; the problem it removes or the value it adds.

A one-line "Added: /forum-agenda" fails this — it conveys neither purpose nor value. Write enough that someone who wasn't in the room understands the capability *and why they'd care*. Keep it tight, but cover all three. (Same teaching ethic as README / CAPABILITIES — those docs update in the **same change**, never left stale.)

## Anti-patterns to call out

| Anti-pattern | Why it's wrong |
|---|---|
| Inflating a PATCH into a MINOR for marketing | Reliability / hardening / fixes are PATCHes regardless of how much code changed |
| Sliding a MINOR into a PATCH because *"it's just one new tool"* | A new MCP tool / rule / hook / endpoint IS a new capability, even if scoped small |
| Non-standard increments (`.5 / .6` instead of `.1 / .2`) | Standard semver `.1 → .2 → .3` is what every contributor and tool reads fluently |
| Tagging without updating CHANGELOG (or vice versa) | They happen together — never tag without doc, never doc without tag |
| Skipping the `-preview` suffix during validation | The suffix signals *"still shaping, expect change"* to readers and tools |
| Terse entry ("added X") with no intent / why | The changelog is documentation — every entry covers capability + intent + why it matters (see the patch-notes standard above) |
| Shipping a capability but leaving README / CAPABILITIES counts + listings stale | Docs update in the SAME change as the capability — stale counts are a freshness failure |

## Release workflow

1. Land your change(s) on `main`
2. Decide MINOR or PATCH using the authoring test
3. Update `CHANGELOG.md`:
   - Move `[Unreleased]` entries into a new `[v0.X.Y-preview] - YYYY-MM-DD` section
   - Add the version's compare/tag link to the footer
4. Create the annotated tag:
   ```bash
   git tag -a v0.X.Y-preview <SHA> -m "<short release summary>"
   ```
5. Push the tag:
   ```bash
   git push origin v0.X.Y-preview
   ```
6. Commit + push the CHANGELOG update
7. `[Unreleased]` is empty until the next change

## Co-change couplings

- **CHANGELOG and tag are coupled.** A commit that adds a `[v0.X.Y]` section MUST also push the matching tag. A pushed tag without a CHANGELOG entry is a documentation gap that confuses readers.
- **VERSIONING.md is the user-facing doc.** This rule auto-injects when you're in version-work. `VERSIONING.md` is what readers see in the repo.
- **README references SHOULD include the latest tag** if the README has install / install-from-tag instructions.

## See also

- `VERSIONING.md` at repo root — the user-facing doc explaining this convention
- `CHANGELOG.md` — the release log following [Keep a Changelog](https://keepachangelog.com/)
- `CONTRIBUTING.md` — broader contribution process
