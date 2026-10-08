import type { PaneEvent, PaneSpecialist } from '../types'
import type { Lane, OrgChartData } from './gfx'

// Demo mode (`/agent-org demo`, Charon port plan W1): a sample org with
// believable, moving activity, for screenshots that must contain NO real data
// (plan D2). Pure: no `$`, no files. Everything is made from the clock, so the
// graphs, sparks and feed move like a live session.
//
// The seat names are the ones Charon ships (they are the product, not private
// data). Every task, session id, count and specialist below is invented. The
// same story is told on the webpage by dashboard/demo.py; keep the two in step.

const SPEC = 'agent-org-reporter:spec-'

// Deterministic noise in [0, 1) for an integer: the same bucket always gets the
// same value, so a graph does not flicker as it redraws.
function noise(i: number) {
  let x = Math.imul(i ^ 0x9e3779b9, 0x85ebca6b)
  x ^= x >>> 13
  x = Math.imul(x, 0xc2b2ae35)
  x ^= x >>> 16
  return (x >>> 0) / 4294967296
}

// A working rhythm: busy stretches and quiet ones, a few minutes each.
function busy(t: number) {
  const m = t / 60_000
  return 0.55 + 0.3 * Math.sin(m / 3.1) + 0.15 * Math.sin(m / 1.3 + 1)
}

export function demoCalls(now: number, size: number, n: number) {
  const end = Math.floor(now / size)
  const out: number[] = []
  for (let i = end - n + 1; i <= end; i++) {
    // bursts while a task runs, near-quiet between them
    const b = busy(i * size)
    const v = b > 0.5 ? (b - 0.5) * 22 + noise(i) * 6 : noise(i) < 0.25 ? noise(i + 1) * 3 : 0
    out.push(Math.round(v))
  }
  return out
}

export function demoTokens(now: number, size: number, n: number) {
  const end = Math.floor(now / size)
  const out: number[] = []
  for (let i = end - n + 1; i <= end; i++) {
    const b = busy(i * size)
    const v = b > 0.45 ? b * 6000 + noise(i + 7919) * 3500 : noise(i + 7919) * 1200
    out.push(noise(i + 104729) < 0.18 ? 0 : Math.max(0, Math.round(v)))
  }
  return out
}

// Calls at a steady pace with some gaps, the last 40 of them.
function callTimes(now: number, everyMs: number, seed: number) {
  const out: number[] = []
  const end = Math.floor(now / everyMs)
  for (let i = end; i > end - 60 && out.length < 40; i--) {
    if (noise(i * 31 + seed) > 0.3) out.unshift(i * everyMs + Math.floor(noise(i + seed) * everyMs * 0.6))
  }
  return out.filter(t => t <= now)
}

function iso(ms: number) {
  return new Date(ms).toISOString()
}

type LaneSpec = {
  key: string
  agentId: string | null
  parentAgentId: string | null
  type: string
  description: string
  startedAgoMs: number
  everyMs: number
  tools: string[]
  session: string
  own: boolean
  limitMin?: number
  finishedAgoMs?: number
  toolCalls?: number
  tier?: string // shows a size badge when it differs from the user's model
}

const SESSION_A = '7f3c21aa'
const SESSION_B = 'c94e0d5b'

const LANES: LaneSpec[] = [
  { key: 'main', agentId: null, parentAgentId: null, type: 'main', description: '', startedAgoMs: 52 * 60_000, everyMs: 6_000, tools: ['Agent', 'Read', 'Bash'], session: SESSION_A, own: true },
  { key: 'z1', agentId: 'z1', parentAgentId: null, type: 'zeus', description: 'Prepare the weekly security brief', startedAgoMs: 9 * 60_000, everyMs: 7_000, tools: ['Agent', 'Read', 'Agent', 'Grep'], session: SESSION_A, own: true },
  { key: 'a1', agentId: 'a1', parentAgentId: 'z1', type: 'athena', description: 'Find last week\'s vendor review notes', startedAgoMs: 4 * 60_000, everyMs: 2_100, tools: ['Grep', 'Read', 'Glob', 'Read'], session: SESSION_A, own: true },
  { key: 'p1', agentId: 'p1', parentAgentId: 'z1', type: 'prometheus', description: 'Scan this week\'s advisories for the stack', startedAgoMs: 7 * 60_000, everyMs: 3_300, tools: ['WebSearch', 'WebFetch', 'WebFetch'], session: SESSION_A, own: true },
  { key: 's1', agentId: 's1', parentAgentId: 'z1', type: `${SPEC}licence-scan`, description: 'Check new dependencies\' licences', startedAgoMs: 6 * 60_000, everyMs: 4_200, tools: ['Read', 'WebFetch'], session: SESSION_A, own: true, limitMin: 15 },
  { key: 'main', agentId: null, parentAgentId: null, type: 'main', description: '', startedAgoMs: 21 * 60_000, everyMs: 9_000, tools: ['Skill', 'Read'], session: SESSION_B, own: false },
  { key: 'h1', agentId: 'h1', parentAgentId: null, type: 'hephaestus', description: 'Weekly harness tune-up', startedAgoMs: 3 * 60_000, everyMs: 5_000, tools: ['Skill', 'Read', 'Grep'], session: SESSION_B, own: false, tier: 'haiku' },
  { key: 'c1', agentId: 'c1', parentAgentId: 'z1', type: 'calliope', description: 'Draft the summary for the team', startedAgoMs: 252_000, everyMs: 4_000, tools: ['Read', 'Write'], session: SESSION_A, own: true, finishedAgoMs: 40_000, toolCalls: 63 },
]

// The demo started this long before it was turned on, so the clock-relative
// times above read as a session in progress. Restarts if demo is turned on again.
let epoch = Date.now()
export function resetDemo() {
  epoch = Date.now()
}

export function demoLanes(now: number): Lane[] {
  return LANES.map(s => {
    // A finished lane stays "just finished" (finishedAgoMs before now); its
    // startedAgoMs is then how long it ran.
    const finishedAt = s.finishedAgoMs !== undefined ? now - s.finishedAgoMs : null
    const started = finishedAt !== null ? finishedAt - s.startedAgoMs : epoch - s.startedAgoMs
    const times = finishedAt ? [] : callTimes(now, s.everyMs, s.key.charCodeAt(0))
    const tick = Math.floor(now / s.everyMs)
    const tool = s.tools[tick % s.tools.length]
    const inTool = !finishedAt && noise(tick * 7 + s.key.length) > 0.25
    return {
      session: s.session,
      own: s.own,
      key: s.key,
      agentId: s.agentId,
      parentAgentId: s.parentAgentId,
      type: s.type,
      description: s.description,
      state: finishedAt ? 'finished' : 'running',
      currentTool: inTool ? tool : null,
      currentSince: inTool ? iso(tick * s.everyMs) : null,
      lastTool: tool,
      callTimes: times,
      startedAt: iso(started),
      finishedAt: finishedAt ? iso(finishedAt) : null,
      lastActivity: iso(times[times.length - 1] ?? now),
      toolCalls: s.toolCalls ?? Math.round((now - started) / s.everyMs),
      limitMin: s.limitMin ?? null,
      tier: s.tier ?? null,
      tierNote: s.tier ? 'below your model' : null,
    }
  })
}

export function demoOrg(running: Map<string, number>): OrgChartData {
  const node = (type: string, name: string) => ({ name, running: running.get(type) ?? 0 })
  return {
    chief: node('zeus', 'Zeus'),
    seats: [
      node('athena', 'Athena'),
      node('helios', 'Helios'),
      node('prometheus', 'Prometheus'),
      node('calliope', 'Calliope'),
      node('hephaestus', 'Hephaestus'),
    ],
    reviewers: [
      node('knowledge-synthesizer', 'synth'),
      node('secure-code-reviewer', 'secure-code'),
      node('owasp-llm-reviewer', 'owasp-llm'),
      node('owasp-agentic-reviewer', 'owasp-agentic'),
    ],
    specialists: [{ name: 'licence-scan', running: running.get(`${SPEC}licence-scan`) ?? 0, ready: false }],
    independent: node('cerberus', 'Cerberus'),
  }
}

export const DEMO_PENDING: PaneSpecialist = {
  id: 'demo-dpa-check',
  slug: 'dpa-check',
  title: 'Compare a vendor DPA against the data-retention guideline',
  purpose: 'No seat reads contracts clause by clause; this needs one careful pass.',
  tools: ['Read', 'WebFetch'],
  maxMinutes: 20,
  status: 'pending',
  proposedAt: new Date().toISOString(),
  model: 'sonnet',
  modelReason: 'bounded extraction from two named documents; no judgement calls',
  sizeNote: 'sonnet, below your model',
  cardHash: 'demo',
  task: 'Read the supplied DPA and list every retention clause that is longer than the guideline allows.',
  brief:
    'You are checking one vendor data processing agreement. Read the DPA at the path given, then the ' +
    'retention guideline. For each clause about how long data is kept, quote it, give the period, and say ' +
    'whether it is within the guideline. Report clause numbers and quotes only; do not summarise the contract.',
}

const FEED_SCRIPT: [string, boolean, string, PaneEvent['outcome']][] = [
  ['athena', true, 'Grep', 'ok'],
  ['prometheus', true, 'WebSearch', 'ok'],
  ['zeus', true, 'Agent → athena', 'start'],
  ['spec:licence', true, 'WebFetch', 'ok'],
  ['athena', true, 'Read', 'ok'],
  ['main', false, 'Read', 'ok'],
  ['prometheus', true, 'WebFetch', 'error'],
  ['hephaestus', true, 'Skill', 'ok'],
  ['zeus', true, 'Agent → general-purpose', 'blocked'],
  ['calliope', true, 'answered in 4m 12s', 'done'],
  ['athena', true, 'Glob', 'ok'],
  ['spec:licence', true, 'Read', 'ok'],
]
const FEED_STEP_MS = 2_500

// The feed advances one row every FEED_STEP_MS; `step` changes when it does.
export function demoFeed(now: number, n: number): { step: number; rows: PaneEvent[] } {
  const step = Math.floor(now / FEED_STEP_MS)
  const rows: PaneEvent[] = []
  for (let k = 0; k < n; k++) {
    const i = step - k
    const [who, isSub, what, outcome] = FEED_SCRIPT[((i % FEED_SCRIPT.length) + FEED_SCRIPT.length) % FEED_SCRIPT.length]
    rows.push({ ts: iso(i * FEED_STEP_MS), who, isSub, what, outcome })
  }
  return { step, rows }
}

export function demoStats(now: number) {
  const run = Math.floor((now - epoch) / 2_500)
  return { callsToday: 1_486 + run, tokensToday: 412_300 + run * 310 }
}

export const DEMO_GATES = { allow: 612, observe: 148, ask: 9, deny: 2 }
export const DEMO_WAITING = { reviewQueue: 3, overdue: 2 }
