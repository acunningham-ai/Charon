# REM-002 — Excessive `Bash` grant without documented purpose

**V-layer:** V1 (Capability Scope Analysis)
**OWASP:** [LLM06:2025 Excessive Agency](https://genai.owasp.org/llmrisk/llm062025-excessive-agency/)
**Severity at detection:** Important (escalates to Critical when combined with `Write` + `WebFetch` per REM-003)
**Status:** stable

## What triggers this

A Claude Code agent or command declares `Bash` in its `tools` array, but the README and/or skill description does not document a shell-using purpose. Granting `Bash` lets the artifact execute arbitrary shell commands on the user's machine — a much broader capability than file reading, grepping, or network-fetching.

```yaml
# agents/example-agent.md frontmatter
tools: ["Read", "Grep", "Bash"]
```

## Why it matters

`Bash` is full local-process capability. The artifact can run any command the user could run from a terminal: read files, execute binaries, install software, modify system state, send data outbound. If the README says the artifact "just helps with documentation" but the agent declares `Bash`, the gap between stated purpose and granted capability is a red flag.

In a prompt-injection attack, an adversary can hijack the artifact's `Bash` capability to do anything the user's account can do — including reading SSH keys, exfiltrating credentials, or installing persistence.

## Author-side fix

**If the artifact does not actually need shell access:**

Remove `Bash` from the `tools` array.

**If the artifact does need shell access (e.g. for git operations, file diff, build scripts):**

1. Document the specific commands the artifact will execute in the README under a "Shell access" section.
2. If possible, restrict the artifact's bash usage to a small list of commands and document them. (Claude Code does not natively support per-command allowlisting in plugin frontmatter, but the artifact's own internal logic should constrain what it runs.)
3. Re-run `/cerberus-vet` once the README documents the use.

## adopter-side acceptance

A org unit can accept this risk only if:

1. The artifact's purpose plausibly requires shell access (e.g. a git-history-analyser, a build-system tool, a deployment helper).
2. The internal developer has read the artifact source and confirmed bash usage matches the documented scope.
3. The org unit has agreed via the Approving Authorities (per your organization's AI tool-approval policy) that the artifact will only be used in contexts where local-process risk is acceptable.

Without all three, escalate to the the CISO function for advisory engagement before install.

## Cross-references

- Detection logic: `skills/vet-external-skill/SKILL.md` Step 2 (V1)
- Related: [REM-001](REM-001-excessive-webfetch.md) — Excessive `WebFetch` grant
- Related: [REM-003](REM-003-mcp-arbitrary-shell-tool.md) — MCP arbitrary-shell tool (same risk class via different mechanism)
