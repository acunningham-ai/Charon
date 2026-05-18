// Gmail provider — SKELETON. Interface is complete; the OAuth + fetch
// methods throw with a clear "not implemented" message pointing at the
// setup doc. The shape is here so a contributor can fill it in without
// inventing the integration pattern.
//
// Setup outline (full walk-through in EMAIL-PROVIDER-SETUP.md):
//   1. Create an OAuth client in Google Cloud Console (Desktop type)
//   2. Enable Gmail API on the project
//   3. Add yourself as a test user while in test mode
//   4. Run `node fetch-mail.mjs auth` — opens browser for consent
//   5. Refresh token saved to config.gmail.refreshTokenFile
//
// Implementation pointers:
//   - Use `googleapis` (already in package.json)
//   - For inbox: messages.list with `q=in:inbox after:YYYY/MM/DD`
//   - For sent:  messages.list with `q=in:sent  after:YYYY/MM/DD`
//   - messages.list returns IDs only; call messages.get(id, format=metadata|full) per ID
//   - Paginate via `pageToken` until null
//   - Gmail dates are epoch ms in headers — convert to ISO for normalised shape

import { Provider } from "./base.mjs";

const NOT_IMPLEMENTED = `Gmail provider is not yet implemented. See EMAIL-PROVIDER-SETUP.md for the setup walk-through, then fill in lib/providers/gmail.mjs. PRs welcome.`;

export class GmailProvider extends Provider {
  constructor(config, pipelineRoot) {
    super(config);
    this.pipelineRoot = pipelineRoot;
    // Validate config shape up-front so the failure surfaces at auth time,
    // not buried inside a generator.
    if (!config.clientId || !config.clientSecret) {
      throw new Error("Gmail config missing clientId / clientSecret. See EMAIL-PROVIDER-SETUP.md.");
    }
  }

  async auth() {
    throw new Error(NOT_IMPLEMENTED);
  }

  async *fetchInbox(opts) {
    throw new Error(NOT_IMPLEMENTED);
    // Unreachable — keeps `yield` shape so type-checkers stay happy.
    yield [];
  }

  async *fetchSent(opts) {
    throw new Error(NOT_IMPLEMENTED);
    yield [];
  }
}
