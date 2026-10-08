// Agent Org behaviour through real engine events (`claude plugin test .`).
//
// The test's own hooks sit beneath the plugin and stand in for Claude Code and the
// machine: they answer a session start, start an agent, run a command, and serve an
// IN-MEMORY vault for the plugin's file and environment calls. Nothing touches a real
// vault. What the plugin refuses never reaches them.
import { describe, expect, mock, test } from 'claude-code/testing'

const VAULT = '/vault'
const ROSTER = {
  version: 1,
  top: 'user',
  seats: [
    { id: 'zeus', name: 'Zeus', role: 'chief', reportsTo: 'user', kind: 'chief', agentType: 'zeus', canSpawn: true },
    { id: 'athena', name: 'Athena', role: 'seat', reportsTo: 'zeus', kind: 'seat', agentType: 'athena', canSpawn: false },
    { id: 'argus', name: 'Argus', role: 'seat', reportsTo: 'zeus', kind: 'seat', agentType: 'argus', canSpawn: false },
    { id: 'hephaestus', name: 'Hephaestus', role: 'seat', reportsTo: 'zeus', kind: 'seat', agentType: 'hephaestus', canSpawn: false },
    { id: 'cerberus', name: 'Cerberus', role: 'independent', reportsTo: 'user', kind: 'independent', agentType: 'cerberus', canSpawn: false },
  ],
  specialistPolicy: {
    toolCeiling: ['Read', 'Grep', 'Glob', 'WebSearch', 'WebFetch'],
    maxMinutes: 30,
    maxActive: 10,
    spawnedBy: ['zeus'],
    refuseTypes: ['general-purpose', 'fork', 'zeus'],
  },
}

// The engine resolves paths for the host OS (`/vault` arrives as `C:\vault` on
// Windows), so the fake file system compares them in one form.
const norm = (p: string) => p.split(String.fromCharCode(92)).join('/').replace(/^[A-Za-z]:/, '')

// A fresh machine per test: a vault with the harness markers and a roster.
const USER_MODEL = 'claude-opus-5-5'

// Agent files carry the tools the tool-based floor reads: Argus may only read, so it may run
// smaller; Hephaestus can run skills, so it may not.
const agentFile = (tools: string) => `---\nname: x\ntools: ${tools}\n---\nbody`

function machine(on: any, opts: { coreModel?: (e: any) => string; approvals?: Record<string, unknown>; proposals?: Record<string, unknown>[] } = {}) {
  const files = new Map<string, string>([
    [`${VAULT}/scripts/load-rules.py`, '# marker'],
    [`${VAULT}/.claude/agents/argus.md`, agentFile('Read, Grep, Glob')],
    [`${VAULT}/.claude/agents/hephaestus.md`, agentFile('Read, Grep, Glob, Skill')],
    ...(opts.proposals ?? []).map(x => [`${VAULT}/state/agent-org/specialists/${x.id}.json`, JSON.stringify(x)] as [string, string]),
    [`${VAULT}/state/agent-org/roster.json`, JSON.stringify(ROSTER)],
    ...(opts.approvals ? [[`${VAULT}/state/agent-org/approvals.json`, JSON.stringify({ approvals: opts.approvals })] as [string, string]] : []),
  ])
  const dirs = new Set([VAULT, `${VAULT}/.claude`, `${VAULT}/.claude/agents`, `${VAULT}/scripts`, `${VAULT}/state`, `${VAULT}/state/agent-org`, `${VAULT}/state/agent-org/specialists`])
  let started = 0
  mock.env(on, { HARNESS_VAULT_ROOT: VAULT, HOME: '/home/test' })
  const clock = mock.clock(on, { now: Date.parse('2026-10-08T00:00:00Z') })

  on('fs.exists', async (_$: any, e: any) => ({ value: files.has(norm(e.path)) || dirs.has(norm(e.path)) }))
  on('fs.read', async (_$: any, e: any) => {
    if (!files.has(norm(e.path))) throw new Error(`ENOENT ${e.path}`)
    return { value: files.get(norm(e.path)) }
  })
  on('fs.write', async (_$: any, e: any) => {
    files.set(norm(e.path), e.text)
    return { value: undefined }
  })
  on('fs.list', async (_$: any, e: any) => {
    const dir = `${norm(e.path)}/`
    const names = [...files.keys()].filter(k => k.startsWith(dir) && !k.slice(dir.length).includes('/'))
    return { value: names.map(k => ({ name: k.slice(dir.length), kind: 'file' })) }
  })
  on('session.id', async () => ({ value: 'test-session' }))
  on('session.model', async () => ({ value: USER_MODEL }))
  on('session.start', async (_$: any, e: any) => ({ cwd: e.cwd ?? VAULT }))
  // Core runs what it was asked for (or what a test says a misbehaving core runs).
  on('agent.spawn', async (_$: any, e: any) => ({ model: opts.coreModel ? opts.coreModel(e) : (e.model ?? USER_MODEL), agentId: `agent-${++started}` }))
  on('command.run', async () => ({ text: 'core ran the command' }))
  return { files, clock }
}

const spawn = (subagentType: string, parentAgentId?: string, extra: Record<string, unknown> = {}) => ({
  tool_use_id: `tu-${subagentType}-${Math.random().toString(36).slice(2, 8)}`,
  prompt: 'test task',
  description: `test ${subagentType}`,
  subagentType,
  provider: { plugin: 'engine', tier: 'core' },
  fork: false,
  background: false,
  parentModel: USER_MODEL,
  ...(parentAgentId ? { parentAgentId } : {}),
  ...extra,
})

const begin = ($: any) => $.session.start({ cwd: VAULT, isInteractive: false, surface: 'terminal' })

describe('Zeus spawn rules', () => {
  test('Zeus may start a roster seat but not a general-purpose agent', async ($: any, on: any) => {
    machine(on)
    await begin($)
    const zeus = await $.agent.spawn(spawn('zeus'))
    expect(zeus.deny).toBeUndefined()

    const gp = await $.agent.spawn(spawn('general-purpose', zeus.agentId))
    expect(gp.deny).toMatch(/Zeus/)

    const athena = await $.agent.spawn(spawn('athena', zeus.agentId))
    expect(athena.deny).toBeUndefined()
  })

  test('Zeus may not start Cerberus, which sits outside the chain', async ($: any, on: any) => {
    machine(on)
    await begin($)
    const zeus = await $.agent.spawn(spawn('zeus'))
    const cerberus = await $.agent.spawn(spawn('cerberus', zeus.agentId))
    expect(cerberus.deny).toMatch(/outside/)
  })

  test('an unapproved specialist is refused', async ($: any, on: any) => {
    machine(on)
    await begin($)
    const zeus = await $.agent.spawn(spawn('zeus'))
    const spec = await $.agent.spawn(spawn('agent-org-reporter:spec-never-approved', zeus.agentId))
    expect(spec.deny).toMatch(/approv/i)
  })

  test('activity is logged to the vault, never anywhere else', async ($: any, on: any) => {
    const { files, clock } = machine(on)
    await begin($)
    await $.agent.spawn(spawn('zeus'))
    await clock.advance(2500)
    const written = [...files.keys()].filter(p => p.includes('/state/agent-org/audit/') || p.includes('/state/agent-org/status/'))
    for (const p of written) expect(p.startsWith(`${VAULT}/state/agent-org/`)).toBe(true)
  })
})

// A specialist proposal as Zeus files it, and the card hash the pane shows for it
// (same fields, same order as pane.tsx cardHash).
const proposal = (id: string) => ({
  id, slug: 'dpa-check', title: 'DPA check', purpose: 'compare clauses', task: 'read three DPAs',
  tools: ['Read'], maxMinutes: 20, prompt: 'brief', proposedBy: 'zeus', proposedAt: '2026-10-08T00:00:00Z', model: 'inherit', modelReason: '',
})
async function hashOf(p: ReturnType<typeof proposal>) {
  const text = JSON.stringify([p.slug, p.title, p.purpose, p.task, p.prompt, p.tools, p.maxMinutes, p.model ?? 'inherit', p.modelReason ?? ''])
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text))
  return [...new Uint8Array(buf)].map(b => b.toString(16).padStart(2, '0')).join('')
}

describe('approval channel', () => {
  const run = (args: string, origin: unknown) => ({ command: 'agent-org', args, origin, presentation: { layout: 'main', columns: 120 } })

  test('approve sent by anything but the person typing is refused', async ($: any, on: any) => {
    machine(on)
    await begin($)
    for (const origin of [{ kind: 'sdk' }, { kind: 'plugin', name: 'someone-else' }, { kind: 'bridge' }]) {
      const r = await $.command.run(run('approve 2026-10-08-anything', origin))
      expect(r.text).toMatch(/^Refused/)
    }
  })

  test('approve typed by the person reaches the decision (no such proposal here)', async ($: any, on: any) => {
    machine(on)
    await begin($)
    const r = await $.command.run(run('approve 2026-10-08-missing 0123abcd', { kind: 'composer' }))
    expect(r.text).toMatch(/No specialist proposal/)
  })

  test('a typed approve needs the code from the card', async ($: any, on: any) => {
    machine(on, { proposals: [proposal('prop-1')] })
    await begin($)
    const r = await $.command.run(run('approve prop-1', { kind: 'composer' }))
    expect(r.text).toMatch(/approve code/)
  })

  test('a wrong code approves nothing; the right one approves', async ($: any, on: any) => {
    const { files } = machine(on, { proposals: [proposal('prop-1')] })
    await begin($)
    const bad = await $.command.run(run('approve prop-1 00000000', { kind: 'composer' }))
    expect(bad.text).toMatch(/not what the card showed/)
    const code = (await hashOf(proposal('prop-1'))).slice(0, 8)
    const ok = await $.command.run(run(`approve prop-1 ${code}`, { kind: 'composer' }))
    expect(ok.text).not.toMatch(/^Not approved/)
    expect(files.get(`${VAULT}/state/agent-org/approvals.json`) ?? '').toMatch(/"prop-1"/)
  })

  test('a second live approval for the same specialist is refused', async ($: any, on: any) => {
    machine(on, {
      proposals: [proposal('prop-2')],
      approvals: { p1: { id: 'p1', slug: 'dpa-check', agentType: 'agent-org-reporter:spec-dpa-check', status: 'approved',
        decidedAt: '2026-10-08T00:00:00Z', decidedVia: 'pane', startBy: '2099-01-01T00:00:00Z', maxMinutes: 20, tools: ['Read'] } },
    })
    await begin($)
    const code = (await hashOf(proposal('prop-2'))).slice(0, 8)
    const r = await $.command.run(run(`approve prop-2 ${code}`, { kind: 'composer' }))
    expect(r.text).toMatch(/already has a live approval/)
  })
})

describe('model sizes', () => {
  const sized = (type: string, zeusId: string, model: string, why = 'list three files') =>
    spawn(type, zeusId, { model, description: `tier=${model}; why=${why}; tidy` })

  test('Zeus may run a read-only seat smaller, with a reason', async ($: any, on: any) => {
    machine(on)
    await begin($)
    const zeus = await $.agent.spawn(spawn('zeus'))
    const h = await $.agent.spawn(sized('argus', zeus.agentId, 'haiku'))
    expect(h.deny).toBeUndefined()
    expect(h.model).toBe('haiku')
  })

  test('a smaller model without a reason is refused', async ($: any, on: any) => {
    machine(on)
    await begin($)
    const zeus = await $.agent.spawn(spawn('zeus'))
    const h = await $.agent.spawn(spawn('argus', zeus.agentId, { model: 'haiku' }))
    expect(h.deny).toMatch(/reason/)
  })

  test('a seat that can act (Skill) never runs smaller: the tool floor', async ($: any, on: any) => {
    machine(on)
    await begin($)
    const zeus = await $.agent.spawn(spawn('zeus'))
    const h = await $.agent.spawn(sized('hephaestus', zeus.agentId, 'haiku'))
    expect(h.deny).toMatch(/never runs below/)
  })

  test('the main chat is bound too: a roster seat cannot be set smaller from it', async ($: any, on: any) => {
    machine(on)
    await begin($)
    const h = await $.agent.spawn(spawn('hephaestus', undefined, { model: 'haiku' }))
    expect(h.deny).toBeDefined()
  })

  test('a floored seat under a smaller parent runs on the user model', async ($: any, on: any) => {
    machine(on)
    await begin($)
    const zeus = await $.agent.spawn(spawn('zeus'))
    const a = await $.agent.spawn(spawn('athena', zeus.agentId, { parentModel: 'claude-haiku-4-5' }))
    expect(a.deny).toBeUndefined()
    expect(a.model).toBe('opus')
  })

  test('a workflow agent that would need a rewrite is refused', async ($: any, on: any) => {
    const type = 'agent-org-reporter:spec-dpa-check'
    machine(on, { approvals: { 'a1': {
      id: 'a1', slug: 'dpa-check', agentType: type, status: 'approved', decidedAt: '2026-10-08T00:00:00Z',
      decidedVia: 'pane', startBy: '2099-01-01T00:00:00Z', maxMinutes: 20, tools: ['Read'], model: 'sonnet',
    } } })
    await begin($)
    const zeus = await $.agent.spawn(spawn('zeus'))
    const sp = await $.agent.spawn(spawn(type, zeus.agentId, { workflow: true }))
    expect(sp.deny).toMatch(/workflow/)
  })

  test('a built-in started from the main chat runs on the user model, never its own smaller default', async ($: any, on: any) => {
    machine(on)
    await begin($)
    // Explore has no agent file here, so its default and its tools are unknown: pinned (NF-D).
    const x = await $.agent.spawn(spawn('Explore'))
    expect(x.deny).toBeUndefined()
    expect(x.model).toBe('opus')
  })

  test('a floored seat whose own definition says haiku still runs on the user model', async ($: any, on: any) => {
    const { files } = machine(on)
    files.set(`${VAULT}/.claude/agents/hephaestus.md`, ['---', 'name: x', 'model: haiku', 'tools: Read, Grep, Glob, Skill', '---', 'body'].join('\n'))
    await begin($)
    const zeus = await $.agent.spawn(spawn('zeus'))
    const h = await $.agent.spawn(spawn('hephaestus', zeus.agentId))
    expect(h.deny).toBeUndefined()
    expect(h.model).toBe('opus')
  })

  test("another plugin's agent is not judged by the vault's file of the same name", async ($: any, on: any) => {
    machine(on)
    await begin($)
    // argus.md here is read-only; someplugin:argus could have any tools (NF-F).
    const a = await $.agent.spawn(spawn('someplugin:argus', undefined, { model: 'haiku', description: 'tier=haiku; why=list files; x' }))
    expect(a.deny).toMatch(/never runs below/)
  })

  test('a model id nobody can place is flagged when a floor applies', async ($: any, on: any) => {
    const { files, clock } = machine(on, { coreModel: () => 'arn:aws:bedrock:custom-profile' })
    await begin($)
    await $.agent.spawn(spawn('zeus'))
    await clock.advance(2500)
    const log = [...files.entries()].filter(([k]) => k.includes('/audit/')).map(([, v]) => v).join('')
    expect(log).toMatch(/"kind":"tier.violation"/)
  })

  test('a floored seat never runs smaller (Athena)', async ($: any, on: any) => {
    machine(on)
    await begin($)
    const zeus = await $.agent.spawn(spawn('zeus'))
    const a = await $.agent.spawn(sized('athena', zeus.agentId, 'haiku'))
    expect(a.deny).toMatch(/never runs below/)
  })

  test('a full model id is refused, not cleaned up', async ($: any, on: any) => {
    machine(on)
    await begin($)
    const zeus = await $.agent.spawn(spawn('zeus'))
    const h = await $.agent.spawn(spawn('hephaestus', zeus.agentId, { model: 'claude-haiku-4-5' }))
    expect(h.deny).toMatch(/not allowed/)
  })

  test('a specialist runs on the size on its approval card', async ($: any, on: any) => {
    const type = 'agent-org-reporter:spec-dpa-check'
    machine(on, { approvals: { 'a1': {
      id: 'a1', slug: 'dpa-check', agentType: type, status: 'approved', decidedAt: '2026-10-08T00:00:00Z',
      decidedVia: 'pane', startBy: '2099-01-01T00:00:00Z', maxMinutes: 20, tools: ['Read'], model: 'sonnet',
    } } })
    await begin($)
    const zeus = await $.agent.spawn(spawn('zeus'))
    const sp = await $.agent.spawn(spawn(type, zeus.agentId))
    expect(sp.deny).toBeUndefined()
    expect(sp.model).toBe('sonnet') // rewritten from "not set" to the approved size
  })

  test('a core that ignores the floor is caught after the spawn', async ($: any, on: any) => {
    const { files, clock } = machine(on, { coreModel: () => 'claude-haiku-4-5' })
    await begin($)
    const zeus = await $.agent.spawn(spawn('zeus'))
    expect(zeus.deny).toBeUndefined()
    await clock.advance(2500)
    const log = [...files.entries()].filter(([k]) => k.includes('/audit/')).map(([, v]) => v).join('')
    expect(log).toMatch(/"kind":"tier.violation"/)
  })
})

