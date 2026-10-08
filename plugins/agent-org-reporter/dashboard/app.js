// Agent Org dashboard — client.
// SECURITY: every value from /api/state is untrusted data (agent descriptions, deny
// reasons and gate reasons can quote anything an agent saw). It is placed with
// textContent / setAttribute only — never innerHTML, never as a URL. No eval, no
// inline handlers (the server's CSP forbids them anyway).
'use strict'

const POLL_VISIBLE_MS = 2000
const POLL_HIDDEN_MS = 15000
const SVGNS = 'http://www.w3.org/2000/svg'
// The harness's own seats. Cerberus is drawn apart: it reports to the user directly,
// not through the chain it checks (design draft section 1).
const INDEPENDENT = new Set(['cerberus'])
const AGENT_ROWS = 8

let lastTopTs = ''
let skySignature = ''
const expanded = new Set()
let data = null

const $ = id => document.getElementById(id)

function el(tag, cls, text) {
  const n = document.createElement(tag)
  if (cls) n.className = cls
  if (text !== undefined && text !== null) n.textContent = String(text)
  return n
}

function svg(tag, attrs) {
  const n = document.createElementNS(SVGNS, tag)
  for (const k in attrs || {}) n.setAttribute(k, String(attrs[k]))
  return n
}

function clear(node) { while (node.firstChild) node.removeChild(node.firstChild) }

function fmtNum(n) {
  n = Number(n) || 0
  if (n >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, '') + 'M'
  if (n >= 1e4) return Math.round(n / 1e3) + 'k'
  if (n >= 1e3) return (n / 1e3).toFixed(1).replace(/\.0$/, '') + 'k'
  return String(n)
}

function time(ts) {
  const d = new Date(ts)
  return isNaN(d) ? '' : d.toLocaleTimeString('en-AU', { hour12: false })
}

function ago(ts) {
  const s = Math.max(0, (Date.now() - new Date(ts).getTime()) / 1000)
  if (!isFinite(s)) return ''
  if (s < 45) return 'just now'
  if (s < 3600) return Math.round(s / 60) + ' min ago'
  if (s < 86400) return Math.round(s / 3600) + ' h ago'
  return Math.round(s / 86400) + ' d ago'
}

function secs(ms) {
  if (typeof ms !== 'number') return ''
  return ms < 1000 ? ms + ' ms' : ms < 120000 ? (ms / 1000).toFixed(1) + ' s' : Math.round(ms / 60000) + ' min'
}

// Pantheon seats read as names (Athena); hyphenated tool-like ids stay as written.
function display(name) {
  if (name.startsWith('agent-org-reporter:spec-')) return 'spec:' + name.slice(24)
  return /-/.test(name) ? name : name.charAt(0).toUpperCase() + name.slice(1)
}

function localMidnight() { const d = new Date(); d.setHours(0, 0, 0, 0); return d }

// ------------------------------------------------------------ header ---

function setLink(state, text) {
  const link = $('link')
  link.dataset.state = state
  $('link-text').textContent = text
}

function renderKpis(d) {
  const t = d.totals || {}
  const g = (d.gates && d.gates.counts) || {}
  $('k-running').textContent = fmtNum(t.runningAgents)
  $('k-calls').textContent = fmtNum(t.toolCalls)
  $('k-spawned').textContent = fmtNum(t.spawned)
  $('k-tokens').textContent = fmtNum(t.tokensOut)
  $('k-gates').textContent = fmtNum((g.ask || 0) + (g.deny || 0))
}

// ------------------------------------------------------ constellation ---

function seatActivity(d) {
  const midnight = localMidnight()
  const run = new Map()
  const today = new Map()
  for (const s of d.sessions || []) {
    for (const a of s.agents || []) {
      if (a.key === 'main') continue
      const type = String(a.type || 'subagent').toLowerCase()
      if (s.live && (a.state === 'running' || a.state === 'waiting')) run.set(type, (run.get(type) || 0) + 1)
      if (a.startedAt && new Date(a.startedAt) >= midnight) today.set(type, (today.get(type) || 0) + 1)
    }
  }
  return { run, today }
}

function renderSky(d) {
  const seats = (d.seats || []).map(s => String(s.name).toLowerCase())
  const { run, today } = seatActivity(d)
  const specialists = [...new Set([...today.keys(), ...run.keys()])].filter(t => !seats.includes(t)).sort()
  const sig = JSON.stringify([seats, specialists, [...run], [...today]])
  if (sig === skySignature) return
  skySignature = sig

  const root = $('sky')
  // keep <title>/<desc>, rebuild the drawing
  ;[...root.childNodes].forEach(n => { if (n.nodeName !== 'title' && n.nodeName !== 'desc') root.removeChild(n) })

  const R1 = 140, R2 = 205
  root.appendChild(svg('circle', { class: 'ring', cx: 0, cy: 0, r: R1 }))
  if (specialists.length) root.appendChild(svg('circle', { class: 'ring', cx: 0, cy: 0, r: R2 }))

  const edges = svg('g', {}), nodes = svg('g', {})
  root.appendChild(edges); root.appendChild(nodes)

  function place(name, angle, r, small, label) {
    const x = Math.cos(angle) * r, y = Math.sin(angle) * r
    const cls = ['seat']
    const nRun = run.get(name) || 0, nToday = today.get(name) || 0
    if (nRun) cls.push('run'); else if (nToday) cls.push('today')
    if (INDEPENDENT.has(name)) cls.push('ind')
    const ecls = ['edge']
    if (nRun) ecls.push('run'); else if (nToday) ecls.push('today')
    if (INDEPENDENT.has(name)) ecls.push('ind')
    edges.appendChild(svg('line', { class: ecls.join(' '), x1: 0, y1: 0, x2: x, y2: y }))

    const g = svg('g', { class: cls.join(' ') })
    const t = svg('title', {})
    t.textContent = label + (nRun ? `: ${nRun} running` : nToday ? `: ${nToday} today` : ': idle')
    g.appendChild(t)
    const rad = small ? 6 : 9
    g.appendChild(svg('circle', { class: 'halo', cx: x, cy: y, r: rad * 2 }))
    g.appendChild(svg('circle', { class: 'node', cx: x, cy: y, r: rad }))
    const out = r + (small ? 14 : 18)
    const lx = Math.cos(angle) * out, ly = Math.sin(angle) * out
    const anchor = Math.abs(Math.cos(angle)) < 0.25 ? 'middle' : Math.cos(angle) > 0 ? 'start' : 'end'
    const dy = Math.sin(angle) > 0.6 ? 10 : Math.sin(angle) < -0.6 ? -4 : 4
    const name1 = svg('text', { class: 'name', x: lx, y: ly + dy, 'text-anchor': anchor })
    name1.textContent = label
    g.appendChild(name1)
    if (nRun || nToday) {
      const meta = svg('text', { class: 'meta', x: lx, y: ly + dy + 14, 'text-anchor': anchor })
      meta.textContent = nRun ? `${nRun} running` : `${nToday} today`
      g.appendChild(meta)
    }
    nodes.appendChild(g)
  }

  const step = (2 * Math.PI) / Math.max(1, seats.length)
  seats.forEach((name, i) => place(name, -Math.PI / 2 + i * step, R1, false, display(name)))
  // Specialists sit in the GAPS between seats (half a step round), so their
  // spokes and labels never cross a seat's. Fill the gaps nearest the bottom first.
  const gaps = seats.map((_, i) => -Math.PI / 2 + (i + 0.5) * step)
    .sort((a, b) => Math.abs(Math.sin(a) - 1) - Math.abs(Math.sin(b) - 1))
  specialists.forEach((name, i) => {
    const a = gaps.length ? gaps[i % gaps.length] + Math.floor(i / gaps.length) * step * 0.25 : Math.PI / 2
    place(name, a, R2, true, display(name))
  })

  const you = svg('g', {})
  you.appendChild(svg('circle', { class: 'you', cx: 0, cy: 0, r: 24 }))
  const yl = svg('text', { class: 'you-label', x: 0, y: 5, 'text-anchor': 'middle' })
  yl.textContent = 'You'
  you.appendChild(yl)
  nodes.appendChild(you)
}

// ---------------------------------------------------------------- feed ---

function feedRow(e) {
  const li = el('li')
  const who = el('span', 'who' + (e.agentId ? ' sub' : ''), e.agent || 'main')
  who.title = 'Session ' + (e.session || '')
  let what = '', out = '', outCls = ''
  if (e.kind === 'tool.call') {
    what = e.tool || 'tool'
    if (e.denied) { out = 'blocked'; outCls = 'blocked' }
    else if (e.isError) { out = 'error'; outCls = 'err' }
    else { out = 'ok'; outCls = 'ok' }
  } else if (e.kind === 'agent.spawn') {
    li.classList.add('k-spawn')
    what = 'started' + (e.description ? ': ' + e.description : '')
    out = e.denied ? 'refused' : 'start'
    outCls = e.denied ? 'blocked' : 'start'
  } else if (e.kind === 'turn.complete') {
    li.classList.add('k-done')
    const done = e.agentId ? 'finished' : 'answered'
    what = e.reason === 'answer' ? `${done} in ${secs(e.durationMs)}` : `stopped (${e.reason || 'unknown'})`
    out = e.reason === 'answer' ? 'done' : (e.reason || '')
    outCls = e.reason === 'answer' ? 'ok' : 'err'
  } else if (e.kind === 'session.start') {
    what = 'session started'; out = 'start'; outCls = 'start'
  } else if (e.kind === 'session.end') {
    what = 'session ended'
  } else {
    what = e.kind || ''
  }
  const w = el('span', 'what', what)
  if (e.deny) w.title = 'Blocked by: ' + e.deny
  li.append(el('span', 't', time(e.ts)), who, w, el('span', 'out ' + outCls, out))
  return li
}

function renderFeed(d) {
  const list = $('feed')
  const onlyAgents = $('only-agents').checked
  const rows = (d.feed || []).filter(e => !onlyAgents || e.agentId || e.kind === 'agent.spawn')
  const atTop = list.scrollTop < 8
  const prevTop = lastTopTs
  clear(list)
  rows.forEach(e => {
    const li = feedRow(e)
    if (prevTop && e.ts > prevTop) li.classList.add('fresh')
    list.appendChild(li)
  })
  if (rows.length) lastTopTs = rows[0].ts > lastTopTs ? rows[0].ts : lastTopTs
  if (atTop) list.scrollTop = 0
  $('feed-empty').hidden = rows.length > 0
  setTimeout(() => list.querySelectorAll('li.fresh').forEach(n => n.classList.remove('fresh')), 1600)
}

// ------------------------------------------------------------ sessions ---

function renderSpark(d) {
  const s = $('spark')
  clear(s)
  const h = d.hourly || []
  const max = Math.max(1, ...h)
  const w = 240 / Math.max(1, h.length)
  h.forEach((v, i) => {
    const bh = v ? Math.max(2, (v / max) * 34) : 0
    if (!bh) return
    s.appendChild(svg('rect', { class: i === h.length - 1 ? 'now' : '', x: i * w + 1, y: 36 - bh, width: w - 2, height: bh, rx: 1 }))
  })
  const total = h.reduce((a, b) => a + b, 0)
  $('spark-cap').textContent = `Tool calls per hour, last 24 hours (${total} in all)`
}

function stateLabel(a) {
  if (a.key === 'main' && a.state === 'idle') return 'waiting for you'
  return a.state
}

function renderSessions(d) {
  const box = $('sessions')
  clear(box)
  const list = d.sessions || []
  if (!list.length) {
    box.appendChild(el('p', 'empty', 'No sessions in the last 24 hours. Agents appear here as soon as a Claude Code session starts.'))
    return
  }
  for (const s of list) {
    const wrap = el('div', 'sess')
    const head = el('div', 'sess-head')
    head.append(el('strong', '', 'Session ' + s.short))
    head.append(el('span', 'state' + (s.live ? ' live' : ''), s.live ? '● live' : s.ended ? 'ended' : 'quiet, last active ' + ago(s.lastActivity)))
    const subs = s.agents.filter(a => a.key !== 'main').length
    head.append(el('span', 'state', `${subs} subagent${subs === 1 ? '' : 's'}`))
    wrap.appendChild(head)

    const table = el('table', 'agents')
    const thead = el('thead'), tr = el('tr')
    ;[['Agent', ''], ['State', ''], ['Calls', 'num'], ['Tokens out', 'num hide-sm'], ['Last active', 'hide-sm']].forEach(([t, c]) => {
      const th = el('th', c, t); th.scope = 'col'; tr.appendChild(th)
    })
    thead.appendChild(tr); table.appendChild(thead)
    const tb = el('tbody')
    const showAll = expanded.has(s.id)
    const agents = showAll ? s.agents : s.agents.slice(0, AGENT_ROWS)
    for (const a of agents) {
      const r = el('tr')
      const name = el('td')
      name.append(el('span', '', a.key === 'main' ? 'Main conversation' : laneName(a)))
      if (a.key !== 'main' && a.description) name.append(el('span', 'desc', a.description))
      const st = el('td')
      st.append(el('span', 'pill ' + a.state, stateLabel(a)))
      const calls = el('td', 'num', a.toolCalls + (a.toolErrors ? ` (${a.toolErrors} err)` : ''))
      r.append(name, st, calls, el('td', 'num hide-sm', fmtNum(a.tokensOut)), el('td', 'hide-sm', ago(a.lastActivity)))
      tb.appendChild(r)
    }
    table.appendChild(tb)
    wrap.appendChild(table)
    if (s.agents.length > AGENT_ROWS) {
      const more = el('p', 'more')
      const b = el('button', '', showAll ? 'Show fewer' : `Show all ${s.agents.length} agents`)
      b.type = 'button'
      b.addEventListener('click', () => { showAll ? expanded.delete(s.id) : expanded.add(s.id); renderSessions(data) })
      more.appendChild(b)
      wrap.appendChild(more)
    }
    box.appendChild(wrap)
  }
}

// --------------------------------------------------------------- gates ---

function renderGates(d) {
  const g = d.gates || { counts: {}, byHook: [], notable: [] }
  const c = g.counts || {}
  const total = (c.allow || 0) + (c.observe || 0) + (c.ask || 0) + (c.deny || 0)
  const bar = $('gate-bar')
  clear(bar)
  ;[['allow', 'g-allow'], ['observe', 'g-observe'], ['ask', 'g-ask'], ['deny', 'g-deny']].forEach(([k, cls]) => {
    if (!c[k]) return
    const s = el('span', cls)
    s.style.width = (100 * c[k] / Math.max(1, total)) + '%'
    bar.appendChild(s)
  })
  bar.setAttribute('aria-label', `${c.allow || 0} allowed, ${c.observe || 0} watched, ${c.ask || 0} asked, ${c.deny || 0} blocked`)
  $('gates-sub').textContent = total
    ? `${total} verdicts. Watched means logged only, for rules still in shadow.` + (g.fellOpen ? ` ${g.fellOpen} fell open (the hook couldn't decide).` : '')
    : 'No gate verdicts yet today.'

  const rows = $('gate-rows')
  clear(rows)
  for (const h of g.byHook || []) {
    const r = el('tr')
    r.append(el('td', '', h.hook), el('td', '', h.allow), el('td', '', h.observe),
      el('td', h.ask ? 'hot-ask' : '', h.ask), el('td', h.deny ? 'hot-deny' : '', h.deny))
    rows.appendChild(r)
  }
  const nl = $('gate-notable')
  clear(nl)
  if (!(g.notable || []).length) nl.appendChild(el('li', 'r', 'None today.'))
  for (const n of (g.notable || []).slice(0, 8)) {
    const li = el('li')
    const vcls = n.verdict === 'ask' ? 'ask' : n.verdict === 'deny' ? 'deny' : 'fell'
    const label = n.verdict === 'ask' ? 'Asked' : n.verdict === 'deny' ? 'Blocked' : 'Fell open'
    li.append(el('span', 'v ' + vcls, label), el('span', '', `${n.hook}, ${n.rule || ''}`), el('span', 't', ' ' + time(n.ts)))
    if (n.reason) li.append(el('span', 'r', n.reason))
    nl.appendChild(li)
  }
}

// ------------------------------------------------------------- waiting ---

// A2 (security review): pending specialists with Zeus's FULL brief, so the user
// approves on what the specialist will actually be told. Read-only: approving
// happens in the Claude Code pane or by typing /agent-org approve <id>.
function renderSpecs(d) {
  const box = $('specs')
  clear(box)
  const list = (d.specialists || []).filter(s => s.status === 'pending')
  const recent = (d.specialists || []).filter(s => s.status !== 'pending').slice(0, 3)
  for (const s of list) {
    const card = el('div', 'spec')
    card.append(el('h3', '', 'Approval needed: ' + (s.title || s.id)))
    card.append(el('p', 'meta', `${(s.tools || []).join(', ')}, up to ${s.maxMinutes ?? '?'} min. Proposed by ${s.proposedBy || 'zeus'} ${s.proposedAt ? ago(s.proposedAt) : ''}. ${s.id}`))
    card.append(el('p', 'meta size', `Size: ${s.model && s.model !== 'inherit' ? s.model : 'your model'}`))
    if (s.model && s.model !== 'inherit' && s.modelReason) card.append(el('p', 'meta', "Zeus's reason (unverified): " + s.modelReason))
    if (s.purpose) card.append(el('p', 'meta', s.purpose))
    if (s.task) card.append(el('p', 'task', 'Task: ' + s.task))
    const det = document.createElement('details')
    det.open = true
    det.append(el('summary', '', "Zeus's full brief (becomes the specialist's instructions)"), el('pre', '', s.brief || '(empty)'))
    card.append(det)
    card.append(el('p', 'how', `Approve in the Claude Code pane: press Approve, or type /agent-org approve ${s.id} <code>, with the 8-character code shown on the pane's card.`))
    box.appendChild(card)
  }
  for (const s of recent) {
    const card = el('div', 'spec decided')
    card.append(el('p', 'meta', `${s.title || s.id}: ${s.status}${s.decidedVia ? ' (via ' + s.decidedVia + ')' : ''}`))
    box.appendChild(card)
  }
}

function renderWaiting(d) {
  renderSpecs(d)
  const b = d.backlog || {}
  const q = $('queue')
  clear(q)
  if (!b.reviewQueue) {
    q.appendChild(el('p', 'empty', 'The self-healing review queue is not set up on this computer.'))
  } else {
    const line = el('div', 'queue-line')
    line.append(el('span', 'big' + (b.reviewQueue.depth ? '' : ' calm'), b.reviewQueue.depth))
    line.append(el('p', '', b.reviewQueue.depth
      ? `harness failures waiting for review, oldest ${b.reviewQueue.oldestDays} days. Run /harness-review --drain to work through them.`
      : 'harness failures waiting. The review queue is clear.'))
    q.appendChild(line)
    if ((b.reviewQueue.byAutomation || []).length) {
      const ul = el('ul', 'queue-by')
      for (const a of b.reviewQueue.byAutomation) {
        const li = el('li')
        li.append(el('span', '', a.name), el('b', '', a.count))
        ul.appendChild(li)
      }
      q.appendChild(ul)
    }
  }
  const c = $('commit')
  clear(c)
  if (!b.commitments) { c.appendChild(el('li', 'w', 'No commitments register on this computer.')); return }
  if (!b.commitments.top.length) { c.appendChild(el('li', 'w', `Nothing overdue. ${b.commitments.open} open.`)); return }
  for (const x of b.commitments.top) {
    const li = el('li')
    li.append(el('span', 'due', 'due ' + (x.due || '')), el('span', 'id', x.id), el('span', 'w', x.what))
    c.appendChild(li)
  }
  if (b.commitments.overdue > b.commitments.top.length) {
    c.appendChild(el('li', 'w', `${b.commitments.overdue - b.commitments.top.length} more overdue. Run python scripts/commitments.py --due to see them all.`))
  }
}

// --------------------------------------------------------- live agents ---
// One lane per running agent across every session, children
// under their parent, then agents that finished in the last two minutes.

const STALE_RUNNING_MS = 10 * 60 * 1000
const FINISHED_FOR_MS = 2 * 60 * 1000

function laneName(a) {
  if (a.key === 'main') return 'Main chat'
  const t = String(a.type || 'agent')
  return t.startsWith('agent-org-reporter:spec-') ? 'spec:' + t.slice(24) : t
}

function laneSpark(times) {
  const s = svg('svg', { viewBox: '0 0 120 22', preserveAspectRatio: 'none', 'aria-hidden': 'true' })
  const n = 16, now = Date.now(), counts = new Array(n).fill(0)
  for (const t of times || []) {
    const b = Math.floor((now - t) / 2000)
    if (b >= 0 && b < n) counts[n - 1 - b] += 1
  }
  const max = Math.max(1, ...counts), w = 120 / n
  counts.forEach((c, i) => {
    if (!c) return
    const h = Math.max(3, (c / max) * 20)
    s.appendChild(svg('rect', { x: i * w + 1, y: 22 - h, width: w - 2, height: h, rx: 1 }))
  })
  return s
}

function laneRow(a, depth, finished) {
  const li = el('li', 'lane' + (finished ? ' finished' : ''))
  const who = el('div', 'who')
  if (depth > 0) who.append(el('span', 'tree', '  '.repeat(depth - 1) + '└'))
  if (finished) who.append(el('span', 'out ok', '✓'))
  else who.append(el('span', 'dot'))
  who.append(el('span', 'name', laneName(a)))
  // size badge only when it differs from the user's model (design 2026-10-08)
  if (a.tier && a.tierNote) {
    const b = el('span', 'tier' + (a.tierNote === 'below your model' ? '' : ' above'), a.tier)
    b.title = a.tierNote
    who.append(b)
  }
  if (a.key !== 'main' && a.description) who.append(el('span', 'desc', '“' + a.description + '”'))
  const tool = el('span', 'tool' + (a.currentTool ? ' now' : ''), a.state === 'waiting' ? '… waiting on its agents' : a.currentTool ? '› ' + a.currentTool : (a.lastTool || ''))
  let timeText
  const t0 = new Date(a.startedAt).getTime()
  if (finished) {
    timeText = secs(new Date(a.finishedAt).getTime() - t0)
  } else {
    const ms = Date.now() - t0
    timeText = ms < 60000 ? Math.round(ms / 1000) + 's' : ms < 3600000 ? Math.floor(ms / 60000) + 'm' : (ms / 3600000).toFixed(1) + 'h'
  }
  const time = el('span', 'time', finished ? `${a.toolCalls} calls, ${timeText}` : timeText)
  li.append(who, tool, laneSpark(a.callTimes), time)
  return li
}

function renderLive(d) {
  const list = $('lanes')
  clear(list)
  const now = Date.now()
  const sessions = (d.sessions || []).filter(s => s.live)
  let running = 0, sessCount = 0
  const finishedAll = []
  for (const s of sessions) {
    const alive = s.agents.filter(a => (a.state === 'running' || a.state === 'waiting') && now - new Date(a.lastActivity).getTime() < STALE_RUNNING_MS)
    for (const a of s.agents) {
      if (a.key !== 'main' && a.state !== 'running' && a.state !== 'waiting' && a.finishedAt && now - new Date(a.finishedAt).getTime() < FINISHED_FOR_MS) finishedAll.push(a)
    }
    if (!alive.length) continue
    sessCount += 1
    running += alive.length
    if (sessions.length > 1) list.appendChild(el('li', 'lane sess', 'Session ' + s.short))
    const ids = new Set(alive.filter(a => a.agentId).map(a => a.agentId))
    const main = alive.find(a => a.key === 'main')
    const walk = (a, depth) => {
      list.appendChild(laneRow(a, depth, false))
      alive.filter(c => c !== a && c.key !== 'main' &&
        (a.key === 'main' ? (!c.parentAgentId || !ids.has(c.parentAgentId)) : c.parentAgentId === a.agentId))
        .forEach(c => walk(c, depth + 1))
    }
    if (main) walk(main, 0)
    else alive.filter(c => !c.parentAgentId || !ids.has(c.parentAgentId)).forEach(c => walk(c, 0))
  }
  if (finishedAll.length) {
    list.appendChild(el('li', 'lane sess', 'Just finished'))
    finishedAll.sort((a, b) => new Date(b.finishedAt) - new Date(a.finishedAt)).slice(0, 5)
      .forEach(a => list.appendChild(laneRow(a, 0, true)))
  }
  $('lanes-empty').hidden = running > 0 || finishedAll.length > 0
  $('live-sub').textContent = running
    ? `${running} running${sessCount > 1 ? ` across ${sessCount} sessions` : ''}, with the tool each one is in right now.`
    : 'Every agent running in any of your Claude Code sessions, with what it is doing right now.'
}

// ---------------------------------------------------------------- loop ---

function renderAll(d) {
  renderKpis(d)
  renderLive(d)
  renderSky(d)
  renderFeed(d)
  renderSpark(d)
  renderSessions(d)
  renderGates(d)
  renderWaiting(d)
}

async function poll() {
  try {
    const r = await fetch('/api/state', { cache: 'no-store' })
    const d = await r.json()
    if (!r.ok || d.error) throw new Error(d.error || 'HTTP ' + r.status)
    data = d
    renderAll(d)
    setLink(d.demo ? 'demo' : 'live', d.demo ? `Demo data: a sample org, not real activity. Updated ${time(d.generated)}` : `Live, updated ${time(d.generated)}`)
  } catch (err) {
    setLink('down', "Can't reach the dashboard server. It stops two minutes after the last tab closes; run /agent-org web in Claude Code to start it again.")
  } finally {
    setTimeout(poll, document.hidden ? POLL_HIDDEN_MS : POLL_VISIBLE_MS)
  }
}

function tickClock() {
  $('clock').textContent = new Date().toLocaleTimeString('en-AU', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

$('only-agents').addEventListener('change', () => { lastTopTs = ''; if (data) renderFeed(data) })
tickClock()
setInterval(tickClock, 1000)
poll()
