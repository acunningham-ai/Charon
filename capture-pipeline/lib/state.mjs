// State store — captured-item index (idempotency) + per-source cursor.
//
// captured.json shape:
//   { schemaVersion, items: { <id>: { sourceType, direction, vaultPath, ...meta, capturedAt } } }
//
// cursor.json shape:
//   { schemaVersion, cursors: { inbox: ISO, sent: ISO } }

import { readFileSync, writeFileSync, appendFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname, isAbsolute, join } from "node:path";

function resolve(p, root) {
  return isAbsolute(p) ? p : join(root, p);
}

export function loadState(stateFile, root) {
  const path = resolve(stateFile, root);
  if (!existsSync(path)) return { schemaVersion: 1, items: {} };
  return JSON.parse(readFileSync(path, "utf8"));
}

export function saveState(stateFile, root, state) {
  const path = resolve(stateFile, root);
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, JSON.stringify(state, null, 2));
}

export function isCaptured(state, id) {
  return Boolean(state.items[id]);
}

export function recordCapture(state, id, record) {
  state.items[id] = { ...record, capturedAt: new Date().toISOString() };
}

export function audit(auditLog, root, line) {
  const path = resolve(auditLog, root);
  mkdirSync(dirname(path), { recursive: true });
  appendFileSync(path, `${new Date().toISOString()} ${line}\n`);
}

// --- Cursor ---

const CURSOR_FILE = "state/cursor.json";

export function loadCursor(root) {
  const path = join(root, CURSOR_FILE);
  if (!existsSync(path)) return { schemaVersion: 1, cursors: {} };
  return JSON.parse(readFileSync(path, "utf8"));
}

export function saveCursor(root, cursor) {
  const path = join(root, CURSOR_FILE);
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, JSON.stringify(cursor, null, 2));
}

/**
 * Resolve the "since" date for a source type. Priority:
 *   explicit override > cursor value > capture-window start.
 */
export function effectiveSince(cursor, sourceType, captureWindowStart, override) {
  if (override) return override;
  const cursored = cursor.cursors?.[sourceType];
  return cursored ?? captureWindowStart;
}

export function updateCursor(cursor, sourceType) {
  cursor.cursors = cursor.cursors ?? {};
  cursor.cursors[sourceType] = new Date().toISOString().slice(0, 10);
}
