# REM-010 — MCP SDK dependency is from a non-canonical source

**V-layer:** V8 (Dependency Footprint — MCP-specific)
**OWASP:** [LLM03:2025 Supply Chain](https://genai.owasp.org/llmrisk/llm032025-supply-chain/)
**Severity at detection:** Important (escalates to Critical when the typosquat package is fetched from a non-canonical URL)
**Status:** stable

## What triggers this

An MCP server's dependency manifest (`package.json` for Node, `requirements.txt` / `pyproject.toml` for Python) lists an MCP-SDK-shaped dependency from a source that isn't the canonical Anthropic publisher.

**Canonical sources:**
- **Node:** `@modelcontextprotocol/sdk`, `@modelcontextprotocol/sdk-typescript` on npm, published by the `@modelcontextprotocol` org
- **Python:** `mcp` on PyPI, published by Anthropic
- **Direct from GitHub:** `github.com/modelcontextprotocol/*` repos

**Typosquats and impostors to flag:**

| Package name | Pattern | Severity |
|---|---|---|
| `@modelcontext-protocol/sdk` (missing hyphen) | Letter substitution | Critical |
| `@modelcontextprotcol/sdk` (missing 'o') | Letter deletion | Critical |
| `mcp-sdk` (from non-canonical author) | Generic name impostor | Important |
| `model-context-protocol` | Spelled-out alternative | Important |
| `@mcp/sdk` (different scope) | Alternative scope | Important |
| `mcp-server`, `mcp-protocol`, `mcp-python` (on PyPI) | Adjacent-name impostors | Important |
| `pip install git+https://github.com/<not-mcp-org>/mcp.git` | Direct GitHub install from non-canonical org | Critical |

## Why it matters

MCP SDKs are foundational dependencies — they handle the protocol layer between the LLM and the server's tool implementations. A compromised MCP SDK can:
- Modify tool descriptions in flight (REM-009-class attack as a library)
- Intercept and exfiltrate tool input/output traffic
- Register hidden additional tools the user can't see in the README
- Phone home with telemetry the canonical SDK wouldn't

Typosquats are documented supply-chain attack vectors. The LiteLLM 1.82.7 / 1.82.8 incident (a similar package-name confusion attack in the LLM ecosystem, cited in Cerberus's own `docs/threat-model.md`) shows the precedent — a small letter substitution in a package name shipped malicious code to thousands of downstream installs.

## Author-side fix

**Use the canonical SDK packages and only the canonical packages.**

**Node:**
```json
{
  "dependencies": {
    "@modelcontextprotocol/sdk": "^1.0.0"
  }
}
```

**Python:**
```
mcp>=1.0.0
```

**Pin to specific versions** in production / shared artifacts so a future supply-chain attack on a transitive dependency doesn't auto-update into the artifact.

**If you've forked the SDK for a legitimate reason** (e.g. patching a bug the canonical version doesn't have yet):

1. Document the fork clearly in the README with a "Why we use a forked MCP SDK" section.
2. Publish the fork under a an organization-controlled scope, not a generic-looking name.
3. Pin to a specific commit SHA from your forked repo, not a moving branch.
4. Maintain a public diff against the canonical SDK so reviewers can see what was changed.

## adopter-side acceptance

**Do not accept** an MCP SDK from a typosquatted or impostor package name. This is one of the cheapest, highest-impact supply-chain attack patterns; there is no legitimate reason to use such a package.

For a documented-fork case (with all four conditions above met), an org unit may accept after:
1. The the CISO function reviews the fork's diff against canonical and confirms no malicious additions
2. The internal developer pins to the documented commit SHA
3. The Approving Authorities sign off per your organization's AI tool-approval policy on the use of forked dependencies

## Cross-references

- Detection logic: `skills/vet-external-skill/SKILL.md` Step 9 (V8 — MCP-specific typosquat patterns)
- Related: REM-013 (planned) — Generic dependency typosquats (non-MCP-specific)
- LiteLLM 1.82.7 / 1.82.8 precedent: documented in Cerberus's own `docs/threat-model.md` L4
- MCP canonical SDK: [npmjs.com/package/@modelcontextprotocol/sdk](https://www.npmjs.com/package/@modelcontextprotocol/sdk) | [pypi.org/project/mcp](https://pypi.org/project/mcp/)
