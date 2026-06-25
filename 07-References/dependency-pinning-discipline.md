---
title: Dependency pinning discipline
status: active
version: 1.0
date: 2026-05-25
audience: anyone adding or updating a dependency in this harness or in a project the harness builds
---

# Dependency pinning discipline

## Why this exists

A dependency manifest is a security artefact, not just a build artefact. The supply-chain attacks of 2024–2026 have made the version pin a defensive control — when a known-compromised version exists in the upstream registry, every install that doesn't exclude it is a risk. Strix (`usestrix/strix`) pins `litellm[proxy]>=1.81.1,<1.82.0` specifically to exclude the LiteLLM 1.82.7 / 1.82.8 compromise window. That posture should be the default, not the exception.

This document defines (a) the **compromise registry** — known-bad package versions to exclude — and (b) the **practice** for adding / updating any dependency.

## The compromise registry

| Package | Ecosystem | Excluded versions | Source | Action when present |
|---|---|---|---|---|
| **litellm** | PyPI | `1.82.7`, `1.82.8` | safedep/pmg; Strix pinning precedent | Pin upper bound: `litellm>=1.81.1,<1.82.7` (or skip 1.82.x entirely until clear) |
| **telnyx** | PyPI | `4.87.2` | safedep/pmg README (May 2026) — legitimate telecom SDK hijacked | Pin upper bound that excludes 4.87.2, or remove if not load-bearing |
| **tiledesk-server** | npm | `2.18.6` through `2.18.12` | safedep/pmg README — npm package compromised via Mini Shai-Hulud cascade | Pin `<2.18.6 || >2.18.12`; replace if active |
| **pino-sdk-v2** | npm | ALL versions | safedep/pmg README — **typosquat** disguised as `pino` logger; always malicious | **Never install.** If found, treat as incident: rotate every secret reachable to the install context, audit logs, re-image if production |
| **Mini Shai-Hulud cascade** | npm | 300+ packages compromised in single campaign (May 2026) | safedep/pmg README | If a package was published during the cascade window, vet it before install |
| **Shai-Hulud "Miasma" / Red Hat npm wave** | npm | `@redhat-cloud-services/*` — ~32 packages (June 2026); GitHub OIDC-token abuse | TLDR InfoSec / Help Net Security, June 2026 | Rotate secrets on machines that installed affected `@redhat-cloud-services` versions; vet before reinstall |
| **Shai-Hulud successor waves (antv / TanStack / "Megalodon" / "3.0")** | npm + PyPI | Specific package/version lists vendor-reported and varying — **verify against OSV / GitHub Advisory DB before relying**; assoc. CVE-2026-45321 | Unit 42 / ReversingLabs / Snyk / CSA, May–June 2026 | Cross-check any npm/PyPI dep published May–Jun 2026 against OSV; vet anything implicated |

**Registry maintenance:**
- New compromise → add a row in the same change that introduces the pin
- Strix's `pyproject.toml` is a useful reference (they maintain similar defensive pins on packages relevant to their stack)
- Review quarterly — supply-chain landscape changes fast

## The practice — adding or updating a dependency

### Step 1. Check the compromise registry above

Before adding a new package or bumping a version, scan the registry. If the package appears, apply the documented upper-pin pattern AND record the pin in the registry as `pin applied — <project> — <date>`.

### Step 2. Read the package's recent release history

Specifically check whether the version you're pinning had any abnormal patterns in the last 30 days:
- Unusually large version-number jumps with no changelog
- New maintainers or transferred ownership
- A burst of releases in a 24-48 hour window
- Author change-of-control announcements on socials

If any of these are present and the package isn't load-bearing, defer the upgrade. If load-bearing, pin to the **previous known-good version** and add a TODO to revisit once the situation clarifies.

### Step 3. Pin with intent

Three pinning patterns, in order of preference:

| Pattern | When to use | Example |
|---|---|---|
| **Compatibility-release pin** | Default for stable libraries | `pydantic>=2.11.3,<3` (semver-compatible upgrades, breaks excluded) |
| **Upper-bound exclusion** | Known compromise window | `litellm>=1.81.1,<1.82.0` (Strix pattern — explicitly excludes 1.82.7/1.82.8) |
| **Exact pin** | Single-binary tools, reproducibility-critical | a compiled single-binary extension or embedded DB; bump deliberately |

Avoid:
- `package>=X` with no upper bound on packages with active maintainers — leaves the door open to the next compromise window
- `package==X` everywhere — locks out security patches; only justified for binary-tool reproducibility
- `package` with no version at all — pulls latest, which IS the supply-chain attack surface

### Step 4. Comment the why

If the pin is defensive (exclusion-style), add a comment naming the excluded version and the source of the compromise data:

```python
# requirements.txt
litellm>=1.81.1,<1.82.0  # excludes 1.82.7/1.82.8 supply-chain compromise (see 07-References/dependency-pinning-discipline.md)
```

### Step 5. Audit before deploying

Run `pip-audit` (Python) or `npm audit` (Node) in CI before publish/deploy. These tools surface known-CVE matches against the lock file. They WON'T catch zero-day compromise windows by themselves (which is why the registry above exists) — but they catch the long tail.

Future enhancement: `test-scenarios/run-deterministic-checks.py` could grow a `dependency-audit` check that cross-references each manifest against the compromise registry. Parked.

## Current audit state (2026-05-25)

A manual audit of all manifests was run on 2026-05-25 as part of this document's creation. **No known-compromised versions are present** in any current manifest in this harness:

| Manifest | Packages | Compromise hits |
|---|---|---|
| `requirements.txt` | PyYAML, anthropic, mcp | None |
| `requirements-graph.txt` | networkx | None |
| `requirements-semantic.txt` | sentence-transformers, sqlite-vec, numpy | None |
| `requirements-voice.txt` | openai-whisper, sounddevice, scipy | None |
| `capture-pipeline/package.json` | @azure/msal-node, googleapis, imapflow | None |

The discipline is therefore established forward-looking. Next dep addition or version bump follows Step 1–5.

## Co-change couplings

- New entry added to the compromise registry → log the source in this doc + consider whether existing manifests need re-auditing
- New manifest created (new optional-deps file, new sub-project) → audit against registry in the same change
- Quarterly review → re-scan all manifests against current registry; surface any drift

## See also

- `https://github.com/usestrix/strix` — provenance for this discipline; their pyproject.toml is a useful reference for compromise-window pinning patterns
- `https://github.com/safedep/pmg` — Package Manager Guard, a runtime tool that maintains its own compromise intelligence; useful comparator for the registry above
- `SECURITY.md` — broader security framework
