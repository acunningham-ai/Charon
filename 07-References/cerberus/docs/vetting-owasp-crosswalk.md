# Vetting Threat Model — OWASP LLM Top 10 Crosswalk

The Cerberus `/cerberus-vet` command applies a 9-layer pre-install threat model (V0–V8) against third-party Claude Code plugins, skills, MCP servers, and ChatGPT GPTs. Every layer is grounded in the **OWASP Top 10 for LLM Applications (2025)**.

This crosswalk exists so adopters, auditors, and reviewing security teams can trace each Cerberus finding back to a recognised industry standard. It is not a Cerberus-internal taxonomy.

## Crosswalk Table

| Layer | What Cerberus checks | OWASP LLM Top 10 (2025) entry | Why this OWASP entry |
|---|---|---|---|
| **V0** | Artifact type identification (Claude plugin / skill / MCP server / ChatGPT GPT / generic) | N/A — operational baseline | Determines which subsequent checks apply; not itself a security control |
| **V1** | Capability scope analysis — declared tools vs stated purpose | [LLM06:2025 Excessive Agency](https://genai.owasp.org/llmrisk/llm062025-excessive-agency/) | An artifact declaring `Bash`, `Write`, `WebFetch` for a stated purpose that needs only `Read`/`Grep` is the textbook excessive-agency pattern |
| **V2** | Network egress surface — hardcoded URLs, `curl` / `wget` / `fetch` in code | [LLM03:2025 Supply Chain](https://genai.owasp.org/llmrisk/llm032025-supply-chain/) | Undocumented egress endpoints in third-party LLM components are a supply-chain compromise vector |
| **V3** | File system access patterns — reads of `~/.ssh`, `~/.aws/credentials`, `.env`, `~/.kube/config`, etc. | [LLM02:2025 Sensitive Information Disclosure](https://genai.owasp.org/llmrisk/llm022025-sensitive-information-disclosure/) | Third-party code reading sensitive paths outside its stated purpose enables exfiltration to the model context |
| **V4** | Hook footprint and override risk — broad-matcher PreToolUse hooks, stdin-rewriting hooks, network-calling Stop hooks | [LLM06:2025 Excessive Agency](https://genai.owasp.org/llmrisk/llm062025-excessive-agency/) | Registering third-party code on broad runtime triggers expands the artifact's effective agency beyond user-consented scope |
| **V5** | Project file modification + injection markers in artifact's own markdown | [LLM01:2025 Prompt Injection](https://genai.owasp.org/llmrisk/llm012025-prompt-injection/) | Direct injection (writes to `CLAUDE.md`/`MEMORY.md`) and indirect injection (markers inside the artifact's own files that get loaded into context) are both LLM01 vectors |
| **V6** | Secret exposure — committed secrets, exposed `.env` / `.pem` files, private-key blocks (reuses `secret-pattern-scan.py`) | [LLM02:2025 Sensitive Information Disclosure](https://genai.owasp.org/llmrisk/llm022025-sensitive-information-disclosure/) | Secrets committed inside an artifact become disclosed to any user who installs it |
| **V7** | Authorship & repo-history signals — single-contributor patterns, recent burst of commits, low total commit count | [LLM03:2025 Supply Chain](https://genai.owasp.org/llmrisk/llm032025-supply-chain/) | Provenance and authorship are core supply-chain controls; recently-fabricated high-capability artifacts are a documented supply-chain attack pattern (LiteLLM 1.82.7/1.82.8 precedent) |
| **V8** | Dependency footprint — typosquat patterns, unfamiliar publishers, excessive direct deps | [LLM03:2025 Supply Chain](https://genai.owasp.org/llmrisk/llm032025-supply-chain/) | Transitive dependencies inherit the supply-chain risk surface; typosquats are a documented attack vector |

## OWASP LLM Top 10 (2025) Coverage Map

Reading the table from the other direction — which OWASP entries does Cerberus `/cerberus-vet` cover?

| OWASP LLM Top 10 (2025) entry | Cerberus V-layer(s) | Coverage |
|---|---|---|
| LLM01:2025 Prompt Injection | V5 | Direct + indirect injection markers in artifact files |
| LLM02:2025 Sensitive Information Disclosure | V3, V6 | File system access + committed secrets |
| LLM03:2025 Supply Chain | V2, V7, V8 | Egress + authorship + dependency footprint |
| LLM04:2025 Data and Model Poisoning | (not covered — out of scope for plugin/skill vetting; relevant for training data, not for Claude Code artifacts) | — |
| LLM05:2025 Improper Output Handling | (not directly covered — handled at the host application layer, not at vetting time) | — |
| LLM06:2025 Excessive Agency | V1, V4 | Declared capability scope + hook footprint |
| LLM07:2025 System Prompt Leakage | (partial — V5's CLAUDE.md scan adjacent; not the primary control) | partial |
| LLM08:2025 Vector and Embedding Weaknesses | (not covered — relevant to RAG implementations, not directly to plugin vetting) | — |
| LLM09:2025 Misinformation | (not a pre-install vetting concern — runtime quality issue) | — |
| LLM10:2025 Unbounded Consumption | (not a pre-install vetting concern — runtime quota issue) | — |

**Direct coverage:** LLM01, LLM02, LLM03, LLM06.
**Adjacent / partial:** LLM07.
**Out of scope at vetting time:** LLM04, LLM05, LLM08, LLM09, LLM10 (these are runtime / deployment-architecture controls, not pre-install controls).

This is the expected coverage profile for a pre-install vetting tool. The four directly-covered entries are the four OWASP LLM Top 10 entries that can meaningfully be assessed by inspecting an artifact's source code before installation. The remaining six require runtime telemetry, training-data access, or deployment-architecture review and are properly addressed by other controls in a defence-in-depth stack.

## MCP server–specific patterns

MCP (Model Context Protocol) servers are a class of LLM-extending artifact with a distinct attack surface compared to in-process plugins. The V-layer threat model covers them, but each layer applies MCP-specific patterns. These patterns map to the same OWASP entries as the generic layers:

| MCP-specific pattern | V-layer | OWASP entry |
|---|---|---|
| **Tool schema audit** — enumeration of declared tools, descriptions, input schemas, and tool annotations (`readOnlyHint`, `destructiveHint`, etc. per the MCP spec) | V1 | LLM06:2025 Excessive Agency |
| **Dangerous single tools** — one tool that executes arbitrary shell commands or reads arbitrary file paths with no allowlist | V1 | LLM06:2025 Excessive Agency |
| **Honesty of tool annotations** — a tool claims `readOnlyHint: true` but the implementation writes / modifies state | V1 | LLM06:2025 Excessive Agency (active misrepresentation to the LLM) |
| **Transport identification** — stdio vs HTTP vs SSE vs WebSocket. Determines whether subsequent V2 checks treat the artifact as a local subprocess or a network service | V0 / V2 | (operational) / LLM03:2025 Supply Chain |
| **Auth scheme on HTTP-transport servers** — MCP spec requires OAuth 2.0 with PKCE for HTTP transport. No auth → critical; weak auth (bearer-in-URL, static API key) → important | V2 | LLM03:2025 Supply Chain |
| **Bind address on HTTP-transport servers** — `0.0.0.0` (public) vs `127.0.0.1` (local-only). Public bind + tool-executing capabilities + weak auth = remote-RCE class risk | V2 | LLM03:2025 Supply Chain |
| **Tool-description poisoning** — adversarial prompt-injection content embedded in tool descriptions, which the LLM reads into context on `tools/list` | V5 | LLM01:2025 Prompt Injection |
| **MCP SDK typosquats** — non-canonical packages claiming MCP SDK functionality (e.g. `@modelcontextprotcol/sdk` missing-letter variants). Canonical sources: `@modelcontextprotocol/*` on npm, `mcp` on PyPI | V8 | LLM03:2025 Supply Chain |
| **Resource scope** — `resources/list` advertising `file:///**` or broad URI templates | V3 | LLM02:2025 Sensitive Information Disclosure |

The MCP-specific patterns deepen the threat model without changing the OWASP grounding — they're sharper detectors for the same risk classes, oriented at the specific attack surface MCP servers present.

**Reference:** [Model Context Protocol specification](https://modelcontextprotocol.io/) for the canonical auth scheme, transport types, and tool annotations.

## Reporting

When `/cerberus-vet` produces a Risk Assessment, each finding cites the applicable V-layer **and** its OWASP LLM Top 10 (2025) entry. Example:

```
Finding: Artifact declares WebFetch tool but README does not document any network use.
Severity: Important (confidence: 82)
Layer: V1 (Capability Scope Analysis)
OWASP: LLM06:2025 Excessive Agency
Evidence: agents/example-agent.md frontmatter:
    tools: ["Read", "Grep", "WebFetch"]
README.md describes only local file analysis — no documented network requirement.
Risk: Granting WebFetch on install allows the artifact to make arbitrary outbound requests at runtime, including potential exfiltration of in-context data.
Mitigation: Either remove WebFetch from agent frontmatter, or update README to document the specific endpoints and data being sent.
```

This format makes the OWASP grounding visible at the point of the finding — auditors and reviewing security teams can confirm the finding is implementing a recognised standard, not a Cerberus-internal opinion.

The Risk Assessment itself produces a **risk level** (LOW / MEDIUM / HIGH / CRITICAL) plus a 0–100 score. Tool-approval authority sits with the Approving Authorities per your organization's AI tool-approval policy — this report is risk evidence that informs their decision, not itself an approval or rejection.

## References

- OWASP Top 10 for LLM Applications (2025) — <https://genai.owasp.org/llm-top-10/>
- LLM01:2025 Prompt Injection — <https://genai.owasp.org/llmrisk/llm012025-prompt-injection/>
- LLM02:2025 Sensitive Information Disclosure — <https://genai.owasp.org/llmrisk/llm022025-sensitive-information-disclosure/>
- LLM03:2025 Supply Chain — <https://genai.owasp.org/llmrisk/llm032025-supply-chain/>
- LLM06:2025 Excessive Agency — <https://genai.owasp.org/llmrisk/llm062025-excessive-agency/>
- LiteLLM 1.82.7 / 1.82.8 supply-chain incident (cited in Cerberus L4 threat-model.md) — referenced as authorship-signal precedent for V7
