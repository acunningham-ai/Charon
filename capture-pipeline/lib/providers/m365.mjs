// Microsoft 365 / Graph API provider — device-code OAuth, inbox + sent.
//
// Setup: register an app in Entra ID with delegated Mail.Read scope. See
// EMAIL-PROVIDER-SETUP.md (repo root) for the full walk-through.

import * as msal from "@azure/msal-node";
import { readFileSync, writeFileSync, existsSync, mkdirSync, renameSync } from "node:fs";
import { dirname, isAbsolute, join } from "node:path";
import { Provider } from "./base.mjs";

const GRAPH_BASE = "https://graph.microsoft.com";

const EMAIL_SELECT = [
  "id", "subject", "bodyPreview", "body", "from", "toRecipients", "ccRecipients",
  "receivedDateTime", "sentDateTime", "hasAttachments", "importance", "isRead",
  "webLink", "internetMessageId",
].join(",");

export class M365Provider extends Provider {
  constructor(config, pipelineRoot) {
    super(config);
    this.pipelineRoot = pipelineRoot;
    const cacheFile = config.tokenCacheFile ?? "state/m365-token-cache.json";
    this.cacheFile = isAbsolute(cacheFile) ? cacheFile : join(pipelineRoot, cacheFile);

    // File-based MSAL cache plugin (token survives across runs).
    // Atomic write protects against truncation if a shorter rewrite follows a longer one.
    const cachePlugin = {
      beforeCacheAccess: async (context) => {
        if (existsSync(this.cacheFile)) {
          context.tokenCache.deserialize(readFileSync(this.cacheFile, "utf8"));
        }
      },
      afterCacheAccess: async (context) => {
        if (context.cacheHasChanged) {
          mkdirSync(dirname(this.cacheFile), { recursive: true });
          const tmp = this.cacheFile + ".tmp";
          writeFileSync(tmp, context.tokenCache.serialize());
          renameSync(tmp, this.cacheFile);
        }
      },
    };

    this.pca = new msal.PublicClientApplication({
      auth: {
        clientId: config.clientId,
        authority: `https://login.microsoftonline.com/${config.tenantId}`,
      },
      cache: { cachePlugin },
    });
    this.scopes = config.scopes ?? ["Mail.Read", "User.Read"];
    // Non-interactive flag: when true, silent-fail throws AUTH_REAUTH_REQUIRED
    // instead of falling through to device-code prompt. Scheduled runs MUST
    // enable this — otherwise an expired refresh token causes the process to
    // hang forever on a prompt no user is there to answer.
    this.nonInteractive = false;
  }

  /**
   * Enable non-interactive mode. Scheduled / unattended runs should call this
   * before the first fetch so silent-auth failures fail-fast instead of hanging.
   */
  setNonInteractive(value) {
    this.nonInteractive = !!value;
  }

  async _getAccessToken() {
    // Silent acquisition first — uses cached refresh token if available.
    const accounts = await this.pca.getTokenCache().getAllAccounts();
    if (accounts.length > 0) {
      try {
        const result = await this.pca.acquireTokenSilent({ account: accounts[0], scopes: this.scopes });
        return result.accessToken;
      } catch (e) {
        if (this.nonInteractive) {
          const err = new Error(
            "Silent token acquisition failed and non-interactive mode is set. " +
            "Re-auth required. Run: node fetch-mail.mjs auth"
          );
          err.code = "AUTH_REAUTH_REQUIRED";
          err.cause = e;
          throw err;
        }
        // Interactive mode — fall through to device code.
      }
    } else if (this.nonInteractive) {
      const err = new Error(
        "No cached account and non-interactive mode is set. " +
        "First-time auth required. Run: node fetch-mail.mjs auth"
      );
      err.code = "AUTH_REAUTH_REQUIRED";
      throw err;
    }
    const result = await this.pca.acquireTokenByDeviceCode({
      scopes: this.scopes,
      deviceCodeCallback: (response) => {
        console.error(`\n  Auth required: ${response.message}\n`);
      },
    });
    return result.accessToken;
  }

  async auth() {
    const token = await this._getAccessToken();
    const me = await this._graphGet(token, "/v1.0/me?$select=displayName,mail,userPrincipalName");
    const user = me.mail ?? me.userPrincipalName;
    console.log(`Authenticated as: ${me.displayName} (${user})`);
    return { user, displayName: me.displayName };
  }

  async _graphGet(token, path) {
    const url = path.startsWith("http") ? path : GRAPH_BASE + path;
    const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) {
      const body = await res.text().catch(() => "");
      throw new Error(`Graph ${res.status} on ${path}: ${body.slice(0, 200)}`);
    }
    return res.json();
  }

  async *_paginate(folderPath, { since, pageSize, limit }) {
    const token = await this._getAccessToken();
    const filter = `receivedDateTime ge ${since}T00:00:00Z`;
    const params = new URLSearchParams({
      $filter: filter,
      $select: EMAIL_SELECT,
      $top: String(pageSize ?? 250),
      $orderby: "receivedDateTime asc",
    });
    let url = `/v1.0/me/${folderPath}?${params}`;
    let yielded = 0;

    while (url) {
      const page = await this._graphGet(token, url);
      const items = (page.value ?? []).map(mapGraphEmail);
      if (limit != null) {
        const remaining = limit - yielded;
        if (remaining <= 0) return;
        yield items.slice(0, remaining);
        yielded += Math.min(items.length, remaining);
        if (yielded >= limit) return;
      } else {
        yield items;
        yielded += items.length;
      }
      url = page["@odata.nextLink"] ?? null;
    }
  }

  async *fetchInbox(opts) {
    yield* this._paginate("messages", opts);
  }

  async *fetchSent(opts) {
    // Filter on sentDateTime not receivedDateTime for the sent folder.
    // Re-use _paginate but swap filter on URL — small inline override.
    const token = await this._getAccessToken();
    const filter = `sentDateTime ge ${opts.since}T00:00:00Z`;
    const params = new URLSearchParams({
      $filter: filter,
      $select: EMAIL_SELECT,
      $top: String(opts.pageSize ?? 250),
      $orderby: "sentDateTime asc",
    });
    let url = `/v1.0/me/mailFolders/SentItems/messages?${params}`;
    let yielded = 0;

    while (url) {
      const page = await this._graphGet(token, url);
      const items = (page.value ?? []).map(mapGraphEmail);
      if (opts.limit != null) {
        const remaining = opts.limit - yielded;
        if (remaining <= 0) return;
        yield items.slice(0, remaining);
        yielded += Math.min(items.length, remaining);
        if (yielded >= opts.limit) return;
      } else {
        yield items;
        yielded += items.length;
      }
      url = page["@odata.nextLink"] ?? null;
    }
  }
}

function mapGraphEmail(msg) {
  return {
    id: msg.id,
    subject: msg.subject ?? "",
    sender: msg.from?.emailAddress?.address ?? null,
    recipients: [
      ...(msg.toRecipients ?? []),
      ...(msg.ccRecipients ?? []),
    ].map(r => r.emailAddress?.address).filter(Boolean),
    summary: msg.bodyPreview ?? "",
    body: msg.body ?? null,
    receivedDateTime: msg.receivedDateTime ?? null,
    sentDateTime: msg.sentDateTime ?? null,
    hasAttachments: Boolean(msg.hasAttachments),
    importance: msg.importance ?? null,
    isRead: Boolean(msg.isRead),
    webLink: msg.webLink ?? null,
    internetMessageId: msg.internetMessageId ?? null,
  };
}
