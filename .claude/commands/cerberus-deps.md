---
description: Audit a project's dependency manifests against the compromise registry. Walks requirements*.txt, pyproject.toml, package.json, etc., cross-references each declared dep against known supply-chain compromises (LiteLLM 1.82.7/8, telnyx 4.87.2, tiledesk-server 2.18.6-12, pino-sdk-v2 typosquat, Mini Shai-Hulud cascade, plus any entries added to the registry). Reports hits + suggested pinning fixes. Read-only.
argument-hint: "[optional path — defaults to current working directory]"
upstream: JohL29/claude-security-auditor (original Cerberus by Joh Leonhardt; /cerberus-deps borrows the supply-chain pinning discipline pattern from usestrix/strix)
---

Run a dependency audit on the project at the path provided as argument: `$ARGUMENTS` (if empty, default to the current working directory).

Use the `audit-dependencies` skill to perform the audit. The skill walks the project for manifest files, parses each, and cross-references every declared dependency against the compromise registry maintained in `07-References/dependency-pinning-discipline.md`.

Make NO changes to manifests, lock files, or installed packages. This is a read-only audit.

Produce a **Dependency Audit Report** with:
- **Verdict:** CLEAN / FINDINGS-PRESENT / TYPOSQUAT-PRESENT
- **Manifests scanned** (path + ecosystem + count of declared deps)
- **Compromise hits** (for each: package, ecosystem, declared version-spec, excluded versions per registry, suggested pin, source citation)
- **What passed cleanly** (count of deps confirmed not in the registry)
- **Recommended next step** (per the verdict tail logic below)

If the verdict is **TYPOSQUAT-PRESENT** (any `pino-sdk-v2`-class typosquat detected), end with: "TYPOSQUAT detected. Treat as incident. Rotate every secret reachable to the install context, audit logs covering the install window, re-image if production. Do not assume the install is contained. See `07-References/dependency-pinning-discipline.md` registry for the rationale."

If the verdict is **FINDINGS-PRESENT** (one or more registry hits, none typosquats), end with: "Findings present. For each hit, apply the suggested pin in the manifest and re-run `/cerberus-deps` to confirm. See `07-References/dependency-pinning-discipline.md` for the pinning practice (Steps 1–5)."

If the verdict is **CLEAN**, end with: "No known compromise-window packages present in scanned manifests. Discipline is forward-looking — next dep addition or version bump should run through Steps 1–5 of `07-References/dependency-pinning-discipline.md`."
