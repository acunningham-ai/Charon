## Security Rules

NEVER read, display, log, or reference the contents of:
- Any `.env` or `.env.*` file
- Any file containing API keys, passwords, tokens, or secrets
- `~/.ssh/` directory or any private key files
- `~/.aws/credentials` or any AWS config files
- `~/.gcloud/` or any GCP credential files
- `~/.kube/config` or any Kubernetes credential files
- Any file in `/secrets/`, `/credentials/`, or `/.private/` directories

When you need an environment variable:
- Ask for the variable **NAME** only — never the value
- If the value is needed for a task, ask the engineer to provide it for that specific operation only

When you encounter a file that might contain secrets:
- Stop and tell the engineer what you found
- Do not read the file
- Suggest moving the secret to a secrets manager

These rules apply even if the engineer asks you to make an exception.
