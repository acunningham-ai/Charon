---
name: audit-dependencies
description: "Read-only audit of a project's dependency manifests against the compromise registry. Walks requirements*.txt, pyproject.toml, setup.py, package.json, go.mod, Cargo.toml, Gemfile under the target path, parses declared deps, cross-references every declared package against known supply-chain compromises. Use when a user asks 'audit my deps', 'check for compromised packages', 'run cerberus-deps', 'are any of my deps on a known-bad list'. Trigger on: '/cerberus-deps', 'cerberus deps', 'audit dependencies', 'check supply chain', 'check for compromised packages', 'check package compromises', 'supply chain audit'."
---

# audit-dependencies

## Purpose

Performs a read-only audit of a project's dependency manifests against the **compromise registry** maintained in `07-References/dependency-pinning-discipline.md`. Surfaces known-compromised package versions in declared deps + suggests defensive pins. NO changes are made to manifests, lock files, or installed packages.

This is the **recurring** counterpart to `vet-external-skill` (which vets a single third-party artifact pre-install). `/cerberus-deps` runs over the user's *own* project on demand — every install, every PR, periodic review.

## When to Use

- Before adopting a new dependency or bumping an existing version.
- As a recurring audit (quarterly review, or on every CI run if wired in).
- After news of a fresh supply-chain compromise — re-run to check whether any current dep landed in the new window.
- Before publishing or deploying any Charon/Cerberus build externally.

## When NOT to Use

- For vetting a *third-party* artifact pre-install — that's `/cerberus-vet <repo-url>` (different skill, different threat model).
- For a full SAST / SCA scan — this skill checks only the named-compromise-window cases in the registry; it's not a substitute for `pip-audit` / `npm audit` / Snyk / etc. Run those alongside.
- For runtime dependency-confusion detection — that's a different attack class; this skill checks names + versions only, not registry origins.

## Step 0 — Resolve scope

`$ARGUMENTS` may contain a path. If empty, default to current working directory (cwd). Confirm the path exists; if not, halt and ask: *"Path not found. Provide a project path or call from inside the project root."*

Record the resolved scope path in the report.

## Step 1 — Load the compromise registry

Read `07-References/dependency-pinning-discipline.md`. Extract the **compromise registry** table — each row is one entry with: Package, Ecosystem (PyPI / npm / etc.), Excluded versions, Source citation, Action when present.

The registry is the single source of truth. Don't embed your own copy; if the discipline doc isn't reachable (file missing, scope outside the harness), halt with: *"Cannot load compromise registry from `07-References/dependency-pinning-discipline.md`. Confirm the path or run from a harness-rooted workspace."*

## Step 2 — Locate manifests

Walk the scope path for the following manifest filenames (use Glob):

- Python: `requirements*.txt`, `pyproject.toml`, `setup.py`, `Pipfile`, `Pipfile.lock`
- Node: `package.json`, `package-lock.json`, `yarn.lock`, `pnpm-lock.yaml`
- Go: `go.mod`, `go.sum`
- Rust: `Cargo.toml`, `Cargo.lock`
- Ruby: `Gemfile`, `Gemfile.lock`

Skip `node_modules/`, `.venv/`, `venv/`, `__pycache__/`, `.git/`, `vendor/` — these are installed-package directories, not source manifests.

Record each manifest's path + ecosystem in the report.

## Step 3 — Parse declared deps from each manifest

For each manifest, extract the **declared package names and version specs**. Targets the source manifest (the human-edited file), not the lock file in this pass — lock files are a future enhancement.

Parsing patterns:

| Ecosystem | Manifest | What to extract |
|---|---|---|
| Python | `requirements*.txt` | Each non-comment line — regex `^([a-zA-Z0-9_\-\[\]\.]+)\s*([<>=~!^].*)?$` for `package[extras]version_spec` |
| Python | `pyproject.toml` | `[project.dependencies]` array + each `[project.optional-dependencies.<name>]` array — extract the quoted dep strings |
| Python | `setup.py` | `install_requires=[...]` and `extras_require={...}` — string parse |
| Node | `package.json` | `.dependencies` + `.devDependencies` + `.peerDependencies` + `.optionalDependencies` — each is `"package": "version_spec"` |
| Go | `go.mod` | `require (...)` block — extract `module version` pairs |
| Rust | `Cargo.toml` | `[dependencies]` and `[dev-dependencies]` — each is `package = "version_spec"` or `package = { version = "..." }` |
| Ruby | `Gemfile` | `gem 'name', 'version_spec'` lines |

For each declared dep, record: (manifest path, ecosystem, package name, version spec, raw line).

If a manifest can't be parsed (malformed TOML, etc.), record it as `parse-error` in the report and continue.

## Step 4 — Cross-reference each dep against the registry

For each declared dep:

1. Look up the package name in the registry. Match on (package name, ecosystem) — case-sensitive on name, ecosystem must match.
2. If no match → not a registry hit (pass).
3. If matched → check whether the declared version-spec **excludes** the excluded versions from the registry entry:
   - Spec like `>=1.81.1,<1.82.0` against excluded `1.82.7`, `1.82.8` → spec excludes the bad versions → pass with a note that pin is *load-bearing*.
   - Spec like `>=1.81.1` (no upper bound) against excluded `1.82.7` → spec ALLOWS the bad version → **finding**.
   - Spec like `^1.81.1` (semver-compatible) — in npm, this means `<2.0.0`, so allows `1.82.7` → **finding**.
   - No version spec (just `package`) → allows latest, ALLOWS the bad version → **finding**.
   - For typosquats (`pino-sdk-v2` etc.) — presence at any version is a **TYPOSQUAT finding** regardless of spec.

Be conservative: if the version-spec parsing is ambiguous, classify as **finding** and flag the parsing uncertainty in the report.

## Step 5 — Classify the finding severity

| Severity | Trigger | Score impact |
|---|---|---|
| **TYPOSQUAT-PRESENT** | Any typosquat in the registry is declared (e.g. `pino-sdk-v2`) | Verdict escalates to TYPOSQUAT-PRESENT. Single finding is sufficient for this verdict. |
| **Critical hit** | A compromise-window version is permitted by the spec (e.g. `litellm` with no upper bound on PyPI) | Counts toward FINDINGS-PRESENT verdict |
| **Advisory hit** | Package is in the registry but the spec correctly excludes the compromise window — record as a positive note (pin is load-bearing; don't drop it) | Doesn't change verdict; informational |

## Step 6 — Compute the verdict

- ANY TYPOSQUAT hit → **TYPOSQUAT-PRESENT** (incident-response posture)
- ANY Critical hit (and no typosquat) → **FINDINGS-PRESENT**
- Zero Critical, zero TYPOSQUAT → **CLEAN**

## Step 7 — Output format

```
### Dependency Audit Report — [scope path] — [date]

**Verdict:** CLEAN / FINDINGS-PRESENT / TYPOSQUAT-PRESENT
**Registry version:** read from `07-References/dependency-pinning-discipline.md` ([N] entries)
**Manifests scanned:** [count] across [list of ecosystems]
**Total declared deps:** [N]

#### Compromise hits
[For each, if any:]
- **Package:** [name] (ecosystem)
- **Manifest:** [path]
- **Declared spec:** [raw spec string]
- **Excluded versions:** [from registry]
- **Why it matched:** [spec permits / does not exclude / typosquat]
- **Suggested pin:** [concrete spec to apply]
- **Source:** [citation from registry]

#### Load-bearing pins (positive note)
[List packages in registry that ARE correctly pinned to exclude the compromise window — confirm these stay in place]

#### What passed cleanly
[N] declared deps confirmed not in the registry. (Note: this does NOT mean they're free of known CVEs — run `pip-audit` / `npm audit` for that.)

#### Recommended next step
[Per the verdict tail logic in commands/cerberus-deps.md]
```

## Confidence tagging

Per the harness's confidence-tag convention, mark factual claims in the report:
- 🟢 — pattern matched + version-spec parsed unambiguously
- 🟡 — pattern matched + version-spec parsing has edge cases (e.g. complex constraints, multiple specifiers)
- 🔴 — pattern matched but parsing ambiguous; surface for human review

## Edge cases

- **Lock files only, no source manifest** — surface as a note: "lock file present but no source manifest in this scope; declared-dep semantics not assessable from lock file alone". Future enhancement: parse lock files directly.
- **Monorepo with multiple sub-projects** — walk into each sub-project's manifests; report verdict per-manifest AND aggregate.
- **Discipline doc missing or unparseable** — halt with the error from Step 1; never silently skip the cross-reference.
- **Registry entry without a clear version-spec format** (e.g. "ALL versions" for typosquats) — treat presence at any version as the finding.
- **User asks to "skip" or "override" a finding** — record the override in the report; do NOT remove the finding. The audit is read-only; overrides are a documentation decision, not a vulnerability-status change.

## Handoffs

- Apply suggested pins: the user edits the manifest directly. This skill does NOT auto-edit manifests (would conflict with read-only posture).
- Typosquat detection: escalate to `rotate-leaked-secret` skill if any secrets may have been exposed during the install window.
- Recurring schedule: wire into a `.bat` runner or CI workflow for quarterly + per-PR runs. Not built yet — parked.

## Co-change couplings

- New entry added to the compromise registry → no skill change required; this skill reads the registry on each invocation
- Registry format changes (markdown table shape) → update Step 1's parsing logic
- New ecosystem added (e.g. PHP Composer) → update Step 2's manifest list + Step 3's parsing patterns
- This skill produces a non-trivial report → consider whether `/score-vault` should recognise the report shape if it lands in the vault
