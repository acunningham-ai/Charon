// Agent Org — pane graphics. PURE: no `$`, no clock, no files. Every function takes
// its data and a width and returns a Grid, which `cells()` packs into a terminal
// `Raster` (RasterProps.cells: base64 of [codePoint, fg, bg] u32 triplets) and
// `text()` renders as plain lines for testing outside the engine.
//
// Look: telemetry-first, eDEX-level graphics, webpage palette
// (Aegean tones, bronze = running), traditional top-down org chart.

export const C = {
  def: 0x01000000, // the terminal's own default colour
  text: 0xe6ecf5,
  muted: 0x9aa8bf,
  rule: 0x3a5079,
  dim: 0x6c7a93,
  bronze: 0xd4a24c,
  bronzeDim: 0x8a6a33,
  ok: 0x5fbf9a,
  watch: 0x7c93c3,
  ask: 0xf08a5d,
  deny: 0xf2677a,
  graph: 0x8fa6d3,
  grid: 0x1e2c45,
} as const

export type Grid = { w: number; h: number; ch: number[]; fg: number[]; bg: number[] }

export function grid(w: number, h: number): Grid {
  const n = Math.max(1, w) * Math.max(1, h)
  return { w: Math.max(1, w), h: Math.max(1, h), ch: new Array(n).fill(32), fg: new Array(n).fill(C.def), bg: new Array(n).fill(C.def) }
}

export function put(g: Grid, x: number, y: number, s: string, fg: number = C.text) {
  if (y < 0 || y >= g.h) return
  let i = 0
  for (const chr of s) {
    const cx = x + i++
    if (cx < 0 || cx >= g.w) continue
    const cp = chr.codePointAt(0) ?? 32
    // Raster cells take printable width-1 BMP characters only.
    g.ch[y * g.w + cx] = cp > 0xffff || cp < 32 ? 63 : cp
    g.fg[y * g.w + cx] = fg
  }
}

function setFg(g: Grid, x: number, y: number, fg: number) {
  if (x >= 0 && x < g.w && y >= 0 && y < g.h) g.fg[y * g.w + x] = fg
}

function at(g: Grid, x: number, y: number) {
  return x >= 0 && x < g.w && y >= 0 && y < g.h ? String.fromCodePoint(g.ch[y * g.w + x]) : ' '
}

// A panel rule: "LABEL ──────────── right".
export function rule(g: Grid, y: number, label: string, right = '', fgRight: number = C.muted) {
  put(g, 0, y, '─'.repeat(g.w), C.rule)
  put(g, 0, y, label + ' ', C.muted)
  if (right) put(g, Math.max(label.length + 2, g.w - right.length - 1), y, ' ' + right, fgRight)
}

// ------------------------------------------------------------- packing ---

const B64 = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/'

function base64(bytes: Uint8Array) {
  let out = ''
  for (let i = 0; i < bytes.length; i += 3) {
    const a = bytes[i] ?? 0, b = bytes[i + 1] ?? 0, c = bytes[i + 2] ?? 0
    const n = (a << 16) | (b << 8) | c
    out += B64[(n >> 18) & 63] + B64[(n >> 12) & 63]
    out += i + 1 < bytes.length ? B64[(n >> 6) & 63] : '='
    out += i + 2 < bytes.length ? B64[n & 63] : '='
  }
  return out
}

export function cells(g: Grid) {
  const words = new Uint32Array(g.w * g.h * 3)
  for (let i = 0; i < g.w * g.h; i++) {
    words[i * 3] = g.ch[i]
    words[i * 3 + 1] = g.fg[i]
    words[i * 3 + 2] = g.bg[i]
  }
  // Little-endian bytes, as RasterProps requires, whatever the host's order.
  const bytes = new Uint8Array(words.length * 4)
  for (let i = 0; i < words.length; i++) {
    const v = words[i]
    bytes[i * 4] = v & 0xff
    bytes[i * 4 + 1] = (v >>> 8) & 0xff
    bytes[i * 4 + 2] = (v >>> 16) & 0xff
    bytes[i * 4 + 3] = (v >>> 24) & 0xff
  }
  return base64(bytes)
}

export function text(g: Grid) {
  const lines: string[] = []
  for (let y = 0; y < g.h; y++) {
    let s = ''
    for (let x = 0; x < g.w; x++) s += String.fromCodePoint(g.ch[y * g.w + x])
    lines.push(s.replace(/\s+$/, ''))
  }
  return lines.join('\n')
}

// --------------------------------------------------------------- clock ---

const DIGITS: Record<string, [string, string, string]> = {
  '0': ['█▀█', '█ █', '█▄█'],
  '1': ['▄█ ', ' █ ', '▄█▄'],
  '2': ['▀▀█', '█▀▀', '█▄▄'],
  '3': ['▀▀█', ' ▀█', '▄▄█'],
  '4': ['█ █', '▀▀█', '  █'],
  '5': ['█▀▀', '▀▀█', '▄▄█'],
  '6': ['█▀▀', '█▀█', '█▄█'],
  '7': ['▀▀█', '  █', '  █'],
  '8': ['█▀█', '█▀█', '█▄█'],
  '9': ['█▀█', '▀▀█', '▄▄█'],
  ':': ['▄', ' ', '▀'],
}

export type Stat = { label: string; value: string; hot?: boolean }

// Header panel: rule, big HH:MM:SS, and up to three stats to its right.
export function clockPanel(w: number, hhmmss: string, live: boolean, stats: Stat[], tag?: string) {
  const g = grid(w, 4)
  // tag: demo mode labels itself so a screenshot can never pass for real activity
  rule(g, 0, 'SYSTEM', tag ? `◆ ${tag}  ` : live ? '● LIVE  ' : '○ IDLE  ', tag ? C.bronze : live ? C.ok : C.dim) // 2 cols clear of the pane's close mark
  let x = 0
  for (const chr of hhmmss) {
    const d = DIGITS[chr]
    if (!d) continue
    for (let r = 0; r < 3; r++) put(g, x, r + 1, d[r], C.text)
    x += d[0].length + 1
  }
  const sx = x + 2
  if (w - sx >= 14) {
    stats.slice(0, 3).forEach((s, i) => {
      put(g, sx, i + 1, s.label.padEnd(8), C.muted)
      put(g, sx + 8, i + 1, s.value, s.hot ? C.bronze : C.text)
    })
  }
  return g
}

// -------------------------------------------------------------- graphs ---

const DOT = [
  [0x01, 0x08],
  [0x02, 0x10],
  [0x04, 0x20],
  [0x40, 0x80],
]

// A braille graph: one sample per dot column (2 per cell), `rows` cells tall,
// drawn from column `x0` for `cols` cells. line: joined; area: filled to the
// baseline. Newest sample at the right.
export function brailleGraph(
  g: Grid, top: number, rows: number, samples: number[], mode: 'line' | 'area', fg: number, x0 = 0, cols = g.w,
) {
  const pw = cols * 2
  const ph = rows * 4
  const data = samples.slice(-pw)
  const pad = pw - data.length
  const max = Math.max(1, ...data)
  const bits = new Array(cols * rows).fill(0)
  const ys: number[] = data.map(v => (v <= 0 ? ph : ph - 1 - Math.round((v / max) * (ph - 1))))
  const dot = (px: number, py: number) => {
    if (px < 0 || px >= pw || py < 0 || py >= ph) return
    bits[(py >> 2) * cols + (px >> 1)] |= DOT[py & 3][px & 1]
  }
  ys.forEach((y, i) => {
    const px = pad + i
    if (mode === 'area') {
      for (let py = y; py < ph; py++) dot(px, py)
    } else {
      const prev = i > 0 ? ys[i - 1] : y
      const yy = Math.min(y, ph - 1)
      const pp = Math.min(prev, ph - 1)
      for (let py = Math.min(yy, pp); py <= Math.max(yy, pp); py++) dot(px, py)
    }
  })
  for (let cy = 0; cy < rows; cy++) {
    for (let cx = 0; cx < cols; cx++) {
      if (top + cy >= g.h || x0 + cx >= g.w) continue
      const b = bits[cy * cols + cx]
      const i = (top + cy) * g.w + x0 + cx
      g.ch[i] = 0x2800 + b
      g.fg[i] = b ? fg : C.rule
    }
  }
}

// Solid bar chart from eighth blocks: `rows` cells tall = rows*8 levels, one sample
// per column, newest at the right. (Braille rendered as faint scattered dots in
// Windows Terminal, so graphs use blocks.)
const EIGHTHS = ' ▁▂▃▄▅▆▇█'

export function barGraph(g: Grid, top: number, rows: number, samples: number[], fg: number) {
  const data = samples.slice(-g.w)
  const pad = g.w - data.length
  const max = Math.max(1, ...data)
  for (let x = 0; x < g.w; x++) {
    const v = x < pad ? 0 : data[x - pad]
    let level = v > 0 ? Math.max(1, Math.round((v / max) * rows * 8)) : 0
    for (let r = rows - 1; r >= 0; r--) {
      const here = Math.min(8, level)
      level -= here
      const i = (top + r) * g.w + x
      if (top + r >= g.h) continue
      g.ch[i] = here ? EIGHTHS.codePointAt(here) as number : 0x2581
      g.fg[i] = here ? fg : C.grid
    }
  }
}

// ACTIVITY: calls per 10 s (3 rows, bronze) over tokens per minute (2 rows, blue).
export function activityPanel(w: number, calls: number[], tokens: number[], right: string) {
  const g = grid(w, 1 + 3 + 1 + 2)
  rule(g, 0, 'ACTIVITY', right)
  barGraph(g, 1, 3, calls, C.bronze)
  put(g, 0, 4, 'calls per 10s', C.muted)
  const tl = 'tokens per min'
  put(g, w - tl.length, 4, tl, C.muted)
  barGraph(g, 5, 2, tokens, C.graph)
  return g
}

// --------------------------------------------------------------- gates ---

// GATES: counts in the rule line, one segmented bar beneath.
export function gatesPanel(w: number, c: { allow: number; observe: number; ask: number; deny: number } | null) {
  const g = grid(w, 2)
  const total = c ? c.allow + c.observe + c.ask + c.deny : 0
  put(g, 0, 0, '─'.repeat(w), C.rule)
  put(g, 0, 0, 'GATES ', C.muted)
  if (!c || !total) {
    put(g, 0, 1, c ? 'No gate verdicts yet today.' : 'Gate log not read yet.', C.dim)
    return g
  }
  const wide = w >= 52
  const legend: [string, number, number][] = [
    [`${c.allow} ${wide ? 'allowed' : 'ok'}`, c.allow, C.ok],
    [`${c.observe} ${wide ? 'watched' : 'watch'}`, c.observe, C.watch],
    [`${c.ask} ${wide ? 'asked' : 'ask'}`, c.ask, C.ask],
    [`${c.deny} ${wide ? 'blocked' : 'block'}`, c.deny, C.deny],
  ]
  const text = legend.map(l => l[0]).join('  ')
  let lx = Math.max(7, w - text.length)
  put(g, lx - 1, 0, ' '.repeat(text.length + 1), C.def)
  for (const [s, n, fg] of legend) {
    put(g, lx, 0, s, n ? fg : C.dim)
    lx += s.length + 2
  }
  const parts: [number, number, string][] = [
    [c.allow, C.ok, '█'],
    [c.observe, C.watch, '▓'],
    [c.ask, C.ask, '▒'],
    [c.deny, C.deny, '░'],
  ]
  let x = 0
  parts.forEach(([n, fg, chr]) => {
    let span = Math.round((n / total) * w)
    if (n > 0 && span === 0) span = 1 // a single ask or block is never invisible
    span = Math.max(0, Math.min(span, w - x))
    put(g, x, 1, chr.repeat(span), fg)
    x += span
  })
  return g
}

// ----------------------------------------------------------- org chart ---
// Traditional top-down chart, compact: YOU above a one-row ZEUS
// box, Cerberus beside it on a dotted line to YOU; a bus, a small downward dash
// (╵) and the NAME per agent. Running = bronze dash + "●NAME".

export type OrgNode = { name: string; running: number; ready?: boolean }

export type OrgChartData = {
  chief: OrgNode
  seats: OrgNode[]
  reviewers: OrgNode[]
  specialists: OrgNode[] // approved / running single-use specialists
  independent: OrgNode | null // Cerberus
}

function centers(n: number, x0: number, w: number) {
  const slot = (w - x0) / Math.max(1, n)
  return Array.from({ length: n }, (_, i) => Math.floor(x0 + slot * i + slot / 2))
}

function short(name: string, max: number) {
  const up = name.toUpperCase()
  return up.length <= max ? up : up.slice(0, Math.max(1, max - 1)) + '…'
}

// One tier: bus row, small downward dash (╵), NAME, then a status mark (● running,
// ○ idle) so state never rests on colour alone.
function tier(g: Grid, y: number, nodes: OrgNode[], w: number, pulse: boolean, dashed: boolean, spine: string) {
  const x0 = 2
  const xs = centers(nodes.length, x0, w)
  if (!xs.length) return
  const right = xs[xs.length - 1]
  put(g, 0, y, (dashed ? '┄' : '─').repeat(right + 1), C.rule)
  put(g, 0, y, spine, C.rule)
  // Names at full length, then trimmed only where they would touch a neighbour.
  const labels = nodes.map(n => n.name.toUpperCase())
  const starts = labels.map((t, i) => xs[i] - Math.floor((t.length - 1) / 2))
  for (let i = 0; i < labels.length; i++) {
    const nextStart = i + 1 < labels.length ? starts[i + 1] : w + 1
    const room = Math.min(nextStart - 1 - starts[i], w - starts[i])
    if (labels[i].length > room) labels[i] = labels[i].slice(0, Math.max(2, room - 1)) + '…'
  }
  xs.forEach((x, i) => {
    const n = nodes[i]
    const run = n.running > 0
    const hot = pulse ? C.bronze : C.bronzeDim
    put(g, x, y, i === xs.length - 1 ? '┐' : '┬', run ? C.bronze : C.rule)
    put(g, x, y + 1, '╵', run ? hot : C.rule)
    put(g, starts[i], y + 2, labels[i], run ? C.bronze : n.ready ? C.text : C.muted)
    put(g, x, y + 3, run ? '●' : '○', run ? hot : C.dim)
    if (run && n.running > 1) put(g, x + 1, y + 3, String(n.running), C.bronze)
  })
}

export function orgPanel(w: number, d: OrgChartData, pulse: boolean) {
  const hasSpecs = d.specialists.length > 0
  const g = grid(w, 1 + 1 + 3 + 4 + 4 + (hasSpecs ? 4 : 0))
  const running = [d.chief, ...d.seats, ...d.reviewers, ...d.specialists].reduce((n, x) => n + x.running, 0)
  rule(g, 0, 'ORG', running ? `${running} running` : 'all idle', running ? C.bronze : C.muted)

  // YOU, then a boxed ZEUS directly below; Cerberus beside it, dotted up to YOU.
  const zname = d.chief.name.toUpperCase()
  const zw = zname.length + 4
  const zx = Math.max(2, Math.floor((w - zw) / 2) - (d.independent ? 7 : 0))
  const cx = zx + Math.floor(zw / 2)
  const chiefRun = d.chief.running > 0
  const zb = chiefRun ? C.bronze : C.rule
  put(g, cx - 1, 1, 'YOU', C.text)
  put(g, zx, 2, '┌' + '─'.repeat(zw - 2) + '┐', zb)
  put(g, cx, 2, '┴', zb)
  put(g, zx, 3, '│', zb)
  put(g, zx + 2, 3, zname, chiefRun ? (pulse ? C.bronze : C.bronzeDim) : C.text)
  put(g, zx + zw - 1, 3, '│', zb)
  put(g, zx, 4, '└' + '─'.repeat(zw - 2) + '┘', zb)
  put(g, cx, 4, '┬', zb)

  if (d.independent) {
    const iname = d.independent.name.toUpperCase()
    const iw = iname.length + 4
    const ix = Math.min(w - iw - 1, zx + zw + 5)
    const icx = ix + Math.floor(iw / 2)
    const ir = d.independent.running > 0
    const ib = ir ? C.bronze : C.rule
    put(g, cx + 2, 1, ' ' + '┄'.repeat(Math.max(1, icx - cx - 3)) + '┐', C.rule)
    put(g, ix, 2, '┌' + '┄'.repeat(iw - 2) + '┐', ib)
    put(g, icx, 2, '┴', ib)
    put(g, ix, 3, '┆', ib)
    put(g, ix + 2, 3, iname, ir ? (pulse ? C.bronze : C.bronzeDim) : C.muted)
    put(g, ix + iw - 1, 3, '┆', ib)
    put(g, ix, 4, '└' + '┄'.repeat(iw - 2) + '┘', ib)
    const tag = 'independent'
    if (ix + iw + 1 + tag.length <= w) put(g, ix + iw + 1, 3, tag, C.dim)
    else put(g, Math.max(0, ix + Math.floor((iw - tag.length) / 2)), 5, '', C.dim)
  }

  // Tier 1: seats on a bus hanging from Zeus.
  tier(g, 5, d.seats, w, pulse, false, '┌')
  put(g, cx, 5, '┴', chiefRun ? C.bronze : C.rule)
  // Tier 2: standing reviewers on the left spine; tier 3: approved specialists (dashed).
  for (let y = 6; y < 9; y++) put(g, 0, y, '│', C.rule)
  tier(g, 9, d.reviewers, w, pulse, false, hasSpecs ? '├' : '└')
  if (hasSpecs) {
    for (let y = 10; y < 13; y++) put(g, 0, y, '┆', C.rule)
    tier(g, 13, d.specialists, w, pulse, true, '└')
  }
  return g
}

// ---------------------------------------------------------------- feed ---

export type FeedRow = { ts: string; who: string; isSub: boolean; what: string; outcome: string }

const OUT_FG: Record<string, number> = { ok: C.ok, done: C.ok, start: C.bronze, error: C.ask, blocked: C.deny, stopped: C.deny }

export function feedPanel(w: number, rows: FeedRow[], n: number, clock: (ts: string) => string) {
  const g = grid(w, n + 1)
  rule(g, 0, 'FEED', rows.length ? 'newest first' : 'nothing yet')
  rows.slice(0, n).forEach((r, i) => {
    const y = i + 1
    put(g, 0, y, clock(r.ts), C.dim)
    const who = r.who.length > 10 ? r.who.slice(0, 9) + '…' : r.who
    put(g, 9, y, who, r.isSub ? C.bronze : C.text)
    const outW = 6
    const whatW = Math.max(4, w - 20 - outW - 1)
    const what = r.what.length > whatW ? r.what.slice(0, whatW - 1) + '…' : r.what
    put(g, 20, y, what, C.muted)
    put(g, w - outW, y, r.outcome.padStart(outW), OUT_FG[r.outcome] ?? C.muted)
  })
  return g
}

// ------------------------------------------------------------- waiting ---

export function waitingPanel(w: number, reviewQueue: number | null, overdue: number | null) {
  const g = grid(w, 1)
  put(g, 0, 0, '─'.repeat(w), C.rule)
  put(g, 0, 0, 'WAITING ON YOU ', C.muted)
  const q = reviewQueue === null ? '–' : String(reviewQueue)
  const o = overdue === null ? '–' : String(overdue)
  const parts: [string, number][] = [
    [q, reviewQueue ? C.ask : C.ok], [w >= 52 ? ' in review queue  ' : ' queued  ', C.muted], [o, overdue ? C.ask : C.ok], [' overdue', C.muted],
  ]
  const len = parts.reduce((n, p) => n + p[0].length, 0)
  let x = Math.max(16, w - len)
  put(g, x - 1, 0, ' ', C.def)
  for (const [t, fg] of parts) { put(g, x, 0, t, fg); x += t.length }
  return g
}

// --------------------------------------------------------- live agents ---
// One lane per running agent across all sessions, children
// indented under their parent, then a "just finished" fade.

export type Lane = {
  session: string // short id
  own: boolean // this session
  key: string
  agentId: string | null
  parentAgentId: string | null
  type: string
  description: string
  state: string
  currentTool: string | null
  currentSince: string | null
  lastTool: string | null
  callTimes: number[]
  startedAt: string
  finishedAt: string | null
  lastActivity: string
  toolCalls: number
  limitMin: number | null // specialists: approved minutes
  tier: string | null // size it runs on
  tierNote: string | null // set only when it differs from the user's model
}

const LIVE_MAX_ROWS = 12
const FINISHED_FOR_MS = 120_000
const SPARK_CELLS = 8
const SPARK_STEP_MS = 4_000 // 8 cells x 4 s = the last 32 s

export function laneName(l: Lane) {
  if (l.key === 'main') return 'MAIN CHAT'
  const t = l.type.startsWith('agent-org-reporter:spec-') ? 'SPEC:' + l.type.slice('agent-org-reporter:spec-'.length) : l.type
  return t.toUpperCase()
}

export function elapsed(ms: number) {
  const s = Math.max(0, Math.round(ms / 1000))
  if (s < 60) return `${s}s`
  if (s < 3600) return `${Math.floor(s / 60)}m`
  return `${Math.floor(s / 3600)}h${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}`
}

// A one-row bar chart of calls in 2 s windows, newest at the right, in solid
// eighth blocks (braille renders as faint dots in Windows Terminal).
function spark(g: Grid, x: number, y: number, times: number[], now: number, fg: number) {
  const counts = new Array(SPARK_CELLS).fill(0)
  for (const t of times) {
    const b = Math.floor((now - t) / SPARK_STEP_MS)
    if (b >= 0 && b < SPARK_CELLS) counts[SPARK_CELLS - 1 - b] += 1
  }
  const max = Math.max(1, ...counts)
  for (let c = 0; c < SPARK_CELLS; c++) {
    const v = counts[c]
    const level = v ? Math.max(1, Math.round((v / max) * 8)) : 0
    put(g, x + c, y, level ? EIGHTHS.charAt(level) : '▁', level ? fg : C.grid)
  }
}

export function livePanel(w: number, lanes: Lane[], now: number, pulse: boolean) {
  // 'waiting' = between turns while its own agents run (Zeus after his dispatch note): still active
  const isRunning = (l: Lane) => l.state === 'running' || l.state === 'waiting'
  const running = lanes.filter(isRunning)
  const finished = lanes
    .filter(l => !isRunning(l) && l.key !== 'main' && l.finishedAt && now - Date.parse(l.finishedAt) < FINISHED_FOR_MS)
    .sort((a, b) => Date.parse(b.finishedAt as string) - Date.parse(a.finishedAt as string))

  // Build the rows first, then size the grid to them.
  type Row = { kind: 'lane' | 'session' | 'finished' | 'note' | 'more'; lane?: Lane; depth?: number; text?: string }
  const rows: Row[] = []
  const sessions = [...new Set(running.map(l => l.session))].sort((a, b) => {
    const ao = running.some(l => l.session === a && l.own), bo = running.some(l => l.session === b && l.own)
    return ao === bo ? a.localeCompare(b) : ao ? -1 : 1
  })
  for (const sess of sessions) {
    const mine = running.filter(l => l.session === sess)
    if (sessions.length > 1) rows.push({ kind: 'session', text: mine[0].own ? 'this session' : `session ${sess}` })
    const byId = new Map(mine.filter(l => l.agentId).map(l => [l.agentId as string, l]))
    const main = mine.find(l => l.key === 'main') ?? null
    const walk = (l: Lane, depth: number) => {
      rows.push({ kind: 'lane', lane: l, depth })
      mine
        .filter(c => c !== l && c.key !== 'main' && (l.key === 'main' ? !c.parentAgentId || !byId.has(c.parentAgentId) : c.parentAgentId === l.agentId))
        .forEach(c => walk(c, depth + 1))
    }
    if (main) walk(main, 0)
    else {
      mine.filter(c => c.key !== 'main' && (!c.parentAgentId || !byId.has(c.parentAgentId))).forEach(c => walk(c, 0))
    }
  }
  if (!running.length) rows.push({ kind: 'note', text: 'Nothing running right now.' })
  if (finished.length) {
    rows.push({ kind: 'session', text: 'just finished' })
    finished.slice(0, 4).forEach(l => rows.push({ kind: 'finished', lane: l }))
  }
  let shown = rows
  if (rows.length > LIVE_MAX_ROWS) {
    shown = rows.slice(0, LIVE_MAX_ROWS - 1)
    shown.push({ kind: 'more', text: `+${rows.length - shown.length} more on the dashboard (/agent-org web)` })
  }

  const g = grid(w, shown.length + 1)
  const nSess = new Set(running.map(l => l.session)).size
  rule(
    g,
    0,
    'LIVE AGENTS',
    running.length ? `${running.length} running${nSess > 1 ? ` in ${nSess} sessions` : ''}` : 'idle',
    running.length ? C.bronze : C.muted,
  )
  const RIGHT = 10 + 1 + SPARK_CELLS + 1 + 6 // tool, spark, time
  shown.forEach((r, i) => {
    const y = i + 1
    if (r.kind === 'session') {
      put(g, 0, y, '╶ ' + (r.text ?? ''), C.dim)
      return
    }
    if (r.kind === 'note' || r.kind === 'more') {
      put(g, 0, y, r.text ?? '', C.dim)
      return
    }
    const l = r.lane as Lane
    if (r.kind === 'finished') {
      const dur = l.finishedAt ? Date.parse(l.finishedAt) - Date.parse(l.startedAt) : 0
      const right = `${l.toolCalls} calls ${elapsed(dur)}`
      put(g, 0, y, '✓', C.ok)
      const nm = laneName(l)
      put(g, 2, y, nm, C.muted)
      const dw = Math.max(0, w - 2 - nm.length - 1 - right.length - 2)
      if (l.description && dw > 3) put(g, 3 + nm.length, y, fitText(`"${l.description}"`, dw), C.dim)
      put(g, w - right.length, y, right, C.dim)
      return
    }
    const depth = r.depth ?? 0
    const ind = depth > 0 ? '  '.repeat(depth - 1) + '└' : ''
    const hot = pulse ? C.bronze : C.bronzeDim
    put(g, 0, y, ind, C.rule)
    const mx = ind.length
    put(g, mx, y, '●', hot)
    const leftW = w - RIGHT - 1
    const badge = l.tierNote && l.tier ? ` [${l.tier}]` : ''
    const nm = fitText(laneName(l) + badge, leftW - mx - 2)
    put(g, mx + 2, y, nm, C.bronze)
    if (badge && nm.endsWith(badge)) put(g, mx + 2 + nm.length - badge.length, y, badge, l.tierNote === 'below your model' ? C.muted : C.ask)
    const dx = mx + 3 + nm.length
    if (l.key !== 'main' && l.description && leftW - dx > 3) put(g, dx, y, fitText(`"${l.description}"`, leftW - dx), C.muted)
    const rx = w - RIGHT
    const tool = l.state === 'waiting' ? '…waiting' : l.currentTool ? '›' + l.currentTool : l.lastTool ?? ''
    put(g, rx, y, fitText(tool, 10), l.currentTool ? C.bronze : C.dim)
    spark(g, rx + 11, y, l.callTimes, now, C.graph)
    const t0 = Date.parse(l.startedAt)
    let tm = elapsed(now - t0)
    let tfg: number = C.muted
    if (l.limitMin) {
      tm = `${Math.floor((now - t0) / 60000)}/${l.limitMin}m`
      if (now - t0 > l.limitMin * 60000 * 0.8) tfg = C.ask
    }
    put(g, w - tm.length, y, tm, tfg)
  })
  return g
}

function fitText(s: string, n: number) {
  if (n <= 0) return ''
  return s.length > n ? s.slice(0, Math.max(0, n - 1)) + '…' : s
}
