// Capture processor — takes a batch of normalised emails, classifies them,
// writes to vault as markdown. Idempotent (skips already-captured IDs).

import { writeFileSync, mkdirSync, existsSync } from "node:fs";
import { join, isAbsolute } from "node:path";
import { isCaptured, recordCapture, audit } from "./state.mjs";
import { classify, isSenderBlocklisted } from "./classify.mjs";
import { formatEmail } from "./format.mjs";

/**
 * Process a batch of emails through classify → format → write.
 * @param {object} config         Full pipeline config (parsed config.json)
 * @param {string} pipelineRoot   Absolute path to the capture-pipeline dir
 * @param {object} state          Loaded state object (mutated as items are captured)
 * @param {object[]} items        Normalised emails (see providers/base.mjs)
 * @param {"inbound"|"outbound"} direction
 * @returns {{requested, captured, skipped, blocklisted, errors}}
 */
export function processItems(config, pipelineRoot, state, items, direction) {
  const summary = { requested: items.length, captured: 0, skipped: 0, blocklisted: 0, errors: [] };
  const auditPath = config.auditLog;

  for (const item of items) {
    try {
      if (!item.id) { summary.errors.push({ id: "(no id)", error: "item missing id" }); continue; }
      if (isCaptured(state, item.id)) { summary.skipped++; continue; }

      // Blocklist check — sender for inbound, recipients for outbound (skip auto-replies, calendar bots, etc.)
      const blocklistTarget = direction === "inbound" ? item.sender : (item.recipients?.[0] ?? "");
      if (isSenderBlocklisted(blocklistTarget, config.senderBlocklist)) {
        summary.blocklisted++;
        audit(auditPath, pipelineRoot, `BLOCKLIST ${direction} ${item.id} target="${blocklistTarget}"`);
        continue;
      }

      const peopleEmails = [item.sender, ...(item.recipients ?? [])].filter(Boolean);
      const haystack = [
        item.subject ?? "",
        item.summary ?? "",
        item.sender ?? "",
        (item.recipients ?? []).join(" "),
      ].join(" ").toLowerCase();

      const cls = classify(config, haystack, peopleEmails);
      const ts = direction === "outbound"
        ? (item.sentDateTime ?? item.receivedDateTime ?? "")
        : (item.receivedDateTime ?? item.sentDateTime ?? "");
      const ym = ts.slice(0, 7) || "0000-00";

      // Routing: unit > domain > uncertain. Same shape for both directions —
      // direction frontmatter distinguishes downstream.
      const paths = config.vaultPaths ?? {};
      const root = paths.emailRoot ?? "00-Inbox/_captured/email";
      let vaultSubdir, bucket;
      if (cls.unit) {
        vaultSubdir = join(root, cls.portfolio ?? "_no-portfolio", cls.unit, ym);
        bucket = `unit:${cls.portfolio ?? "_no-portfolio"}/${cls.unit}`;
      } else if (cls.domain) {
        vaultSubdir = join(paths.emailDomain ?? join(root, "_domain"), cls.domain, ym);
        bucket = `domain:${cls.domain}`;
      } else {
        vaultSubdir = join(paths.emailUncertain ?? join(root, "_uncertain"), ym);
        bucket = "uncertain";
      }

      const result = formatEmail(item, cls, direction);
      const vaultRootAbs = isAbsolute(config.vaultRoot) ? config.vaultRoot : join(pipelineRoot, config.vaultRoot);
      const targetDir = join(vaultRootAbs, vaultSubdir);
      mkdirSync(targetDir, { recursive: true });
      const targetPath = join(targetDir, result.filename);

      // Don't overwrite existing files — name-collision safety
      if (existsSync(targetPath)) {
        summary.skipped++;
        audit(auditPath, pipelineRoot, `COLLISION ${direction} ${item.id} → ${targetPath}`);
        continue;
      }

      writeFileSync(targetPath, result.markdown);
      recordCapture(state, item.id, {
        direction,
        vaultPath: targetPath.replace(vaultRootAbs, "").replace(/^[\\/]+/, "").replace(/\\/g, "/"),
        unit: cls.unit, portfolio: cls.portfolio, domain: cls.domain,
        sensitivity: cls.sensitivity, confidence: cls.confidence, bucket,
      });
      audit(auditPath, pipelineRoot, `CAPTURE ${direction} ${item.id} → ${targetPath} bucket=${bucket} sens=${cls.sensitivity}`);
      summary.captured++;
    } catch (e) {
      summary.errors.push({ id: item.id ?? "(no id)", error: String(e.message ?? e) });
      audit(auditPath, pipelineRoot, `ERROR ${direction} ${item.id} ${e.message ?? e}`);
    }
  }

  return summary;
}
