# REM-005 — Hardcoded URL to a non-public-API host

**V-layer:** V2 (Network Egress Surface)
**OWASP:** [LLM03:2025 Supply Chain](https://genai.owasp.org/llmrisk/llm032025-supply-chain/)
**Severity at detection:** Critical (paste-bin / ngrok / discord webhook / unknown host) or Important (undocumented but plausible API)
**Status:** stable

## What triggers this

The vetter finds a hardcoded URL in artifact code (Python / JS / TS / shell), and the host is one of:

- A paste service (`pastebin.com`, `hastebin.com`, `gist.github.com/<random>`)
- A tunnel service (`ngrok.io`, `localtunnel.me`, `serveo.net`, `*.trycloudflare.com`)
- A messaging webhook (`discord.com/api/webhooks/...`, `hooks.slack.com/...`)
- A URL-shortener (`bit.ly`, `tinyurl.com`, `t.co`)
- An IP address rather than a domain
- A host that doesn't match any documented vendor in the README

```python
# Highly suspicious in artifact code
WEBHOOK_URL = "https://discord.com/api/webhooks/123/abc"

# Suspicious — unknown host
TELEMETRY_URL = "https://metrics.example-unknown-domain.com/track"

# Suspicious — tunnel
DEV_URL = "https://my-test-12345.ngrok.io/api"
```

## Why it matters

These hosts are classic exfiltration destinations for compromised artifacts. They share three properties:
1. Anyone can register / control them quickly and anonymously.
2. They accept arbitrary inbound HTTP traffic without authentication.
3. They're not standard "vendor API" hosts that a legitimate artifact would call.

A legitimate AI tool integrating with GitHub calls `api.github.com`. A legitimate tool integrating with OpenAI calls `api.openai.com`. A legitimate tool that ships with a webhook to a random discord server is almost always doing something the user didn't sign up for — telemetry-as-exfiltration, command-and-control beaconing, or data leakage.

## Author-side fix

**If the URL is left-over development scaffolding:**

Remove it. Replace with a configurable parameter so the user can supply their own webhook if the feature is needed.

```python
# Before
WEBHOOK_URL = "https://discord.com/api/webhooks/123/abc"

# After
WEBHOOK_URL = os.getenv("ARTIFACT_WEBHOOK_URL")    # user opts in, supplies their own
```

**If the URL is legitimate (e.g. an API endpoint for a service the artifact integrates with):**

1. Document the host and purpose in the README under a "Network endpoints" section.
2. Pin the URL to the canonical API hostname (e.g. `api.example-vendor.com`) rather than a tunnel or staging URL.
3. Document what data is sent and what the response looks like.
4. Re-run `/cerberus-vet` once the README documents the integration.

**If the URL is a webhook for legitimate notification:**

Make it user-configurable rather than hardcoded. The user supplies their own webhook target via env var or config.

## adopter-side acceptance

For paste-bin / tunnel / random-webhook hosts: **do not accept**. Escalate to the the CISO function and the artifact author.

For undocumented-but-plausible hosts (e.g. an API endpoint that looks legitimate but isn't documented): an org unit may accept if:
1. The internal developer verifies via DNS / WHOIS / public docs that the host is associated with a legitimate vendor.
2. The org unit verifies what data is sent and confirms it's non-sensitive in their context.
3. The artifact author is contacted to document the endpoint in the README (so subsequent reviewers don't repeat the verification work).

## Cross-references

- Detection logic: `skills/vet-external-skill/SKILL.md` Step 3 (V2)
- Related: [REM-001](REM-001-excessive-webfetch.md) — Excessive `WebFetch` grant (V2 hardcoded URL often accompanies excessive `WebFetch`)
- Related: [REM-006](REM-006-mcp-http-no-auth.md) — HTTP-transport MCP server without auth (different V2 pattern, same OWASP entry)
