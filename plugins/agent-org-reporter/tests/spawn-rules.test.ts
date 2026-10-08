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
function machine(on: any) {
  const files = new Map<string, string>([
    [`${VAULT}/scripts/load-rules.py`, '# marker'],
    [`${VAULT}/state/agent-org/roster.json`, JSON.stringify(ROSTER)],
  ])
  const dirs = new Set([VAULT, `${VAULT}/.claude`, `${VAULT}/scripts`, `${VAULT}/state`, `${VAULT}/state/agent-org`])
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
  on('fs.list', async () => ({ value: [] }))
  on('session.id', async () => ({ value: 'test-session' }))
  on('session.start', async (_$: any, e: any) => ({ cwd: e.cwd ?? VAULT }))
  on('agent.spawn', async () => ({ model: 'test-model', agentId: `agent-${++started}` }))
  on('command.run', async () => ({ text: 'core ran the command' }))
  return { files, clock }
}

const spawn = (subagentType: string, parentAgentId?: string) => ({
  tool_use_id: `tu-${subagentType}-${Math.random().toString(36).slice(2, 8)}`,
  prompt: 'test task',
  description: `test ${subagentType}`,
  subagentType,
  provider: { plugin: 'engine', tier: 'core' },
  fork: false,
  background: false,
  ...(parentAgentId ? { parentAgentId } : {}),
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
    const r = await $.command.run(run('approve 2026-10-08-missing', { kind: 'composer' }))
    expect(r.text).toMatch(/No specialist proposal/)
  })
})
