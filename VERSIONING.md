# Versioning

Charon follows **[semantic versioning](https://semver.org/)** (`vMAJOR.MINOR.PATCH`) with a clear authoring rule for which number to bump.

During private validation, tags carry the `-preview` suffix: `v0.X.Y-preview`. The suffix drops at first public release.

## The rule

| Bump | When | What's happening |
|---|---|---|
| **MAJOR** (`v1.0.0` → `v2.0.0`) | Breaking change | A user has to change their integration. Examples: removing a capability, renaming a published interface, the public-release flip itself. |
| **MINOR** (`v0.1.X` → `v0.2.0`) | **A new capability ships** | The previous version couldn't do this; this version can. Examples: a new MCP server, a new always-fire rule, a new slash command, a new email provider going from skeleton to working. |
| **PATCH** (`v0.1.0` → `v0.1.1`) | **An existing capability is improved** | The capability already existed; this version makes it better. Examples: a reliability fix, a validator-feedback refinement, a bug fix, a doc update to a published surface. |

## The authoring test

When opening a PR / cutting a release / writing a CHANGELOG entry, ask yourself:

> *"Could a user describe this change as 'now I can do X' where X is something they couldn't do before?"*

- **Yes** → MINOR bump
- **No, it's** *"X works better / faster / more reliably / without bug Y"* → PATCH bump

## Anti-patterns

These look fine in isolation but degrade the signal of your release log over time.

- **Inflating a PATCH into a MINOR for marketing.** Reliability / hardening / bug-fix work is a PATCH regardless of how much code changed.
- **Sliding a MINOR into a PATCH because *"it's just one new tool"*.** New tools / rules / hooks / endpoints are new capabilities even if scoped small.
- **Non-standard increments (.5 / .6 instead of .1 / .2).** Standard semver `v0.X.1 → v0.X.2 → v0.X.3` is what every contributor and tool reads fluently. Skip-patterns confuse readers.
- **Tagging without updating CHANGELOG (or vice versa).** Tag and CHANGELOG section update happen together — never tag-without-doc, never doc-without-tag.

## Release workflow

1. Land your change(s) on `main`.
2. Decide MINOR or PATCH using the authoring test.
3. Update `CHANGELOG.md`:
   - Move `[Unreleased]` entries into a new `[v0.X.Y-preview] - YYYY-MM-DD` section.
   - Add the version's compare/tag link to the footer.
4. Create the annotated tag:
   ```bash
   git tag -a v0.X.Y-preview <SHA> -m "<short release summary>"
   ```
5. Push the tag:
   ```bash
   git push origin v0.X.Y-preview
   ```
6. Commit + push the CHANGELOG update.
7. `[Unreleased]` is empty until the next change.

## Why this framework

Charon's development cadence is roughly 50/50 split between:

- **Validator-driven refinement** — Joh, Ben, future validators say *"X is confusing"* / *"please harden Z"*. PATCH lane.
- **Planned roadmap items** — a capability you'd designed ahead of time ships. MINOR lane.

The version number alone should tell a reader which kind of change happened. PATCH = the existing thing got better. MINOR = a new thing exists. That's the discipline this doc enforces.

## See also

- [`CHANGELOG.md`](CHANGELOG.md) — release log following [Keep a Changelog](https://keepachangelog.com/)
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — broader PR / contribution process
- [`ROADMAP.md`](ROADMAP.md) — planned capabilities that will trigger MINOR bumps when they ship
