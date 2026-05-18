// Classifier — config-driven domain → org-unit + topic routing.
//
// Inbox path:  sender + recipients drive routing
// Sent path:   recipients drive routing (sender is always the user)
//
// Returns:
//   {
//     unit:        string | null     — matched org-unit name (config.orgUnitDomainMap)
//     portfolio:   string | null     — matched portfolio
//     domain:      string | null     — matched topic domain (config.domainKeywordMap)
//     sensitivity: "internal" | "confidential" | "restricted"
//     confidence:  "high" | "medium" | "low"
//     reasons:     string[]          — human-readable trail of matched rules
//     extraTags:   string[]          — additional frontmatter tags
//   }

const DEFAULT_SENSITIVITY = "confidential";

export function isSenderBlocklisted(sender, blocklist) {
  if (!sender) return false;
  const s = String(sender).toLowerCase();
  return (blocklist ?? []).some(rx => {
    if (typeof rx !== "string" || rx.startsWith("_comment")) return false;
    try { return new RegExp(rx, "i").test(s); } catch { return false; }
  });
}

/**
 * @param {object} config  Full pipeline config
 * @param {string} haystack  Lowercased text used for keyword matching (subject + body preview + people)
 * @param {string[]} peopleEmails  All sender + recipient addresses for unit-domain matching
 */
export function classify(config, haystack, peopleEmails) {
  const reasons = [];
  const extraTags = [];

  // 1. Org-unit by recipient/sender domain
  let unit = null, portfolio = null;
  const orgMap = config.orgUnitDomainMap ?? {};
  for (const email of peopleEmails) {
    if (!email || !email.includes("@")) continue;
    const domain = email.split("@")[1].toLowerCase();
    if (orgMap[domain] && !orgMap[domain]._comment) {
      unit = orgMap[domain].unit;
      portfolio = orgMap[domain].portfolio ?? null;
      if (orgMap[domain].extraTags) extraTags.push(...orgMap[domain].extraTags);
      reasons.push(`unit-domain:${domain}→${unit}`);
      break;
    }
  }

  // 2. Topic domain by keyword (only if no org-unit matched)
  let domain = null;
  if (!unit) {
    const domainMap = config.domainKeywordMap ?? {};
    for (const [topic, keywords] of Object.entries(domainMap)) {
      if (topic === "_comment") continue;
      if (!Array.isArray(keywords)) continue;
      const hit = keywords.find(kw => haystack.includes(kw.toLowerCase()));
      if (hit) {
        domain = topic;
        reasons.push(`domain-keyword:${hit.trim()}→${topic}`);
        break;
      }
    }
  }

  // 3. Sensitivity — default + restricted-keyword escalation
  const sens = config.sensitivity ?? {};
  let sensitivity = sens.default ?? DEFAULT_SENSITIVITY;
  const restricted = sens.restrictedKeywords ?? [];
  const restrictedHit = restricted.find(kw => haystack.includes(kw.toLowerCase()));
  if (restrictedHit) {
    sensitivity = "restricted";
    reasons.push(`restricted-keyword:${restrictedHit}`);
  }

  // 4. Confidence — high if unit matched, medium if domain matched, low otherwise
  let confidence = "low";
  if (unit) confidence = "high";
  else if (domain) confidence = "medium";

  return { unit, portfolio, domain, sensitivity, confidence, reasons, extraTags };
}
