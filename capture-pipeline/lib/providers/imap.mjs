// Generic IMAP provider — SKELETON. App-password auth + TLS. Works with any
// IMAP-compliant mailbox (Gmail with app password, Outlook, Yahoo, FastMail,
// self-hosted, etc.).
//
// Setup outline (full walk-through in EMAIL-PROVIDER-SETUP.md):
//   1. Enable IMAP in your provider's web settings
//   2. Generate an app-specific password (NOT your main password)
//   3. Store the app password in a file under $HARNESS_SECRETS_DIR with 600 perms
//   4. Set host / port / user / passwordSecretFile / inboxFolder / sentFolder in config
//   5. Run `node fetch-mail.mjs auth` — connects + logs the folder list to confirm setup
//
// Implementation pointers:
//   - Use `imapflow` (already in package.json) — modern async API
//   - For inbox: open `inboxFolder` (default "INBOX"), search since-date, fetch envelope + body
//   - For sent:  open `sentFolder` (varies — "Sent" / "Sent Items" / "[Gmail]/Sent Mail")
//   - Use the `INTERNALDATE` for inbox, `Date:` header for sent
//   - Idempotency uses Message-ID — IMAP UIDs are not stable across folder moves

import { Provider } from "./base.mjs";

const NOT_IMPLEMENTED = `IMAP provider is not yet implemented. See EMAIL-PROVIDER-SETUP.md for the setup walk-through, then fill in lib/providers/imap.mjs. PRs welcome.`;

export class ImapProvider extends Provider {
  constructor(config, pipelineRoot) {
    super(config);
    this.pipelineRoot = pipelineRoot;
    if (!config.host || !config.user || !config.passwordSecretFile) {
      throw new Error("IMAP config missing host / user / passwordSecretFile. See EMAIL-PROVIDER-SETUP.md.");
    }
  }

  async auth() {
    throw new Error(NOT_IMPLEMENTED);
  }

  async *fetchInbox(opts) {
    throw new Error(NOT_IMPLEMENTED);
    yield [];
  }

  async *fetchSent(opts) {
    throw new Error(NOT_IMPLEMENTED);
    yield [];
  }
}
