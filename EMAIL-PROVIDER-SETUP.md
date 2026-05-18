# Email provider setup

Step-by-step setup for each capture-pipeline provider. Read the relevant section before running the first-run wizard with `capture_pipeline_setup: y` — provider-side preparation (app registrations, OAuth clients, app passwords) cannot be done by the wizard.

| Provider | Status | Best for |
|---|---|---|
| **Microsoft 365 / Graph** | ✅ Fully implemented | Enterprise (Entra ID), Exchange Online, personal MS accounts |
| **Gmail (Gmail API)** | 🚧 Skeleton — implement before use | Google Workspace, personal Gmail |
| **Generic IMAP** | 🚧 Skeleton — implement before use | Anything else (Outlook IMAP, Yahoo, FastMail, self-hosted, etc.) |

Why only M365 is implemented: the harness ships the *pattern* fully working for one provider so users can verify the end-to-end flow, then fill in their own provider following the same shape. PRs adding Gmail / IMAP implementations are welcome.

---

## Microsoft 365 (Graph API)

### Prerequisites

- A Microsoft 365 account (work, school, or personal)
- Permission to register an app in Entra ID (your own tenant, or a personal-account "common" registration)
- Browser access for the device-code OAuth handshake

### Setup

#### 1. Register an app in Entra ID

For **work / school accounts**:

1. Open [Entra admin centre](https://entra.microsoft.com/) → **Identity** → **Applications** → **App registrations** → **New registration**.
2. Name it `charon-capture-pipeline` (or whatever helps you find it later).
3. **Supported account types**: pick the narrowest fit.
   - "Single tenant" if only you / your org use this clone
   - "Multitenant" if Charon clones across multiple tenants
4. **Redirect URI**: leave blank — device-code flow doesn't need one.
5. Click **Register**.
6. Copy the **Application (client) ID** — this is `m365.clientId`.
7. Copy the **Directory (tenant) ID** — this is `m365.tenantId`.

For **personal Microsoft accounts** (`@outlook.com`, `@hotmail.com`, `@live.com`):

- Use the same app registration but set "Supported account types" to **"Personal Microsoft accounts only"**.
- Set `m365.tenantId` to `"common"` in config.json instead of the directory UUID.

#### 2. Add API permissions

1. In your app registration → **API permissions** → **Add a permission** → **Microsoft Graph** → **Delegated permissions**.
2. Add: `Mail.Read`, `User.Read`.
3. If your tenant requires admin consent (most enterprise tenants do), click **Grant admin consent for &lt;your tenant&gt;**.

#### 3. Enable public client flows

Device-code flow is a "public client" flow.

1. In your app registration → **Authentication**.
2. Scroll to **Advanced settings** → **Allow public client flows** → set to **Yes** → **Save**.

#### 4. First auth

```bash
cd capture-pipeline
node fetch-mail.mjs auth
```

You'll see:

```
  Auth required: To sign in, use a web browser to open the page https://login.microsoftonline.com/common/oauth2/deviceauth and enter the code XXXXXXX to authenticate.
```

Open the URL, enter the code, sign in. The pipeline caches a refresh token at `state/m365-token-cache.json` — future runs are silent until that token expires (typically 90 days of inactivity).

#### 5. First capture

```bash
node fetch-mail.mjs all       # inbox + sent (default — sent capture is on)
node fetch-mail.mjs inbox     # inbox only
node fetch-mail.mjs sent      # sent only
node fetch-mail.mjs all --dry-run    # count what would be captured, write nothing
```

### Token-expiry recovery

If the pipeline silently fails for 2+ days with `device_code_expired` or `401`, the refresh token has lapsed. Re-auth:

```bash
node fetch-mail.mjs auth      # will fall through to device-code flow again
```

If you set up `feedback_pipeline_failure_surface.md` in your harness memory, the session-start ritual flags this for you. Otherwise add a calendar reminder to run `node fetch-mail.mjs auth` monthly as insurance.

### Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `AADSTS65001: The user or administrator has not consented` | Admin consent not granted on the Mail.Read scope. Step 2 above. |
| `AADSTS7000218: The request body must contain the following parameter: 'client_assertion'` | Public client flow not enabled. Step 3 above. |
| `AADSTS50059: No tenant-identifying information found` | Using `tenantId: "common"` with a work account, or a tenant UUID with a personal account. Switch the tenantId. |
| Device-code page shows "this account doesn't exist in tenant X" | Mixed personal + work identity. Sign out of all MS accounts in the browser, retry. |
| `Graph 403 on /me/messages` | Mail.Read scope missing or admin consent not granted. |
| Pipeline hangs on auth indefinitely | Token-cache file corruption. Delete `state/m365-token-cache.json` and re-auth. |

---

## Gmail (Gmail API)

🚧 **Provider is currently a skeleton.** The interface is defined in `capture-pipeline/lib/providers/gmail.mjs` — implementation is left to the user / contributors. The setup steps below are the prerequisite work; once those are done, fill in the three methods (`auth`, `fetchInbox`, `fetchSent`) in `gmail.mjs` to enable Gmail.

### Prerequisites

- A Google account
- Access to [Google Cloud Console](https://console.cloud.google.com/) to create a project + OAuth client
- Browser access for OAuth consent

### Setup

#### 1. Create a Google Cloud project

1. Open [Cloud Console](https://console.cloud.google.com/) → **Select project** → **New project**.
2. Name it `charon-capture-pipeline`. Note the project ID.

#### 2. Enable the Gmail API

1. **APIs & Services** → **Library** → search "Gmail API" → **Enable**.

#### 3. Configure OAuth consent screen

1. **APIs & Services** → **OAuth consent screen**.
2. User type: **External** (works for personal Gmail) or **Internal** (Google Workspace only).
3. Fill required fields (app name, support email, developer contact). The other fields can stay blank.
4. **Scopes**: add `https://www.googleapis.com/auth/gmail.readonly`.
5. **Test users**: while in test mode, add your own email. Apps in test mode work for up to 100 test users without verification.

#### 4. Create OAuth client

1. **APIs & Services** → **Credentials** → **Create credentials** → **OAuth client ID**.
2. Application type: **Desktop app**.
3. Name: `charon-capture-pipeline`.
4. Download the JSON. Copy:
   - `client_id` → `gmail.clientId` in `config.json`
   - `client_secret` → write to `<your secrets dir>/gmail-client-secret.txt` (DON'T commit to config.json)

#### 5. Implement `lib/providers/gmail.mjs`

The skeleton at `capture-pipeline/lib/providers/gmail.mjs` documents what's needed. The `googleapis` npm package is already in `package.json`. Key calls:

- `gmail.users.messages.list({ userId: 'me', q: 'in:inbox after:YYYY/MM/DD', pageToken })`
- `gmail.users.messages.list({ userId: 'me', q: 'in:sent after:YYYY/MM/DD',  pageToken })`
- `gmail.users.messages.get({ userId: 'me', id, format: 'full' })` per message ID

Map the Gmail response shape to the normalised email shape in `providers/base.mjs`. The classifier + writer don't care which provider supplied the data.

#### 6. First auth + capture

```bash
cd capture-pipeline
node fetch-mail.mjs auth      # OAuth flow opens browser; refresh token saved
node fetch-mail.mjs all       # inbox + sent
```

### Gotchas

- **Apps in test mode**: refresh tokens expire after 7 days. For production use, submit the app for verification (free, Google reviews scope appropriateness).
- **Sent folder naming**: Gmail's "Sent" lives under `[Gmail]/Sent Mail` in IMAP, but the Gmail API uses `in:sent` as a label query — no folder hierarchy.
- **Threading**: Gmail conversation IDs (`threadId`) are stable across messages — useful for grouping replies in downstream skills. Capture them in the `internetMessageId` field or add a new normalised field if you need thread-level dedup.

---

## Generic IMAP

🚧 **Provider is currently a skeleton.** Implementation pointers in `capture-pipeline/lib/providers/imap.mjs`. Works with any IMAP-compliant mailbox.

### Prerequisites

- An email account with IMAP enabled
- An app-specific password (NEVER your main account password)
- IMAP server details (host + port + TLS)

### Setup

#### 1. Enable IMAP + generate an app password

Provider-specific. Common providers:

**Gmail (with app password — works without OAuth):**

1. Enable 2-Step Verification on your Google account (required for app passwords).
2. [Generate an app password](https://myaccount.google.com/apppasswords) → name it `charon` → copy the 16-character password.
3. IMAP host: `imap.gmail.com`, port `993`, TLS on.

**Outlook / Microsoft 365 (with app password):**

1. Open [account.live.com/proofs/AppPassword](https://account.live.com/proofs/AppPassword) (personal) or the security defaults in your Microsoft 365 admin (work).
2. Generate an app password → copy.
3. IMAP host: `outlook.office365.com`, port `993`, TLS on.

**Yahoo Mail:**

1. [Generate an app password](https://login.yahoo.com/account/security/app-passwords) → name it `charon` → copy.
2. IMAP host: `imap.mail.yahoo.com`, port `993`, TLS on.

**FastMail / iCloud / self-hosted**: consult your provider's IMAP documentation. Same pattern.

#### 2. Store the app password securely

```bash
# Unix
mkdir -p ~/.secrets
echo 'your-16-char-app-password' > ~/.secrets/imap-app-password.txt
chmod 600 ~/.secrets/imap-app-password.txt

# Windows PowerShell
$env:HARNESS_SECRETS_DIR = "$HOME\.secrets"
mkdir $env:HARNESS_SECRETS_DIR -Force | Out-Null
"your-16-char-app-password" | Out-File -Encoding ascii "$env:HARNESS_SECRETS_DIR\imap-app-password.txt"
icacls "$env:HARNESS_SECRETS_DIR\imap-app-password.txt" /inheritance:r /grant:r "$env:USERNAME:R"
```

The path becomes `imap.passwordSecretFile` in `config.json`.

#### 3. Find your "Sent" folder name

IMAP folder names vary widely. Common values:

| Provider | Sent folder |
|---|---|
| Most providers | `Sent` |
| Microsoft Outlook (IMAP) | `Sent Items` |
| Gmail (IMAP) | `[Gmail]/Sent Mail` |
| Apple Mail / iCloud | `Sent Messages` |
| Some self-hosted | `INBOX.Sent` |

Once you've implemented the IMAP provider, the first `node fetch-mail.mjs auth` run logs the folder list to help you pick.

#### 4. Implement `lib/providers/imap.mjs`

The skeleton documents what's needed. `imapflow` is already in `package.json`. Key calls:

- `client.mailboxOpen(config.inboxFolder)` then `client.search({ since: dateObj }, { uid: true })`
- `client.mailboxOpen(config.sentFolder)` — same
- `client.fetch(uids, { source: true, envelope: true, internalDate: true })`

Idempotency: use the email's `Message-ID` header for dedup. IMAP UIDs are not stable across folder moves.

#### 5. First auth + capture

```bash
cd capture-pipeline
node fetch-mail.mjs auth      # connects, lists folders, confirms credentials
node fetch-mail.mjs all
```

### Gotchas

- **Plain passwords**: never. Use app passwords (or OAuth where the provider supports IMAP OAuth2).
- **Folder UIDs vs Message-IDs**: dedup on Message-ID (RFC 822 header), not IMAP UID — UIDs aren't stable.
- **TLS required**: refuse to connect to `port: 143` (cleartext) on any provider. The example config defaults to `port: 993, secure: true`.
- **Date filtering granularity**: IMAP's SEARCH only supports day-level granularity. Cursor stores `YYYY-MM-DD`, not a timestamp — re-fetches the cursor day on each run (dedup makes this safe).

---

## Scheduling

Once `node fetch-mail.mjs all` works manually, register it with your platform's scheduler. The first-run wizard records your preferred frequency + time; this section walks you through wiring it in.

### Windows — Task Scheduler

The pipeline ships with `capture-pipeline/scheduled-capture.bat` as the wrapper.

```powershell
# Open Task Scheduler — Create Basic Task
#   Name: Charon Capture
#   Trigger: Daily at <your chosen time, default 07:00>
#   Action: Start a program
#     Program: C:\path\to\Charon\capture-pipeline\scheduled-capture.bat
#     Start in: C:\path\to\Charon\capture-pipeline
#
# Recommended settings:
#   - "Run only when user is logged on" (NOT "run whether user is logged on or not")
#   - "Do not start a new instance" (parallel-run safety)
#   - UNCHECK "Wake the computer to run this task"
#   - UNCHECK "Run with highest privileges"
```

Or via PowerShell:

```powershell
$action = New-ScheduledTaskAction -Execute "C:\path\to\Charon\capture-pipeline\scheduled-capture.bat"
$trigger = New-ScheduledTaskTrigger -Daily -At 7am
$settings = New-ScheduledTaskSettingsSet -DontStopIfGoingOnBatteries:$false -AllowStartIfOnBatteries:$false -StartWhenAvailable
Register-ScheduledTask -TaskName "Charon Capture" -Action $action -Trigger $trigger -Settings $settings
```

### macOS — launchd

Create `~/Library/LaunchAgents/com.charon.capture.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.charon.capture</string>
  <key>ProgramArguments</key>
  <array>
    <string>/path/to/Charon/capture-pipeline/scheduled-capture.sh</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    <key>Hour</key><integer>7</integer>
    <key>Minute</key><integer>0</integer>
  </dict>
  <key>RunAtLoad</key>
  <false/>
  <key>StandardOutPath</key>
  <string>/path/to/Charon/capture-pipeline/state/scheduled-run.log</string>
  <key>StandardErrorPath</key>
  <string>/path/to/Charon/capture-pipeline/state/scheduled-run.log</string>
</dict>
</plist>
```

Load it:

```bash
launchctl load ~/Library/LaunchAgents/com.charon.capture.plist
launchctl list | grep charon          # confirm registered
```

### Linux — cron

Edit `crontab -e` and add (substitute your actual path):

```cron
# Charon capture — daily 07:00
0 7 * * * /path/to/Charon/capture-pipeline/scheduled-capture.sh

# Or hourly (for users with high inbox volume + tight feedback loops):
0 * * * * /path/to/Charon/capture-pipeline/scheduled-capture.sh
```

Verify: `crontab -l | grep charon-pipeline`. Logs land in `capture-pipeline/state/scheduled-run.log`.

### Run cadence

| Cadence | When it fits |
|---|---|
| **Daily morning (default)** | Pairs with `/refresh-todo` — your day starts with fresh captures. |
| **Hourly** | High-volume mailboxes with tight-feedback workflows. Watch token quotas on rate-limited providers. |
| **Manual** | Privacy-sensitive setups, or when you want explicit control over each pull. |

### Failure-mode awareness

OAuth tokens expire. If the pipeline silently fails for ≥2 consecutive days, captures drift and downstream skills (`/refresh-todo`, `/triage-inbox`) operate on stale data. Heuristics:

- Tail `capture-pipeline/state/scheduled-run.log` at session start. Look for `Fatal error` / `device_code_expired` / consecutive `Run finished: ... (exit=1)` lines.
- `python scripts/check-capture-state.py` — ships in Charon, diagnoses cursor + state-file health.
- If you have memory in your harness, add a `feedback_pipeline_failure_surface.md` rule (mirror of the Charon author's): *"If the capture pipeline log shows ≥2 consecutive failed runs, surface that at session-start before any other work."*

## Adding a new provider

The capture-pipeline is designed for extensibility. To add (e.g.) Slack, Notion, or a custom REST endpoint:

1. **Copy the interface**: `capture-pipeline/lib/providers/base.mjs` → new file in same dir.
2. **Implement** `auth()`, `fetchInbox({ since })`, `fetchSent({ since })`. Return normalised email objects (shape in `base.mjs`).
3. **Register** in `lib/providers/index.mjs`:
   ```js
   import { SlackProvider } from "./slack.mjs";
   const REGISTRY = { m365, gmail, imap, slack: SlackProvider };
   ```
4. **Config block**: add a top-level key in `config.example.json` and `config.json` template at end of `scripts/first-run-questions.yaml`.
5. **Wizard branch**: add provider choice + per-provider questions in `scripts/first-run-questions.yaml`.
6. **Docs**: add a section to this file.

Keep providers narrow. The classifier + writer don't need to change — they consume the normalised shape.

---

## See also

- `capture-pipeline/README.md` — pipeline overview and run instructions
- `capture-pipeline/config.example.json` — config template
- `FIRST-RUN.md` — wizard walk-through (post-provider-setup)
- `INSTALL.md` — Charon install + bootstrap
- `SECURITY.md` — C-1..C-8 baseline; C-5 (write-path allowlist) and C-7 (captured-content untrusted) apply directly
