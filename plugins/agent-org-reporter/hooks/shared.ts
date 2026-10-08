import type { PaneLive } from '../types'
import type { OrgData } from './policy'

// The hand-off between the modules of this plugin. Plain data only: the engine
// interface `$` may not cross a module import, so each module does its own `$`
// calls and they meet here. A hot reload clears it, like the rest of the module
// state; pane.tsx reloads the org data within seconds.

// reporter (register.ts) -> pane: the live roll-up
export const paneFeed: { view: PaneLive | null; version: number } = { view: null, version: 0 }

export function setPaneView(view: PaneLive) {
  paneFeed.view = view
  paneFeed.version += 1
}

// pane (loads roster + approvals) -> reporter (enforces spawn rules)
export const org: { data: OrgData | null } = { data: null }

// A1 (security review): specialist types already started in THIS process. The
// spawn hook checks and adds in one synchronous step, so two parallel starts of a
// single-use specialist cannot both pass, with or without a pane to sync approvals.
export const usedSpecs = new Set<string>()

// reporter -> pane: specialist lifecycle events the pane writes to approvals.json
// (the pane is the ONLY writer of that file).
export const lifecycle: { started: { agentType: string; at: string }[]; finished: { agentType: string; at: string }[] } = {
  started: [],
  finished: [],
}

// reporter -> pane: raw activity for the graphs. Timestamps (ms) of tool calls and
// [ms, output tokens] of turn completions; the pane buckets them. Bounded.
const SERIES_MAX = 20_000
export const series: { calls: number[]; tokens: [number, number][]; lastEventMs: number; version: number } = {
  calls: [],
  tokens: [],
  lastEventMs: 0,
  version: 0,
}

export function seriesCall(ms: number) {
  series.calls.push(ms)
  if (series.calls.length > SERIES_MAX) series.calls.splice(0, series.calls.length - SERIES_MAX)
  series.lastEventMs = ms
  series.version += 1
}

export function seriesTokens(ms: number, out: number) {
  series.tokens.push([ms, out])
  if (series.tokens.length > SERIES_MAX) series.tokens.splice(0, series.tokens.length - SERIES_MAX)
  series.lastEventMs = ms
  series.version += 1
}

// Where this install keeps its files (Charon port W2, 2026-10-08). Resolved once
// per load by each module (each does its own `$` calls) through findRoots below,
// so the same code runs in any vault: no hardcoded user path. Null = no vault
// found, and then nothing is written anywhere.
export const roots: {
  vault: string | null
  state: string | null
  pipeline: string | null
  plugin: string | null
  resolved: boolean
} = { vault: null, state: null, pipeline: null, plugin: null, resolved: false }

const slash = (p: string) => p.split(String.fromCharCode(92)).join('/').replace(/\/+$/, '')

export type RootEnv = {
  vaultOverride?: string
  captureRoot?: string
  userProfile?: string
  home?: string
}

// The vault is HARNESS_VAULT_ROOT when set, else the nearest folder above the
// plugin holding `.claude/` and `scripts/load-rules.py` (true of the author's
// vault and of every Charon clone). The capture pipeline follows Charon's
// convention: HARNESS_CAPTURE_ROOT, else ~/capture-pipeline.
export async function findRoots(env: RootEnv, exists: (path: string) => Promise<boolean>, pluginRoot: string) {
  if (roots.resolved) return roots
  const plugin = slash(pluginRoot)
  const candidates: string[] = []
  if (env.vaultOverride) candidates.push(slash(env.vaultOverride))
  else {
    let dir = plugin
    for (let i = 0; i < 8 && dir.includes('/'); i++) {
      candidates.push(dir)
      dir = dir.slice(0, dir.lastIndexOf('/'))
    }
  }
  let vault: string | null = null
  for (const dir of candidates) {
    if ((await exists(`${dir}/.claude`)) && (await exists(`${dir}/scripts/load-rules.py`))) {
      vault = dir
      break
    }
  }
  const home = env.userProfile ?? env.home
  roots.plugin = plugin
  roots.vault = vault
  roots.state = vault ? `${vault}/state/agent-org` : null
  roots.pipeline = env.captureRoot ? slash(env.captureRoot) : home ? `${slash(home)}/capture-pipeline` : null
  roots.resolved = true
  return roots
}
