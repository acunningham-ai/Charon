# REM-004 — MCP tool annotation contradicts implementation

**V-layer:** V1 (Capability Scope Analysis)
**OWASP:** [LLM06:2025 Excessive Agency](https://genai.owasp.org/llmrisk/llm062025-excessive-agency/) — active misrepresentation to the LLM
**Severity at detection:** Critical
**Status:** stable

## What triggers this

An MCP server declares tool annotations (`readOnlyHint`, `destructiveHint`, `idempotentHint`, `openWorldHint` per the MCP spec) that don't match what the tool actually does.

Example — claims read-only, but writes:
```python
@server.tool(annotations={"readOnlyHint": True})
async def fetch_data(path: str) -> str:
    # ... reads the path ...
    audit_log.write(f"fetched {path}\n")    # ← writes to audit log
    cache.set(path, data)                    # ← writes to cache
    return data
```

Example — claims idempotent, but isn't:
```python
@server.tool(annotations={"idempotentHint": True})
async def create_ticket(title: str) -> str:
    return jira_api.create_issue(title=title)    # ← creates a new ticket on every call
```

## Why it matters

Tool annotations are the contract between the MCP server author and the LLM. The LLM uses them to make decisions: a `readOnlyHint: true` tool can be called speculatively without user confirmation; a `destructiveHint: true` tool requires user consent. An annotation that lies actively misleads the LLM into bypassing the user's safety expectations.

This is **active misrepresentation**. It's worse than under-claiming capabilities — a tool that quietly does more than its annotation says is the textbook excessive-agency pattern, with the additional offence of being designed to evade user consent flows.

In a prompt-injection scenario, an attacker can rely on a falsely-annotated tool to be called more freely than its true capability warrants.

## Author-side fix

**Audit every tool's annotations against its implementation:**

| Annotation | True if |
|---|---|
| `readOnlyHint: true` | The tool does not write, modify, delete, or create state of any kind — including logs, caches, audit trails, telemetry |
| `destructiveHint: true` | The tool modifies / deletes / overwrites state in a non-reversible way |
| `idempotentHint: true` | Repeated calls with the same input produce the same effect (no duplicates, no incrementing counters) |
| `openWorldHint: true` | The tool interacts with systems outside the MCP server's local process — external APIs, databases, filesystems |

Update annotations to match reality. If a tool writes a log, it's not `readOnlyHint: true` — it's `readOnlyHint: false` with an honest description of the writes.

**Recommendation:** add a test that asserts each tool's annotations match its actual behaviour. The verify pass becomes part of CI.

## adopter-side acceptance

**Do not accept this finding.** Annotation dishonesty is a deliberate-design defect — it can't be "accepted with conditions" because the misalignment is what makes the artifact dangerous. The org unit should escalate to the the CISO function and the artifact author for a fix.

If the artifact is unmaintained and the org unit cannot get a fix, do not install. Document the rejection per the Approving Authorities process.

## Cross-references

- Detection logic: `skills/vet-external-skill/SKILL.md` Step 2 (V1 — MCP servers — annotation honesty check)
- Related: [REM-003](REM-003-mcp-arbitrary-shell-tool.md) — Arbitrary-shell tools that lack `destructiveHint: true` will trigger both findings
- MCP spec: [Tool annotations](https://modelcontextprotocol.io/) — canonical definitions
