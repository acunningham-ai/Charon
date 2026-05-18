// Provider loader — resolves a configured provider name to its class + config block.

import { M365Provider } from "./m365.mjs";
import { GmailProvider } from "./gmail.mjs";
import { ImapProvider } from "./imap.mjs";

const REGISTRY = {
  m365: M365Provider,
  gmail: GmailProvider,
  imap: ImapProvider,
};

/**
 * @param {object} config  Full config object (parsed config.json)
 * @param {string} pipelineRoot  Absolute path to the capture-pipeline dir (for state-file resolution)
 * @returns {Provider}
 */
export function loadProvider(config, pipelineRoot) {
  const name = config.provider?.name;
  if (!name) {
    throw new Error("config.provider.name is required (one of: m365 | gmail | imap)");
  }
  const Cls = REGISTRY[name];
  if (!Cls) {
    throw new Error(`Unknown provider "${name}". Known: ${Object.keys(REGISTRY).join(", ")}`);
  }
  const providerConfig = config[name];
  if (!providerConfig) {
    throw new Error(`config.${name} block missing (provider chosen but no settings)`);
  }
  return new Cls(providerConfig, pipelineRoot);
}

export const KNOWN_PROVIDERS = Object.keys(REGISTRY);
