---
description: First-run security hardening wizard for Claude Code. Audits your current setup against the gold standard, walks you through each gap interactively, and verifies the result. Run this before using Claude Code on any company project.
upstream: JohL29/claude-security-auditor (original Cerberus by Joh Leonhardt)
---

Run a complete security audit and hardening session using the cerberus agent.

First, invoke the agent to audit this machine's Claude Code configuration across all 7 security layers (secrets at rest, env vars, egress, prompt injection, supply chain, bypass containment, audit trail).

After the audit, for each Critical or Important finding:
1. Show the engineer the exact change needed (diff format)
2. Ask for confirmation before making any change
3. Delegate settings writes to the update-config skill
4. Re-verify the fix took effect

End by running the verify checklist:
- /status shows all settings sources loaded
- /permissions lists the expected deny rules
- settings.json passes JSON validation
- A test prompt ("show me my .env") is refused

Do not skip findings. Do not accept "I'll fix it later" for Critical findings.
