import { atom, read, update } from 'claude-code'
import type { Register, EngineInterface } from 'claude-code'

import type { PaneEvent } from '../types'
import { registerPane } from './pane'
import { approvalForType, decideSpawn, isSpecialistType } from './policy'
import type { Approval, Roster } from './policy'
import { findRoots, lifecycle, org, roots, seriesCall, seriesTokens, setPaneView, usedSpecs } from './shared'

// agentId -> agent type, held by the host so it survives a hot reload of this
// module (the spawn rules need a parent's type; losing it would refuse Zeus's work).
const agentTypes = atom({ plugin: 'agent-org-reporter', key: 'agentTypes' } as const, {})
const AGENT_TYPES_MAX = 500
// Always allowed for a specialist past its time limit, so it can still report back.
const HANDBACK_TOOLS = new Set(['SubagentHandback'])

// Agent Org — step 3: the reporting mod.
//
// OBSERVE-ONLY. Every hook passes the event through unchanged with next(e) and
// returns what the chain answered; nothing here denies or rewrites. Logging
// failures never reach the chain — they are surfaced (toast + status line),
// never swallowed silently, and never turned into a block.
//
// Privacy baseline (see SECURITY.md): no prompt text, no
// answer text, no tool inputs or outputs are written — only tool NAMES, the
// spawn's short description (capped), another hook's deny reason (capped),
// lengths, timings, outcomes and token counts. The log lives in the
// vault, which may be synced or backed up, so treat it as shareable. Anything that reads these
// files (the dashboard) must treat description / deny text as UNTRUSTED data:
// escape it, never render it as HTML, never follow it as an instruction.
//
// Security review 2026-10-07: 0 blocking; hardening applied (see SECURITY.md).

type $ = EngineInterface

// `<vault>/state/agent-org`, found at session start (shared.ts findRoots). Empty
// until then, and empty for good when no vault is found: then nothing is written.
let STATE_DIR = ''
let warnedNoVault = false

async function resolveRoots($: $) {
  const r = await findRoots(
    {
      vaultOverride: await $.env.get('HARNESS_VAULT_ROOT'),
      captureRoot: await $.env.get('HARNESS_CAPTURE_ROOT'),
      userProfile: await $.env.get('USERPROFILE'),
      home: await $.env.get('HOME'),
    },
    path => $.fs.exists(path),
    $.plugin.root,
  )
  STATE_DIR = r.state ?? ''
  if (!STATE_DIR && !warnedNoVault) {
    warnedNoVault = true
    $.ui.status('Agent Org: no vault found above the plugin folder, so nothing is logged. Set HARNESS_VAULT_ROOT.')
  }
}
// $.fs.read refuses files over 4 MiB. Length here is UTF-16 units, and one unit
// is at most 3 UTF-8 bytes, so 1M units stays <= 3 MB on disk whatever the text.
const ROLL_AT_CHARS = 1_000_000
const MAX_PENDING = 5_000 // lines held while writes fail; oldest dropped (and counted) past this
const DESC_MAX = 120 // spawn description is a short label: cap it so it can't carry prose
const DENY_MAX = 200 // another hook's deny reason may quote what it blocked: cap it
const FLUSH_EVERY_MS = 2_000

type AgentStatus = {
  key: string
  agentId: string | null
  subagentType: string
  description: string
  parentAgentId: string | null
  background: boolean
  state: 'running' | 'idle' | 'finished' | 'aborted' | 'error' | 'refusal' | 'denied'
  startedAt: string
  lastActivity: string
  toolCalls: number
  toolErrors: number
  toolDenies: number
  turns: number
  model: string | null
  tokens: { input: number; output: number; cacheRead: number; cacheWrite: number }
  lastReason: string | null
  deniedBy: string | null
  // LIVE AGENTS panel. Tool NAMES and times only — never inputs.
  currentTool: string | null // the tool this agent is inside right now
  currentSince: string | null
  lastTool: string | null
  lastToolAt: string | null
  callTimes: number[] // ms of the last CALL_TIMES_MAX calls, for the activity spark
  finishedAt: string | null
}

const CALL_TIMES_MAX = 40

// Module state: a hot reload starts this over (register runs in a fresh
// environment). The files on disk are the record; these are only the unflushed
// tail and the in-session roll-up.
let sessionId: string | null = null
let fileDay = '' // a session keeps the folder of the day its log started
let part = 0
let fileText: string | null = null // what is on disk for the current file
let pending: string[] = []
const status = new Map<string, AgentStatus>()
const dirty = new Set<string>()
let chain: Promise<void> = Promise.resolve()
let failures = 0
let dropped = 0
let hasWarned = false
let tick: { cancel: () => void } | null = null
// The pane's live view (pane.tsx): newest first, names and outcomes only.
const RECENT_MAX = 12
let recent: PaneEvent[] = []
let paneDirty = false

function iso() {
  return new Date().toISOString()
}

// Folder day is the machine's LOCAL date — the UTC slice put every
// Brisbane morning before 10:00 under yesterday. Line `ts` stays UTC.
function localDay() {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

function cap(text: string | null | undefined, max: number) {
  if (text == null) return null
  return text.length > max ? `${text.slice(0, max)}…[+${text.length - max}]` : text
}

// IDs come from the engine, but they become path segments: keep them to a safe
// alphabet so no value can add a separator, `..` or a Windows-reserved name.
function safeId(id: string) {
  return id.replace(/[^A-Za-z0-9_-]/g, '_').slice(0, 80) || '_'
}

function blank(key: string, agentId: string | null): AgentStatus {
  return {
    key,
    agentId,
    subagentType: agentId ? 'unknown' : 'main',
    description: agentId ? '' : 'main conversation',
    parentAgentId: null,
    background: false,
    state: 'running',
    startedAt: iso(),
    lastActivity: iso(),
    toolCalls: 0,
    toolErrors: 0,
    toolDenies: 0,
    turns: 0,
    model: null,
    tokens: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 },
    lastReason: null,
    deniedBy: null,
    currentTool: null,
    currentSince: null,
    lastTool: null,
    lastToolAt: null,
    callTimes: [],
    finishedAt: null,
  }
}

function statusFor(key: string, agentId: string | null) {
  let s = status.get(key)
  if (!s) {
    s = blank(key, agentId)
    status.set(key, s)
  }
  s.lastActivity = iso()
  dirty.add(key)
  return s
}

function loopStatus(agentId: string | undefined) {
  return statusFor(agentId ?? 'main', agentId ?? null)
}

// Some agents start without an agent.spawn event (a Workflow's agents, found
// 2026-10-08), so the reporter first meets them at a tool call and knows nothing
// about them. Ask the engine who they are, once per agent (retried every 5 s
// while it isn't listed yet), and audit where the facts came from.
const resolveTried = new Map<string, number>()
const RESOLVE_RETRY_MS = 5_000

async function resolveUnknown($: $, agentId: string) {
  const s = status.get(agentId)
  if (!s || s.subagentType !== 'unknown') return
  const last = resolveTried.get(agentId) ?? 0
  if (Date.now() - last < RESOLVE_RETRY_MS) return
  resolveTried.set(agentId, Date.now())
  const info = (await $.agent.list()).find(a => a.id === agentId)
  if (!info) return
  s.subagentType = cap(info.type || info.name || 'agent', 80) ?? 'agent'
  s.description = cap(info.description, DESC_MAX) ?? ''
  s.parentAgentId = info.parentId ?? s.parentAgentId
  dirty.add(agentId)
  paneDirty = true
  await rememberType($, agentId, s.subagentType)
  record('agent.seen', {
    agentId,
    subagentType: s.subagentType,
    description: s.description,
    parentAgentId: s.parentAgentId,
    via: 'agent.list',
  })
}

function record(kind: string, fields: Record<string, unknown>) {
  pending.push(JSON.stringify({ ts: iso(), kind, ...fields }) + '\n')
  if (pending.length > MAX_PENDING) {
    dropped += pending.length - MAX_PENDING
    pending = pending.slice(-MAX_PENDING)
  }
}

function note(ev: Omit<PaneEvent, 'ts'>) {
  recent = [{ ts: iso(), ...ev }, ...recent].slice(0, RECENT_MAX)
  paneDirty = true
}

function agentLabel(agentId: string | undefined) {
  if (!agentId) return 'main'
  return status.get(agentId)?.subagentType ?? 'subagent'
}

// Hand the pane a snapshot of the roll-up, at most once per tick. Plain data
// only (shared.ts); the pane publishes it. The view must never touch the log.
function publish() {
  if (!paneDirty) return
  paneDirty = false
  const all = [...status.values()]
  const main = status.get('main')
  const tokensOut = [...status.values()].reduce((n, s) => n + s.tokens.output, 0)
  try {
    setPaneView({
      agents: all.map(s => ({
        key: s.key,
        agentId: s.agentId,
        parentAgentId: s.parentAgentId,
        type: s.subagentType,
        description: s.description,
        state: s.state,
        toolCalls: s.toolCalls,
        tokensOut: s.tokens.output,
        startedAt: s.startedAt,
        lastActivity: s.lastActivity,
        currentTool: s.currentTool,
        currentSince: s.currentSince,
        lastTool: s.lastTool,
        callTimes: s.callTimes.slice(),
        finishedAt: s.finishedAt,
      })),
      recent,
      mainCalls: main?.toolCalls ?? 0,
      tokensOut,
    })
  } catch {
    paneDirty = true
  }
}

function surfaceFailure($: $, err: unknown) {
  failures += 1
  $.ui.status(`agent-org-reporter: ${failures} log write failure(s) — see state/agent-org`)
  if (!hasWarned) {
    hasWarned = true
    const msg = err instanceof Error ? err.name : 'error'
    $.ui.toast(`agent-org-reporter could not write its log (${msg}); retrying, nothing is blocked`)
  }
}

function auditPath() {
  return `${STATE_DIR}/audit/${fileDay}/${safeId(sessionId as string)}${part ? `.${part}` : ''}.jsonl`
}

async function ensureFile($: $) {
  if (!sessionId) {
    sessionId = await $.session.id()
    fileDay = localDay()
    part = 0
    fileText = null
  }
  if (fileText === null) {
    // After a reload, resume the highest part already on disk — never
    // overwrite a rolled part.
    while (await $.fs.exists(
      `${STATE_DIR}/audit/${fileDay}/${safeId(sessionId)}.${part + 1}.jsonl`)) part += 1
    const path = auditPath()
    fileText = (await $.fs.exists(path)) ? await $.fs.read(path) : ''
  }
}

async function writeAudit($: $, lines: string) {
  await ensureFile($)
  let text = fileText as string
  if (text.length + lines.length > ROLL_AT_CHARS) {
    part += 1
    text = ''
  }
  text += lines
  await $.fs.write(auditPath(), text)
  fileText = text // only once the write landed
}

async function writeStatus($: $) {
  if (!dirty.size || !sessionId) return
  const keys = [...dirty]
  dirty.clear()
  for (const key of keys) {
    const s = status.get(key)
    if (!s) continue
    try {
      await $.fs.write(
        `${STATE_DIR}/status/${safeId(sessionId)}/${safeId(key)}.json`,
        JSON.stringify({ sessionId, ...s }, null, 2) + '\n',
      )
    } catch (err) {
      dirty.add(key) // retry on the next flush
      throw err
    }
  }
}

// Serialised: one write at a time, so read-modify-write of this session's own
// file never races itself. Files are per-session, so sessions never contend.
function flush($: $) {
  chain = chain
    .then(async () => {
      if (!STATE_DIR) return
      if (pending.length || dropped) {
        const batch = pending
        pending = []
        if (dropped) {
          batch.unshift(JSON.stringify({ ts: iso(), kind: 'reporter.dropped', lines: dropped }) + '\n')
          dropped = 0
        }
        try {
          await writeAudit($, batch.join(''))
        } catch (err) {
          // A failed write must not lose lines: put the batch back for the
          // next flush. record() bounds how much is held.
          pending = [...batch, ...pending]
          throw err
        }
      }
      await writeStatus($)
    })
    .catch(err => surfaceFailure($, err))
  return chain
}

// Read-only load of the org data the spawn rules need. Runs in EVERY session
// (headless too), unlike the pane. pane.tsx is the only writer of approvals.json
// and also refreshes org.data straight after a decision.
const ORG_EVERY_MS = 5_000
let orgLoadedAt = 0

async function loadOrg($: $) {
  if (Date.now() - orgLoadedAt < ORG_EVERY_MS) return
  orgLoadedAt = Date.now()
  let roster: Roster | null = org.data?.roster ?? null
  let approvals: Record<string, Approval> = org.data?.approvals ?? {}
  try {
    // the vault's own roster, else the default shipped in the plugin (fresh install,
    // or no vault found: the spawn rules still hold; only approvals need a vault)
    const own = STATE_DIR ? `${STATE_DIR}/roster.json` : ''
    const rp = own && (await $.fs.exists(own)) ? own : `${roots.plugin}/roster.default.json`
    if (await $.fs.exists(rp)) {
      const r = JSON.parse(await $.fs.read(rp)) as Partial<Roster>
      if (Array.isArray(r.seats) && r.specialistPolicy) roster = { seats: r.seats, specialistPolicy: r.specialistPolicy }
    }
  } catch {
    // keep the last good roster; a half-saved file must not open the gate
  }
  try {
    const ap = STATE_DIR ? `${STATE_DIR}/approvals.json` : ''
    approvals = ap && (await $.fs.exists(ap))
      ? ((JSON.parse(await $.fs.read(ap)) as { approvals?: Record<string, Approval> }).approvals ?? {})
      : {}
  } catch {
    // keep the last good approvals
  }
  org.data = { roster, approvals, loadedAt: Date.now() }
}

function activeSpecialists() {
  return [...status.values()].filter(s => isSpecialistType(s.subagentType) && s.state === 'running').length
}

async function typeOf($: $, agentId: string | undefined | null) {
  if (!agentId) return null
  const known = status.get(agentId)?.subagentType
  if (known && known !== 'unknown') return known
  const types = (await read($, agentTypes)) ?? {}
  return types[agentId] ?? null
}

async function rememberType($: $, agentId: string, agentType: string) {
  await update($, agentTypes, m => {
    const next: Record<string, string> = { ...(m ?? {}), [agentId]: agentType }
    const keys = Object.keys(next)
    for (const k of keys.slice(0, Math.max(0, keys.length - AGENT_TYPES_MAX))) delete next[k]
    return next
  })
}

// Decide before the spawn runs. Fail-closed ONLY for governed spawns (nested, or a
// specialist type): an evaluation error must never stop the main conversation.
async function spawnRefusal($: $, e: { subagentType: string; fork: boolean; parentAgentId?: string }) {
  const governed = Boolean(e.parentAgentId) || isSpecialistType(e.subagentType)
  try {
    if (governed) await loadOrg($)
    const parentType = await typeOf($, e.parentAgentId)
    return decideSpawn(
      {
        subagentType: e.subagentType,
        fork: e.fork,
        parentAgentId: e.parentAgentId ?? null,
        parentType,
        parentKnown: !e.parentAgentId || parentType !== null,
        activeSpecialists: activeSpecialists(),
        nowMs: Date.now(),
        alreadyUsed: usedSpecs.has(e.subagentType),
      },
      org.data,
    )
  } catch {
    return governed ? 'Agent Org: the spawn rules could not be evaluated, so this governed start is refused.' : null
  }
}

// A specialist past its time limit, or calling a tool it was not approved for, is
// refused (its hand-back always passes). Null = allow.
async function toolRefusal($: $, agentId: string | undefined, tool: string) {
  if (!agentId || HANDBACK_TOOLS.has(tool)) return null
  try {
    const t = await typeOf($, agentId)
    if (!isSpecialistType(t) || !org.data) return null
    const a = approvalForType(org.data, t as string)
    if (!a) return 'Agent Org: this specialist has no approval on record. Report back to Zeus now.'
    if (!a.tools.includes(tool)) return `Agent Org: ${tool} is not in this specialist's approved tools (${a.tools.join(', ')}).`
    const started = Date.parse(status.get(agentId)?.startedAt ?? a.startedAt ?? '')
    if (started && Date.now() > started + a.maxMinutes * 60_000) {
      return `Agent Org: this specialist's ${a.maxMinutes}-minute limit is up. Report back to Zeus now with what you have.`
    }
    return null
  } catch {
    // G2 (security review): a specialist whose limits cannot be checked is refused;
    // anything else (main, seats) is not governed here and passes.
    const known = status.get(agentId)?.subagentType
    return isSpecialistType(known)
      ? 'Agent Org: this specialist\'s tool limits could not be checked, so the call is refused. Report back to Zeus.'
      : null
  }
}

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const result = await next(e)
    try {
      await resolveRoots($)
      sessionId = null
      record('session.start', { isInteractive: e.isInteractive })
      loopStatus(undefined)
      tick?.cancel() // session.start may fire again in the same environment
      tick = $.clock.every(FLUSH_EVERY_MS, () => {
        void flush($)
        publish()
        void loadOrg($).catch(() => undefined)
      })
      void flush($)
    } catch (err) {
      surfaceFailure($, err)
    }
    return result
  })

  on('agent.spawn', async ($, e, next) => {
    let refusal = await spawnRefusal($, e)
    const isSpec = isSpecialistType(e.subagentType)
    if (!refusal && isSpec) {
      if (usedSpecs.has(e.subagentType)) {
        refusal = `Agent Org: ${e.subagentType} is single-use and has already run. Propose a new specialist if the task needs more work.`
      } else {
        usedSpecs.add(e.subagentType) // marked BEFORE it starts: a parallel start now sees it
      }
    }
    const result = refusal ? { deny: refusal } : await next(e)
    if (isSpec && !refusal && !result.agentId && result.deny === undefined) usedSpecs.delete(e.subagentType) // never started
    try {
      const denied = result.deny !== undefined
      const description = cap(e.description, DESC_MAX) ?? ''
      const deny = cap(result.deny, DENY_MAX)
      record('agent.spawn', {
        agentId: result.agentId ?? null,
        parentAgentId: e.parentAgentId ?? null,
        subagentType: e.subagentType,
        description,
        background: e.background,
        fork: e.fork,
        provider: e.provider,
        model: result.model ?? null,
        promptChars: e.prompt.length,
        denied,
        deny,
      })
      if (result.agentId) {
        const s = loopStatus(result.agentId)
        s.subagentType = e.subagentType
        s.description = description
        s.parentAgentId = e.parentAgentId ?? null
        s.background = e.background
        s.model = result.model ?? null
        s.state = 'running'
        await rememberType($, result.agentId, e.subagentType)
        if (isSpecialistType(e.subagentType)) lifecycle.started.push({ agentType: e.subagentType, at: iso() })
      } else if (denied) {
        // A refused spawn has no agentId; keep it visible as its own row.
        const s = statusFor(`denied-${e.tool_use_id}`, null)
        s.subagentType = e.subagentType
        s.description = description
        s.state = 'denied'
        s.deniedBy = deny
      }
      note({
        who: e.subagentType,
        isSub: true,
        what: denied ? 'refused to start' : `started: ${description}`,
        outcome: denied ? 'blocked' : 'start',
      })
      void flush($)
    } catch (err) {
      surfaceFailure($, err)
    }
    return result
  })

  on('tool.call', async ($, e, next) => {
    const refusal = await toolRefusal($, e.agentId, e.tool)
    if (!refusal) {
      try {
        const s0 = loopStatus(e.agentId)
        if (e.agentId && s0.subagentType === 'unknown') void resolveUnknown($, e.agentId).catch(() => undefined)
        s0.currentTool = e.tool
        s0.currentSince = iso()
        if (s0.state === 'idle') s0.state = 'running' // main: a turn is under way
        paneDirty = true
      } catch {
        // the live view must never get in the way of the call
      }
    }
    const result = refusal ? { deny: refusal } : await next(e)
    try {
      const denied = result.deny !== undefined
      const isError = !denied && result.isError === true
      record('tool.call', {
        agentId: e.agentId ?? null,
        tool: e.tool,
        denied,
        isError,
      })
      const s = loopStatus(e.agentId)
      s.toolCalls += 1
      if (denied) s.toolDenies += 1
      if (isError) s.toolErrors += 1
      if (s.currentTool === e.tool) {
        s.currentTool = null
        s.currentSince = null
      }
      s.lastTool = e.tool
      s.lastToolAt = iso()
      s.callTimes.push(Date.now())
      if (s.callTimes.length > CALL_TIMES_MAX) s.callTimes.splice(0, s.callTimes.length - CALL_TIMES_MAX)
      seriesCall(Date.now())
      note({
        who: agentLabel(e.agentId),
        isSub: Boolean(e.agentId),
        what: e.tool,
        outcome: denied ? 'blocked' : isError ? 'error' : 'ok',
      })
    } catch (err) {
      surfaceFailure($, err)
    }
    return result
  })

  on('turn.complete', async ($, e, next) => {
    const result = await next(e)
    try {
      const u = e.usage
      record('turn.complete', {
        agentId: e.agentId ?? null,
        turnId: e.turnId,
        reason: e.reason,
        durationMs: e.durationMs,
        // A subagent answers through its hand-back TOOL, so 0 here is normal
        // for subagents — not "no answer".
        answerChars: e.answer.length,
        model: u?.model ?? null,
        usage: u
          ? {
              input: u.input_tokens,
              output: u.output_tokens,
              cacheRead: u.cache_read_input_tokens,
              cacheWrite: u.cache_creation_input_tokens,
            }
          : null,
      })
      const s = loopStatus(e.agentId)
      s.turns += 1
      s.lastReason = e.reason
      if (u) {
        seriesTokens(Date.now(), u.output_tokens)
        s.model = u.model
        s.tokens.input += u.input_tokens
        s.tokens.output += u.output_tokens
        s.tokens.cacheRead += u.cache_read_input_tokens
        s.tokens.cacheWrite += u.cache_creation_input_tokens
      }
      // A subagent's run is one turn: its turn.complete is its finish. The main
      // loop goes idle and waits for the next prompt. Anything outside the
      // known reasons is recorded as 'error' rather than trusted as a state.
      s.currentTool = null
      s.currentSince = null
      if (e.agentId) s.finishedAt = iso()
      if (e.reason === 'answer') s.state = e.agentId ? 'finished' : 'idle'
      else if (e.reason === 'aborted' || e.reason === 'refusal') s.state = e.reason
      else s.state = 'error'
      // A specialist has no Agent tool, so its one turn is its whole run: retire it.
      if (e.agentId && isSpecialistType(s.subagentType)) {
        lifecycle.finished.push({ agentType: s.subagentType, at: iso() })
      }
      note({
        who: agentLabel(e.agentId),
        isSub: Boolean(e.agentId),
        what: e.reason === 'answer'
          ? `${e.agentId ? 'finished' : 'answered'} in ${Math.round(e.durationMs / 100) / 10}s`
          : `stopped (${e.reason})`,
        outcome: e.reason === 'answer' ? 'done' : 'stopped',
      })
      void flush($)
    } catch (err) {
      surfaceFailure($, err)
    }
    return result
  })

  on('session.end', async ($, e, next) => {
    try {
      record('session.end', { reason: e.reason })
      loopStatus(undefined).state = 'finished'
      await flush($)
      // After /clear the process continues under a new session id with no
      // session.start: start a fresh file and roll-up on the next event.
      sessionId = null
      status.clear()
    } catch (err) {
      surfaceFailure($, err)
    }
    return next(e)
  })

  registerPane(on)
}
