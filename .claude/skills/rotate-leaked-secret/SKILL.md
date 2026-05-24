---
name: rotate-leaked-secret
description: "Post-leak runbook for credential rotation and incident response. Use when a secret, API key, token, or credential has been exposed, committed to git, read by Claude, found in a transcript, or potentially exfiltrated. Trigger on: 'my secret leaked', 'key was exposed', 'rotate my credentials', 'api key committed to git', 'secret in transcript', 'credential rotation', 'revoke leaked key', 'incident response', 'secret in git history', 'cerberus rotate'."
---

# rotate-leaked-secret

## Purpose

A structured five-phase runbook for responding to a credential leak. The AI walks alongside as a guide — this is not automated remediation. Each phase requires human confirmation before moving to the next. The runbook adapts to the type of credential involved.

## Critical Constraint

**Never ask the engineer to share or paste the actual secret value.** You don't need it to guide the rotation. If the user volunteers it, do not echo it back, do not include it in any report, and remind them not to paste it anywhere.

## When to Use

- An API key or token was found in a committed file
- A secret appeared in a Claude conversation transcript or memory file
- A `.env` file was accidentally read by Claude or another AI tool
- A credential was spotted in git history, logs, or a screenshot
- You suspect a secret may have been exfiltrated

---

## Phase 1 — Immediate Containment (Do Now)

**Objective:** Revoke the credential at the source before anything else. This stops active misuse.

### Action: Revoke at the provider

Go to the provider's credential management console and revoke or delete the exposed key immediately. Do not wait for scope assessment — revoke first.

Provider-specific links (use whichever applies):

| Provider | Revocation URL |
|---|---|
| AWS | IAM console → Security credentials → Access keys → Deactivate/Delete |
| GitHub | github.com → Settings → Developer settings → Personal access tokens |
| Anthropic | console.anthropic.com → API keys |
| Slack | api.slack.com/apps → Your app → OAuth & Permissions → Revoke |
| OpenAI | platform.openai.com → API keys |
| GCP | console.cloud.google.com → IAM & Admin → Service accounts |
| Azure | portal.azure.com → Azure Active Directory → App registrations |

If the provider is not listed, locate their "API keys" or "credentials" management page. Revocation should be possible within the dashboard.

### Action: Do NOT commit the revoked key

The empty value or placeholder does not need to be committed. The key was revoked at the provider — that is sufficient. Committing a placeholder (`sk-REVOKED`, `""`, etc.) is unnecessary and can obscure the history of what happened.

### Action: Database credentials require extra care

If the leaked credential is a database password:
1. Rotate the password at the database level (not just the application config).
2. Check whether any active connection is currently authenticated with the old credential. Most database consoles show active sessions — terminate sessions using the old credential after rotating.
3. Update connection strings in all environment configs and secret managers.

**Confirm Phase 1 complete before continuing.**

> "Have you revoked the credential at the provider console? Confirm before moving to scope assessment."

---

## Phase 2 — Scope Assessment

**Objective:** Understand what the credential could have accessed and for how long.

### Search git history

Run the following to find commits that touched env files:

```bash
git log --all --full-history -- "*.env" "*.env.*"
```

Note the earliest commit date — that is the earliest point the credential was potentially exposed in the repository.

### Check Claude transcript and memory files

If Claude Code is installed, check project memory files for any mention of the credential type:

```bash
ls ~/.claude/projects/
```

Open any memory files for the relevant project and search for the credential type (e.g. "API key", "token", "database password"). Do not search for the literal value — search for the key name or credential category.

Also check if any Claude transcript files exist in the project directory:

```bash
find . -name "*.jsonl" -path "*claude*" 2>/dev/null
```

### Assess blast radius

Determine what services and data the credential could have accessed:
- What permissions did the credential carry? (admin, read-only, scoped to one service?)
- What data stores or APIs were accessible?
- Were there any API call logs at the provider showing activity under this credential during the exposure window?

Document the blast radius assessment even if it is incomplete. This is needed for any incident report.

**Confirm Phase 2 complete before continuing.**

> "Have you noted the exposure window and assessed what the credential could access? Confirm before moving to history cleanup."

---

## Phase 3 — History Cleanup (If Credential Was Committed to Git)

**Objective:** Remove the secret from git history so it cannot be retrieved from past commits.

Skip this phase if the credential was never committed to git (e.g. it was only in a transcript or memory file).

### Use git filter-repo

Use `git filter-repo` to rewrite history. This is the current recommended tool. **Do not use `git filter-branch`** — it is deprecated, significantly slower, and has known correctness problems with complex histories.

Install if needed:
```bash
pip install git-filter-repo
# or: brew install git-filter-repo
```

To remove all `.env` files from history:
```bash
git filter-repo --path-glob '*.env' --invert-paths
```

To remove a specific file by path:
```bash
git filter-repo --path path/to/secretfile --invert-paths
```

To replace a specific string pattern (if only the value needs removal):
```bash
git filter-repo --replace-text <(echo 'OLDVALUE==>REDACTED')
```

### Force-push requires team coordination

After rewriting history, all existing clones of the repository have diverged. You must:
1. Notify all team members that a force-push is coming and they must re-clone.
2. Force-push all affected branches: `git push --force-with-lease origin <branch>`
3. Have team members discard their local copies and re-clone from origin.
4. If the repository is on GitHub or GitLab: invalidate any tokens or deploy keys that could access the old history (GitHub can purge cached views of old commits via support, though it takes time).

**Warn the user about force-push scope before they run it.** Force-pushing rewrites shared history — coordinate with the team first.

**Confirm Phase 3 complete before continuing.**

> "Have you rewritten git history with git filter-repo and coordinated the force-push with your team? Confirm before moving to protection setup."

---

## Phase 4 — Enable Ongoing Protection

**Objective:** Prevent the same class of incident from recurring.

### Verify Cerberus hooks

Check that the Cerberus PreToolUse hook is installed and active:

```bash
cat ~/.claude/settings.json | python3 -m json.tool | grep -A5 "PreToolUse"
```

The output should show a hook that runs `block-secrets.sh` (or equivalent) before Bash tool calls. If this hook is absent, run `/harden-claude-setup` to install it.

### Enable GitHub push protection and secret scanning

If the repository is on GitHub:
- **Secret scanning**: Repository Settings → Security → Code security and analysis → Secret scanning → Enable
- **Push protection**: Same section → Push protection → Enable

Push protection blocks commits containing known secret formats before they reach the remote. Enable it now so future pushes are gated.

### Consider migrating from .env files to a secrets manager

`.env` files on disk are a persistent exposure risk. Consider migrating to:
- **1Password Secrets Automation** — retrieves secrets at runtime, no file on disk
- **Doppler** — syncs secrets to CI/CD and local dev without .env files
- **HashiCorp Vault** — self-hosted, enterprise-grade secret storage
- **AWS Secrets Manager** — native integration for AWS workloads

A secrets manager eliminates the class of leak that comes from `.env` files being read, committed, or left in shell history.

**Confirm Phase 4 complete before continuing.**

> "Have you verified the Cerberus hooks and enabled push protection? Confirm before moving to verification."

---

## Phase 5 — Verify and Document

**Objective:** Confirm the revoked credential no longer works, and create an incident record.

### Verify the credential is dead

Make a test API call using the revoked credential. The response should be a 401 Unauthorized or equivalent authentication error. A 200 response means revocation did not take effect — return to Phase 1.

```bash
# Example for a generic REST API (adapt to your provider):
curl -I -H "Authorization: Bearer <REVOKED_KEY>" https://api.example.com/v1/test
# Expected: HTTP 401
```

Do not share the key value in chat to perform this test — run it in your terminal.

### Document the incident

Write a brief incident record covering:
- What type of credential leaked (do not include the value)
- When it was first exposed (earliest git commit date or other evidence)
- When revocation was performed
- Blast radius assessment: what the credential could have accessed
- What cleanup was done (history rewrite, team notification, etc.)
- What protection was enabled to prevent recurrence

### Consider notifying affected parties

If the leaked credential had access to sensitive data belonging to other users, customers, or partners:
- Consult your organization's incident response policy.
- Depending on jurisdiction and data type, breach notification may be legally required.
- Loop in your security team or legal counsel if in doubt.

**Confirm Phase 5 complete.**

> "Has the revoked credential tested as 401? Is the incident documented? The rotation runbook is complete."

---

## Summary

| Phase | Action | Required |
|---|---|---|
| 1 | Revoke at provider | Yes — do this first |
| 2 | Assess scope and exposure window | Yes |
| 3 | Rewrite git history with git filter-repo | Only if committed to git |
| 4 | Enable Cerberus hooks and push protection | Yes |
| 5 | Verify revocation and document | Yes |
