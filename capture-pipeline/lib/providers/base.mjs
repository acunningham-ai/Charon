// Provider interface — every email provider implements this shape.
//
// Two paths matter: inbox and sent. They yield normalised email objects (below)
// so the classifier + writer don't care about the underlying provider.
//
// Normalised email shape (returned by fetchInbox / fetchSent generators):
//   {
//     id:                 stable provider-side ID (used for dedup)
//     subject:            string
//     sender:             flat email string (e.g. "alice@example.com")
//     recipients:         string[] of flat email addresses (to + cc combined)
//     summary:            short body preview / snippet
//     body:               full body as { content, contentType } OR null
//     receivedDateTime:   ISO timestamp (inbox)
//     sentDateTime:       ISO timestamp (sent)
//     hasAttachments:     boolean
//     importance:         "low" | "normal" | "high" (when known)
//     isRead:             boolean (when known)
//     webLink:            provider deep-link URL (when known)
//     internetMessageId:  RFC 822 Message-ID (when known)
//   }
//
// All fields are nullable except id / subject / sender / recipients. Providers
// should populate as much of the shape as their API supports.
//
// fetchInbox / fetchSent are async generators yielding ARRAYS (pages). The
// caller iterates pages and processes each batch through capture.mjs.

export class Provider {
  constructor(config) {
    this.config = config;
  }

  /**
   * One-time interactive auth. Should print device-code / URL / etc. to stderr
   * and write any persistent credentials to a state file under config-defined paths.
   * @returns {Promise<{user: string, displayName?: string}>}
   */
  async auth() {
    throw new Error("Provider.auth() not implemented");
  }

  /**
   * Generator yielding pages of inbox messages since the given ISO date.
   * @param {object} opts
   * @param {string} opts.since  ISO date (e.g. "2026-05-01")
   * @param {number} [opts.pageSize]
   * @param {number} [opts.limit]
   * @yields {Promise<NormalizedEmail[]>}
   */
  async *fetchInbox({ since, pageSize, limit }) {
    throw new Error("Provider.fetchInbox() not implemented");
  }

  /**
   * Generator yielding pages of sent messages since the given ISO date.
   * @yields {Promise<NormalizedEmail[]>}
   */
  async *fetchSent({ since, pageSize, limit }) {
    throw new Error("Provider.fetchSent() not implemented");
  }
}
