# REM-001 — Excessive `WebFetch` grant without documented purpose

**V-layer:** V1 (Capability Scope Analysis)
**OWASP:** [LLM06:2025 Excessive Agency](https://genai.owasp.org/llmrisk/llm062025-excessive-agency/)
**Severity at detection:** Important (escalates to Critical when combined with `Bash` + `Write` per REM-003)
**Status:** stable

## What triggers this

A Claude Code agent or command declares `WebFetch` in its `tools` array, but the README and/or skill description does not document a network-using purpose. From the perspective of the vetter, you're granting outbound HTTP capability on install with no stated reason.

```yaml
# agents/example-agent.md frontmatter
tools: ["Read", "Grep", "WebFetch"]
```

## Why it matters

`WebFetch` lets the artifact make arbitrary outbound HTTP requests at runtime, including potential exfiltration of in-context data (snippets of files Claude has read, settings, conversation history). Granted unnecessarily, it expands the artifact's effective agency well beyond what the user consented to when they installed it.

In a prompt-injection attack against the user, an adversary can hijack the artifact's `WebFetch` capability to send sensitive context to an attacker-controlled URL. The user thinks the artifact "just analyses local files" — they don't realise the install also enabled outbound HTTP.

## Author-side fix

**If the artifact does not actually need network access:**

Remove `WebFetch` from the `tools` array in every agent / command frontmatter that declares it.

```yaml
# Before
tools: ["Read", "Grep", "WebFetch"]
# After
tools: ["Read", "Grep"]
```

**If the artifact does need network access:**

1. Document the specific need in the README under a "Network access" or "Privacy" section. Name the endpoints being called and what data is sent.
2. If possible, narrow the capability — use a more constrained mechanism (e.g. a specific MCP server with a documented allowlist) instead of unrestricted `WebFetch`.
3. Re-run `/cerberus-vet` once the README documents the use. The finding will downgrade or pass.

## adopter-side acceptance

A org unit can accept this risk only if:

1. The artifact's purpose plausibly requires network access (e.g. an artifact that researches CVEs needs to query CVE databases).
2. The internal developer has read the artifact source and confirmed network calls go only to the documented endpoints.
3. The org unit has agreed via the Approving Authorities (per your organization's AI tool-approval policy) that the data the artifact might exfil is non-sensitive in the org unit's context.

Without all three, escalate to the the CISO function for advisory engagement before install.

## Cross-references

- Detection logic: `skills/vet-external-skill/SKILL.md` Step 2 (V1)
- Related: [REM-002](REM-002-excessive-bash.md) — Excessive `Bash` grant
- Related: [REM-003](REM-003-mcp-arbitrary-shell-tool.md) — MCP arbitrary-shell tool (same risk class for MCP artifacts)
