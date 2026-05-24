# REM-006 — HTTP-transport MCP server with no auth

**V-layer:** V2 (Network Egress Surface — MCP transport-aware)
**OWASP:** [LLM03:2025 Supply Chain](https://genai.owasp.org/llmrisk/llm032025-supply-chain/)
**Severity at detection:** Critical when combined with tool-executing capabilities; Important when the server exposes read-only tools and binds to localhost
**Status:** stable

## What triggers this

An MCP server uses HTTP or SSE transport (i.e. exposes itself as a network service rather than running as a subprocess) and does not implement the OAuth 2.0 with PKCE authentication scheme that the MCP specification requires for HTTP transport. Combined with a public bind address (`0.0.0.0` rather than `127.0.0.1`), this is a Critical finding because the server is reachable from any host on the network with no authentication wall.

Indicators in code:
```typescript
const transport = new SSEServerTransport("/mcp", res);
// ... no auth middleware ...
app.listen(3000, "0.0.0.0");    // public bind, no auth
```

```python
# starlette / FastAPI MCP server with no auth check
app.mount("/mcp", mcp_app)
uvicorn.run(app, host="0.0.0.0", port=8000)
```

## Why it matters

An MCP server is a privileged tool-execution endpoint. The LLM connected to it can read files, call APIs, modify state — whatever tools the server exposes. Without authentication:

- Anyone on the network with the URL can connect and invoke the same tools.
- Combined with an arbitrary-shell tool (REM-003), this is remote code execution as a service.
- Combined with file-read tools, this is data exfiltration as a service.
- Even read-only tools become a reconnaissance vector — what data does this server have access to?

The MCP specification was designed with this risk in mind: the spec requires OAuth 2.0 with PKCE for HTTP transport. A server that skips auth is non-conformant with the spec.

## Author-side fix

**Implement OAuth 2.0 with PKCE per the MCP spec.**

The MCP TypeScript SDK and Python SDK both provide auth-helper modules. Reference implementations are in the MCP specification documentation. At minimum:

1. The server exposes a metadata endpoint advertising its OAuth authorization server.
2. Clients (Claude Code) authenticate via the OAuth flow with PKCE.
3. The server validates bearer tokens on every request.
4. Tokens expire and rotate.

**Interim measures if full OAuth is not viable yet:**

- **Bind to `127.0.0.1` only.** Local-only is dramatically lower risk than public. If the server is for the local user, it should never bind to `0.0.0.0`.
- **Require a shared secret in a header.** Much weaker than OAuth, but better than nothing. Document the rotation policy.
- **Document the gap in the README.** Mark the server as "local-only, no auth — do not expose publicly".

**Update tool annotations.** If auth is missing and tools are destructive, ensure `destructiveHint: true` is set so clients can warn users.

## adopter-side acceptance

For **HTTP-transport + public bind + no auth + destructive tools**: **do not accept**. This is the worst-case configuration and should never be installed.

For **HTTP-transport + localhost-only + no auth + read-only tools**: a org unit may accept for a single-user local-dev context, provided:
1. The host doesn't run untrusted other code that could connect to the local port.
2. The org unit agrees not to expose the server externally.
3. The artifact author is asked to add auth before the next rollout.

For **stdio-transport MCP servers**: this finding doesn't apply. stdio servers are subprocess-coupled and don't need network auth.

## Cross-references

- Detection logic: `skills/vet-external-skill/SKILL.md` Step 3 (V2 — MCP transport-aware)
- Related: [REM-003](REM-003-mcp-arbitrary-shell-tool.md) — Arbitrary-shell tool (combination = remote RCE)
- Related: [REM-005](REM-005-suspicious-hardcoded-url.md) — Suspicious hardcoded URL (different V2 pattern)
- MCP spec: [Authentication](https://modelcontextprotocol.io/)
