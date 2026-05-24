---
description: Read-only security audit of your Claude Code setup. Scores your configuration against the 7-layer Cerberus threat model and produces a report. No changes are made. Safe to run at any time.
upstream: JohL29/claude-security-auditor (original Cerberus by Joh Leonhardt)
---

Run a read-only security audit using the cerberus agent.

Audit scope: all 7 threat layers (L0 secrets-at-rest, L1 env-vars, L2 egress, L3 prompt-injection, L4 supply-chain, L5 bypass-containment, L6 audit-trail).

Make NO changes to any files or settings during this audit. This is a diagnostic only.

Produce the Security Audit Report with score, Critical/Important findings, what's working, and recommended next step.

If you find Critical issues, end the report with: "Run /cerberus-setup to fix these findings."
