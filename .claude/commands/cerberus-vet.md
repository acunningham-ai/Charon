---
description: Run a pre-install security risk assessment of a third-party Claude Code plugin, skill, or MCP server. Takes a GitHub repo URL as argument, scans the contents against the Cerberus threat model, and produces a Risk Assessment with risk level (LOW / MEDIUM / HIGH / CRITICAL), score (0-100), and findings. Output is risk evidence — final tool-approval authority sits with the Approving Authorities per your organization's AI tool-approval policy. Read-only; does NOT install anything. Safe to run at any time.
upstream: JohL29/claude-security-auditor (original Cerberus by Joh Leonhardt)
---

Run a risk assessment on the third-party artifact at the GitHub repo URL provided as the argument: $ARGUMENTS

Use the `vet-external-skill` skill to perform the assessment. The skill will clone the repo to a sandbox directory, walk the file tree, apply the Cerberus threat model (V0-V8), and produce a Risk Assessment.

Make NO changes to the user's Claude Code installation, settings, or plugin set. This is pre-install assessment only — the artifact is NOT installed by this command.

Produce the **Risk Assessment** with risk level (LOW / MEDIUM / HIGH / CRITICAL RISK), score (0-100), Critical / Important findings, what passed cleanly, and recommended next step.

**Frame the output as risk evidence, not approval.** Final tool-approval decision sits with the Approving Authorities (as defined by your organization) per your organization's AI tool-approval policy.

If the risk level is **CRITICAL**, end with: "Risk level is CRITICAL. Do not proceed with install. Forward this assessment to your AI governance reviewer or the CISO function for risk review. The final tool-approval decision sits with the Approving Authorities per your organization's AI tool-approval policy — this report is risk evidence, not an approval decision."

If the risk level is **HIGH**, end with: "Risk level is HIGH. Author engagement is needed to address the findings. Re-run /cerberus-vet after the artifact has been updated. The final tool-approval decision sits with the Approving Authorities per your organization's AI tool-approval policy — this report is risk evidence, not an approval decision."

If the risk level is **MEDIUM**, end with: "Risk level is MEDIUM. Risk evidence supports proceeding subject to the documented mitigation or acceptance for each Important finding. The final tool-approval decision sits with the Approving Authorities per your organization's AI tool-approval policy — this report is risk evidence, not an approval decision."

If the risk level is **LOW**, end with: "Risk level is LOW. No material risk surfaced by this assessment. The final tool-approval decision sits with the Approving Authorities per your organization's AI tool-approval policy — this report is risk evidence, not an approval decision."
