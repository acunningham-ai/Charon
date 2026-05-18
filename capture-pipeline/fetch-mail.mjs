#!/usr/bin/env node
// Charon capture-pipeline entry point.
//
// Usage:
//   node fetch-mail.mjs auth                    Authenticate (one-time per provider)
//   node fetch-mail.mjs inbox                   Fetch inbox only
//   node fetch-mail.mjs sent                    Fetch sent only
//   node fetch-mail.mjs all                     Fetch both (default)
//
// Options:
//   --since YYYY-MM-DD    Override start date (ignores cursor)
//   --full                Reset cursor — re-fetch from capture-window start
//   --limit N             Cap items (for testing)
//   --page-size N         Override provider page size
//   --dry-run             Connect + count, do not write captures

import { readFileSync, existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { loadProvider, KNOWN_PROVIDERS } from "./lib/providers/index.mjs";
import { loadState, saveState, loadCursor, saveCursor, effectiveSince, updateCursor } from "./lib/state.mjs";
import { processItems } from "./lib/capture.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const CONFIG_PATH = join(HERE, "config.json");

if (!existsSync(CONFIG_PATH)) {
  console.error(`Config not found at ${CONFIG_PATH}.`);
  console.error(`Copy config.example.json → config.json and edit, OR run scripts/first-run.py.`);
  process.exit(2);
}
const config = JSON.parse(readFileSync(CONFIG_PATH, "utf8"));

// --- CLI args ---
const args = process.argv.slice(2);
const command = args[0] ?? "all";
function flag(name) { return args.includes(name); }
function flagValue(name) {
  const i = args.indexOf(name);
  return i === -1 ? undefined : args[i + 1];
}

if (!["auth", "inbox", "sent", "all"].includes(command)) {
  console.error(`Usage: node fetch-mail.mjs <auth|inbox|sent|all> [--since YYYY-MM-DD] [--full] [--limit N] [--page-size N] [--dry-run]`);
  console.error(`Known providers: ${KNOWN_PROVIDERS.join(", ")}`);
  process.exit(1);
}

const explicitSince = flagValue("--since");
const fullMode = flag("--full");
const limit = flagValue("--limit") != null ? parseInt(flagValue("--limit"), 10) : undefined;
const pageSize = flagValue("--page-size") != null ? parseInt(flagValue("--page-size"), 10) : undefined;
const dryRun = flag("--dry-run");

function resolveSince(cursor, sourceType) {
  if (explicitSince) return explicitSince;
  if (fullMode) return config.captureWindow?.start ?? "1970-01-01";
  return effectiveSince(cursor, sourceType, config.captureWindow?.start ?? "1970-01-01");
}

const provider = loadProvider(config, HERE);

async function cmdAuth() {
  console.log(`Provider: ${config.provider.name}`);
  const me = await provider.auth();
  console.log(`Auth OK — ${me.displayName ?? me.user} (${me.user})`);
}

async function fetchPath(sourceType, generatorFn) {
  if (!config.capture?.[sourceType] && sourceType !== "inbox") {
    console.log(`Skipping ${sourceType} — disabled in config.capture.${sourceType}`);
    return { captured: 0, skipped: 0, blocklisted: 0, errors: [] };
  }
  if (sourceType === "inbox" && config.capture?.inbox === false) {
    console.log(`Skipping inbox — disabled in config.capture.inbox`);
    return { captured: 0, skipped: 0, blocklisted: 0, errors: [] };
  }

  const cursor = loadCursor(HERE);
  const since = resolveSince(cursor, sourceType);
  console.log(`Fetching ${sourceType} since ${since}...`);

  const state = loadState(config.stateFile, HERE);
  const direction = sourceType === "sent" ? "outbound" : "inbound";
  const totals = { pages: 0, requested: 0, captured: 0, skipped: 0, blocklisted: 0, errors: [] };

  for await (const batch of generatorFn({ since, pageSize, limit })) {
    totals.pages++;
    if (dryRun) {
      totals.requested += batch.length;
      console.log(`  [dry-run] Page ${totals.pages}: ${batch.length} items (not written)`);
      continue;
    }
    const summary = processItems(config, HERE, state, batch, direction);
    totals.requested += summary.requested;
    totals.captured += summary.captured;
    totals.skipped += summary.skipped;
    totals.blocklisted += summary.blocklisted;
    totals.errors.push(...summary.errors);
    console.log(`  Page ${totals.pages}: +${summary.captured} captured, ${summary.skipped} skipped, ${summary.blocklisted} blocklisted${summary.errors.length ? `, ${summary.errors.length} errors` : ""}`);
  }

  if (!dryRun) {
    saveState(config.stateFile, HERE, state);
    updateCursor(cursor, sourceType);
    saveCursor(HERE, cursor);
  }

  console.log(`\n${sourceType} complete.`);
  console.log(`  Pages: ${totals.pages}`);
  console.log(`  Captured: ${totals.captured}`);
  console.log(`  Skipped: ${totals.skipped}`);
  console.log(`  Blocklisted: ${totals.blocklisted}`);
  if (totals.errors.length) {
    console.log(`  Errors: ${totals.errors.length}`);
    for (const e of totals.errors.slice(0, 5)) console.log(`    - ${e.id}: ${e.error}`);
    if (totals.errors.length > 5) console.log(`    ... and ${totals.errors.length - 5} more`);
  }
  return totals;
}

async function main() {
  if (command === "auth") {
    await cmdAuth();
    return;
  }
  if (command === "inbox" || command === "all") {
    await fetchPath("inbox", (opts) => provider.fetchInbox(opts));
    if (command === "all") console.log("\n---\n");
  }
  if (command === "sent" || command === "all") {
    if (config.capture?.sent === false) {
      console.log("Sent-items capture disabled in config.capture.sent — skipping.");
    } else {
      await fetchPath("sent", (opts) => provider.fetchSent(opts));
    }
  }
}

try {
  await main();
} catch (e) {
  console.error(`\nFatal error: ${e.message}`);
  if (/401|token|expired|device_code/i.test(e.message)) {
    console.error(`Try re-authenticating: node fetch-mail.mjs auth`);
  }
  process.exit(1);
}
