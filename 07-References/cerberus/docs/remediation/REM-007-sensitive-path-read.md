# REM-007 — Code reads sensitive filesystem paths without documented need

**V-layer:** V3 (File System Access Patterns)
**OWASP:** [LLM02:2025 Sensitive Information Disclosure](https://genai.owasp.org/llmrisk/llm022025-sensitive-information-disclosure/)
**Severity at detection:** Critical for SSH / AWS / kube creds; Important for `.env` files
**Status:** stable

## What triggers this

Artifact code reads from a filesystem path that's well-known to contain secrets:

```python
# Critical — reads SSH private keys
with open(os.path.expanduser("~/.ssh/id_rsa")) as f:
    key = f.read()

# Critical — reads AWS credentials
with open(os.path.expanduser("~/.aws/credentials")) as f:
    creds = configparser.read(f)

# Important — reads .env file
with open(".env") as f:
    env_vars = dotenv.load(f)
```

If the artifact's stated purpose doesn't involve managing those credentials (e.g. it's a "documentation helper" but reads `~/.ssh/`), this is a Critical finding. The read might be benign (e.g. checking if a config exists) or it might be exfiltration. The vetter can't tell from the code alone — that's why the documented justification matters.

## Why it matters

These paths are the most common location for high-value secrets on a developer machine:

- `~/.ssh/id_rsa`, `~/.ssh/id_ed25519` — SSH private keys, often with no passphrase
- `~/.aws/credentials` — AWS access keys for the user's accounts
- `~/.kube/config` — Kubernetes credentials, sometimes for production clusters
- `~/.gcloud/`, `~/.netrc`, `~/.docker/config.json` — credentials for other cloud and service auths
- `.env` files in project roots — typically environment-specific secrets

Once an artifact has read one of these into Claude's context, the secret is now in the LLM's context window. From there it can be:
- Echoed back into chat (visible to anyone with access to the conversation)
- Sent to a remote service via any `WebFetch` capability the artifact has
- Used by the LLM in tool calls the user didn't anticipate

## Author-side fix

**If the artifact does not need these credentials:**

Remove the code that reads them. If you're "just checking if the file exists", use `os.path.exists()` rather than reading the contents.

**If the artifact does need these credentials** (rare, but legitimate for e.g. an SSH-key-management skill):

1. Document the need explicitly in the README. Name the exact paths and explain why.
2. Add the path to a documented allowlist in code, rather than reading anything matching a pattern.
3. Annotate the read with a comment citing the README section that documents it.
4. Consider whether you can do the job without reading the secret value (e.g. invoke `ssh` and let it use the key, rather than reading the key contents into Python).

**For `.env` reads specifically:**

If the artifact reads `.env` for its own configuration:

1. Document that the artifact reads `.env` and what variable names it expects.
2. Use `dotenv` library functions that don't echo values to logs or chat.
3. Consider supporting an `os.environ` fallback so the user can avoid the file read entirely.

## adopter-side acceptance

For SSH / AWS / kube path reads: **do not accept** unless the artifact's documented purpose is credential management for that system. Even then, escalate to the the CISO function for advisory engagement — at minimum, the org unit should run the artifact in a sandboxed dev environment that doesn't share secrets with production.

For `.env` reads: an org unit may accept if:
1. The README documents the read.
2. The internal developer confirms the artifact doesn't echo `.env` contents back to chat or send them outbound.
3. The org unit agrees not to use the artifact in contexts where `.env` contains production secrets.

## Cross-references

- Detection logic: `skills/vet-external-skill/SKILL.md` Step 4 (V3)
- Related: [REM-001](REM-001-excessive-webfetch.md) — `WebFetch` granted alongside V3 reads is an exfiltration combo
- Related: REM-011 (planned) — Secrets committed to repo (different V6 pattern, same OWASP entry)
