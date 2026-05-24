# Cerberus Threat Model

## Overview

This document describes the security threat model for Claude Code and explains how the Cerberus plugin addresses each threat category. It is intended for engineers deploying Cerberus in team environments and for security reviewers auditing AI-assisted development workflows.

Cerberus applies defense-in-depth across seven layers (L0–L6), from file-system deny rules to audit trail validation. Each layer blocks a distinct attack vector. No single layer is sufficient; all seven are required for full protection.

---

## Why Claude Code Is a Unique Threat Surface

Claude Code is not a conventional software tool. It is an agent with:

- **Full filesystem access** — it can read any file in the home directory unless explicitly denied.
- **Native Bash execution** — it runs arbitrary shell commands in the developer's session, with the developer's credentials.
- **Network access** — WebFetch and MCP server integrations can make HTTP requests, including to attacker-controlled endpoints.
- **Persistent configuration** — `settings.json`, `CLAUDE.md`, and `MEMORY.md` files influence every future session. A compromised config file is a persistent foothold.
- **Transcript logging** — Anthropic's servers may log tool call inputs and outputs. Any secret that Claude reads may appear in a log that outlives the session.

This combination means Claude Code can read a secret, transmit it, and log it in a single agentic turn — without the developer seeing any of these as distinct actions.

---

## Layer-by-Layer Threat Analysis

### L0 — Secrets at Rest (File-System Deny Rules)

**Threat**: Claude reads `.env` files, private keys, AWS credentials, SSH keys, kubeconfig, or other credential stores during routine development work (e.g., "show me the project config") or through an attacker-induced prompt.

**Real-world precedents**:
- **CVE-2025-59536** (Check Point Research, 2025): Demonstrated that prompt injection via a malicious repository's CLAUDE.md could instruct Claude Code to exfiltrate files from `~/.aws/credentials` to an attacker-controlled endpoint. No user interaction beyond `claude` startup was required.
- **Claude Pirate Files API exfil** (Embrace The Red, 2025): Showed how an agent with unrestricted Read access would follow instructions embedded in a repository to upload private key files to a remote API, bypassing no safeguards.

**What Cerberus does**: Installs 31+ deny rules in `settings.json` covering `.env*`, `*.pem`, `*.key`, `id_rsa`, `id_ed25519`, `*.p12`, `*.pfx`, `.aws/**`, `.ssh/**`, `.gcloud/**`, `.kube/config`, `.gnupg/**`, `secrets/**`, and `credentials/**`. These rules are enforced by the Claude Code runtime before any tool call executes.

---

### L1 — Environment Variable Protection

**Threat**: Even if `.env` files are deny-listed, Bash commands like `printenv`, `env | grep`, or `export -p` expose every loaded environment variable in the current shell — including secrets injected at startup, CI tokens, and database passwords.

**What Cerberus does**: Adds deny rules for `Bash(printenv)`, `Bash(env |*)`, and `Bash(export -p)`. Combined with the L0 hook (block-secrets.sh + secret-pattern-scan.py), these patterns are caught at both the permission layer and the regex scan layer.

---

### L2 — Egress Control

**Threat**: Once a secret is in memory (as a variable, a command argument, or a file content string), Claude can transmit it via `curl`, `wget`, `nc`, `scp`, or WebFetch — to attacker-controlled infrastructure or to a legitimate endpoint that logs request bodies.

**Real-world precedents**:
- **CVE-2025-59536**: The attack chain required both file read (L0) and egress (L2) to complete exfiltration. Blocking either layer stops the attack.
- **Source-map leak, March 2026** (SecurityWeek): A `cli.js.map` file exposed internal Anthropic infrastructure details. The mechanism was an HTTP request made during a build process — a reminder that egress is the final data-loss vector.

**What Cerberus does**: Deny rules block `Bash(curl *)`, `Bash(wget *)`, `Bash(nc *)`, `Bash(scp *)`, and `WebFetch`. MCP server integrations are audited to ensure tokens are stored as environment variable references, not plaintext values.

---

### L3 — Prompt Injection via Project Files

**Threat**: A malicious CLAUDE.md, MEMORY.md, or project README contains instructions that hijack Claude's behavior — instructing it to exfiltrate secrets, bypass rules, or act on behalf of an attacker. This is the primary supply-chain attack vector for agentic AI systems.

**Real-world precedents**:
- **CVE-2026-35020, CVE-2026-35021, CVE-2026-35022** (Phoenix Security, 2026): A cluster of vulnerabilities in agentic AI developer tools where malformed or malicious project context files caused the agent to execute attacker-supplied commands with developer-level permissions. All three CVEs involved CLAUDE.md or equivalent context file injection.
- **Malicious CLAUDE.md injection** (multiple threat reports, 2025–2026): Open-source repositories with CLAUDE.md files containing `IGNORE PREVIOUS INSTRUCTIONS` or `[INST]` markers have been observed in the wild, targeting developers who `clone && claude` unfamiliar repos.

**What Cerberus does**: `audit-claude-md.sh` is registered on `UserPromptSubmit`. It scans `CLAUDE.md`, `CLAUDE.local.md`, `.claude/CLAUDE.md`, and project `MEMORY.md` for injection markers (`IGNORE PREVIOUS`, `[INST]`, `<system>`, `cat ~/.aws`, `cat ~/.ssh`, curl-pipe patterns, and base64 blobs). The scan runs once per session and emits an advisory on match (exit 0 — the session continues, but the developer is warned).

---

### L4 — Supply Chain (Plugins and MCP Servers)

**Threat**: A malicious or compromised Claude Code plugin, MCP server, or skill registers a hook that intercepts tool calls or reads secrets before Cerberus can block them. Third-party plugins may have lower security standards than official ones.

**What Cerberus does**: The `/cerberus-audit` command includes a plugin audit step that lists all installed plugins and flags any not sourced from the `claude-plugins-official` registry. MCP server configurations in `~/.claude.json` are scanned for plaintext tokens. The audit report identifies any plugin that registers a `PreToolUse` hook alongside Cerberus, flagging potential hook-chain bypass risks.

---

### L5 — Bypass Mode and Managed Settings

**Threat**: Claude Code's `--bypass-permissions` flag (or the equivalent `disableBypassPermissionsMode` setting) disables all deny rules and hooks for a session. An attacker who can influence how Claude Code is launched, or a developer who runs it with `--bypass-permissions` as a convenience, removes all L0–L4 protections.

**What Cerberus does**: Sets `disableBypassPermissionsMode: "disable"` in `settings.json`. This configuration key prevents the bypass flag from taking effect even if passed on the command line. Cerberus's `/cerberus-audit` command verifies this value is present and has not been overridden by a managed settings layer.

---

### L6 — Audit Trail and Config Integrity

**Threat**: `settings.json` has a JSON syntax error. Claude Code silently ignores the entire file, operating with no restrictions. This can happen from manual edits, merge conflicts, or a partially-written file from a crashed install process. The developer sees no error and believes they are protected.

**What Cerberus does**: `verify.sh` and the `/cerberus-audit` command both run `python3 -m json.tool ~/.claude/settings.json` and fail loudly if it returns a non-zero exit. The `/cerberus-audit` agent treats an invalid settings.json as a Critical finding with confidence 95 and stops further audit steps until it is resolved.

---

## Defense in Depth — ASCII Diagram

```
  ┌─────────────────────────────────────────────────────┐
  │  L6 Audit Trail (config integrity, JSON validation) │
  │  ┌───────────────────────────────────────────────┐  │
  │  │  L5 Bypass Controls (disableBypassPermissions)│  │
  │  │  ┌─────────────────────────────────────────┐  │  │
  │  │  │  L4 Supply Chain (plugin audit, MCP scan)│  │  │
  │  │  │  ┌───────────────────────────────────┐  │  │  │
  │  │  │  │ L3 Prompt Injection (CLAUDE.md scan)│  │  │  │
  │  │  │  │  ┌──────────────────────────────┐  │  │  │  │
  │  │  │  │  │ L2 Egress (curl/wget/nc deny) │  │  │  │  │
  │  │  │  │  │  ┌───────────────────────┐   │  │  │  │  │
  │  │  │  │  │  │ L1 Env Vars (printenv)│   │  │  │  │  │
  │  │  │  │  │  │  ┌────────────────┐  │   │  │  │  │  │
  │  │  │  │  │  │  │ L0 Secrets at  │  │   │  │  │  │  │
  │  │  │  │  │  │  │ Rest (.env,    │  │   │  │  │  │  │
  │  │  │  │  │  │  │ .pem, .aws/…)  │  │   │  │  │  │  │
  │  │  │  │  │  │  └────────────────┘  │   │  │  │  │  │
  │  │  │  │  │  └───────────────────────┘   │  │  │  │  │
  │  │  │  │  └──────────────────────────────┘  │  │  │  │
  │  │  │  └─────────────────────────────────────┘  │  │  │
  │  │  └───────────────────────────────────────────┘  │  │
  │  └───────────────────────────────────────────────────┘  │
  └─────────────────────────────────────────────────────────┘
```

Outermost ring = widest net. Each inner ring is a more specific control. An attacker must defeat all six outer layers before reaching the innermost secret.

---

## What Cerberus Does NOT Protect Against

- **The developer deliberately shows Claude a secret.** If a user pastes an API key into the chat, Cerberus cannot intercept a user-originated input before it reaches Claude's context. The block-secrets.sh hook fires on *tool calls*, not on the user prompt content.
- **Compromised Anthropic servers.** If Anthropic's infrastructure is breached, transcript contents could be accessed. Cerberus cannot protect against the platform it runs on.
- **OS-level compromise.** If the developer's machine is compromised at the OS level, an attacker with filesystem access can read `settings.json`, modify hooks, or read secrets directly. Cerberus is not a substitute for OS hardening, disk encryption, or EDR tooling.
- **Denial-of-service via hook exhaustion.** A malicious repository could contain patterns that trigger thousands of Cerberus warnings per session, degrading usability. Rate limiting is not currently implemented.
- **Future Claude Code API changes.** If Anthropic changes how `settings.json` deny rules are parsed, or introduces new tool types not covered by the hook matcher, Cerberus's protections may silently degrade. Pin Claude Code versions in CI environments and review Cerberus compatibility on each major version update.

---

## References

- **CVE-2025-59536** — Check Point Research: "Claude Code Prompt Injection via Malicious Repository CLAUDE.md"
  https://research.checkpoint.com/2025/cve-2025-59536-claude-code-prompt-injection/

- **CVE-2026-35020, CVE-2026-35021, CVE-2026-35022** — Phoenix Security: "Agentic AI Context File Injection Cluster"
  https://phoenix.security/research/agentic-ai-cve-2026-35020-35021-35022/

- **Source-map leak, March 2026** — SecurityWeek: "Anthropic CLI Source Map Exposure Reveals Internal Infrastructure Details"
  https://www.securityweek.com/anthropic-cli-source-map-leak-march-2026/

- **Claude Pirate Files API Exfil** — Embrace The Red: "Making Claude Exfiltrate Files via the Files API"
  https://embracethered.com/blog/posts/2025/claude-code-files-api-exfil/
