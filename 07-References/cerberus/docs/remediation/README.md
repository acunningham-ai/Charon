# Cerberus Remediation Library

Canonical fix templates for the most common findings Cerberus produces. When `/cerberus-vet` fires a finding, the Mitigation field references the matching template ID. This library gives artifact authors and internal developers a structured path from "Cerberus found X" to "here's how to fix it".

## How to use

- **As an artifact author** (you wrote the plugin / skill / MCP server): find the REM-NNN ID Cerberus surfaced, read the "Author-side fix" section, apply the change, re-run `/cerberus-vet`.
- **As an internal developer** (you want to install someone else's artifact): find the REM-NNN ID, read the "adopter-side acceptance" section, decide whether the conditions are acceptable for your context.
- **As the CISO function reviewer**: read the cross-references and use them to inform your advisory engagement with the org unit and the Approving Authorities.

## Library

| ID | Title | V-layer | OWASP | Severity at detection |
|---|---|---|---|---|
| [REM-001](REM-001-excessive-webfetch.md) | Excessive `WebFetch` grant without documented purpose | V1 | LLM06 Excessive Agency | Important |
| [REM-002](REM-002-excessive-bash.md) | Excessive `Bash` grant without documented purpose | V1 | LLM06 Excessive Agency | Important |
| [REM-003](REM-003-mcp-arbitrary-shell-tool.md) | MCP server exposes a tool that executes arbitrary shell | V1 | LLM06 Excessive Agency | Critical |
| [REM-004](REM-004-mcp-annotation-dishonesty.md) | MCP tool annotation contradicts implementation | V1 | LLM06 Excessive Agency | Critical |
| [REM-005](REM-005-suspicious-hardcoded-url.md) | Hardcoded URL to a non-public-API host | V2 | LLM03 Supply Chain | Critical |
| [REM-006](REM-006-mcp-http-no-auth.md) | HTTP-transport MCP server with no auth | V2 | LLM03 Supply Chain | Critical |
| [REM-007](REM-007-sensitive-path-read.md) | Code reads sensitive filesystem paths without documented need | V3 | LLM02 Sensitive Information Disclosure | Critical |
| [REM-008](REM-008-injection-markers-in-md.md) | Prompt-injection markers in artifact's own markdown | V5 | LLM01 Prompt Injection | Critical |
| [REM-009](REM-009-mcp-tool-description-poisoning.md) | Tool description contains prompt-injection content | V5 | LLM01 Prompt Injection | Critical |
| [REM-010](REM-010-mcp-sdk-typosquat.md) | MCP SDK dependency is from a non-canonical source | V8 | LLM03 Supply Chain | Important |

## Template structure

Each template file follows the same shape so callers can pattern-match:

```markdown
# REM-NNN — <title>

**V-layer:** Vetting layer this implements
**OWASP:** OWASP Top 10 for LLM Applications (2025) entry
**Severity at detection:** Default severity the vetter assigns
**Status:** stable / draft / deprecated

## What triggers this
Plain-English description of the finding pattern.

## Why it matters
Risk explanation — what could go wrong if unaddressed.

## Author-side fix
Step-by-step remediation for the artifact author.

## adopter-side acceptance
Conditions under which an org unit can accept the risk if the author won't fix.

## Cross-references
Links to OWASP entry, related templates, and the SKILL.md step that detects this.
```

## Adding to the library

When `/cerberus-vet` surfaces a finding that doesn't have a matching template — and it's the kind of finding that's likely to recur across internal artifacts — add a new template:

1. Pick the next REM-NNN ID.
2. Create `docs/remediation/REM-NNN-<short-slug>.md` following the structure above.
3. Add a row to the table in this README (alphabetised by ID).
4. Reference the template from the relevant `Step N` in `skills/vet-external-skill/SKILL.md` so the vetter surfaces it inline.

The library grows. Don't worry about completeness on day one; the calibration log from real assessments (see `docs/calibration-log.md` once it exists) drives what's missing.

## Authority framing

This library produces **remediation advice**, not approval decisions. Final tool-approval authority sits with the Approving Authorities (as defined by your organization) per your organization's AI tool-approval policy. A "Author-side fix" applied successfully reduces the risk evidence; it does not by itself approve the tool.
