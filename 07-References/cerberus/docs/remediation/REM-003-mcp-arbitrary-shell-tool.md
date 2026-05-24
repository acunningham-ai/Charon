# REM-003 — MCP server exposes a tool that executes arbitrary shell

**V-layer:** V1 (Capability Scope Analysis)
**OWASP:** [LLM06:2025 Excessive Agency](https://genai.owasp.org/llmrisk/llm062025-excessive-agency/)
**Severity at detection:** Critical
**Status:** stable

## What triggers this

An MCP server declares a tool whose input is an arbitrary shell command string with no allowlist or sandboxing. Common shapes:

```python
@server.tool()
async def run_command(cmd: str) -> str:
    return subprocess.check_output(cmd, shell=True).decode()
```

```typescript
server.tool("execute", { command: z.string() }, async ({ command }) => {
  return { content: [{ type: "text", text: execSync(command).toString() }] };
});
```

If the MCP server has one tool that can run anything, the entire server is effectively "remote code execution as a service" to whatever LLM is connected.

## Why it matters

The user installs an MCP server believing it provides specific capabilities (e.g. "git operations" or "file analysis"). One arbitrary-shell tool gives the LLM unrestricted local-process access — equivalent to handing over the keyboard. Combined with prompt injection (an attacker convincing the LLM to call the tool with their command), this is a full RCE path that bypasses every other protection in the user's setup.

The MCP spec's `destructiveHint` annotation should be `true` for tools that can modify state. A tool that runs arbitrary shell is the most destructive possible tool, and any artifact that doesn't annotate it as such is also failing the honesty test (see REM-004).

## Author-side fix

**Replace the arbitrary-shell tool with a small set of purpose-specific tools.**

Before:
```python
@server.tool()
async def run_command(cmd: str) -> str:
    return subprocess.check_output(cmd, shell=True).decode()
```

After:
```python
@server.tool()
async def git_status() -> str:
    return subprocess.check_output(["git", "status", "--porcelain"]).decode()

@server.tool()
async def git_log(limit: int = 20) -> str:
    return subprocess.check_output(["git", "log", "-n", str(limit), "--oneline"]).decode()
```

The new tools:
- Use list-form `subprocess` args (no `shell=True`)
- Have constrained input types (`int` for limit, no free-form strings)
- Are named for their specific purpose
- Can be properly annotated with `readOnlyHint: true`

**If the artifact genuinely needs arbitrary-shell capability** (vanishingly rare and almost always wrong):

1. Require explicit per-invocation user consent in the MCP server's authentication / authorization layer.
2. Constrain by allowlist of permitted commands.
3. Annotate the tool with `destructiveHint: true` and a description that warns the user explicitly.
4. Document in the README why no narrower tool design works.

## adopter-side acceptance

**Do not accept this finding.** An arbitrary-shell tool on an MCP server is a Critical finding for a reason — the design is fundamentally insecure for any production or shared-machine use. Escalate to the the CISO function for advisory engagement.

If an org unit has a one-off, single-user, local-dev use case where the risk is contained, document it explicitly with the Approving Authorities per your organization's AI tool-approval policy and time-box the approval.

## Cross-references

- Detection logic: `skills/vet-external-skill/SKILL.md` Step 2 (V1 — MCP servers)
- Related: [REM-002](REM-002-excessive-bash.md) — Excessive `Bash` grant (Claude plugin equivalent)
- Related: [REM-004](REM-004-mcp-annotation-dishonesty.md) — MCP annotation dishonesty (almost always accompanies REM-003)
- MCP spec: [Tool annotations](https://modelcontextprotocol.io/)
