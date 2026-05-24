---
description: Post-leak response guide. Use when you suspect or know that Claude Code may have seen a real secret (API key, credential, .env file contents). Walks you through rotation, git history cleanup, session invalidation, and enabling ongoing protection.
upstream: JohL29/claude-security-auditor (original Cerberus by Joh Leonhardt)
---

Invoke the cerberus agent to run the leak recovery playbook.

Before starting, ask the engineer three questions:
1. What was potentially leaked? (API key type, service name — not the value itself)
2. Where could it appear? (git history, transcript, memory file, a specific commit)
3. How recently? (today, this week, this month)

Then invoke the rotate-leaked-secret skill to produce a step-by-step recovery runbook tailored to their answers.

Important: Do NOT ask the engineer to show you the actual secret value. You only need the type and location.
