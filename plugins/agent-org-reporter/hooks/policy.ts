// Agent Org — the spawn rules (design draft section 3, "hard rules in the spawn hook").
// PURE: no `$`, no files, no clock of its own. register.ts calls decideSpawn()
// BEFORE a spawn runs and refuses with the reason it returns. The data comes from
// shared.ts (loaded by pane.tsx from roster.json / approvals.json).
//
// Zeus is a subagent; it may start only roster seats and approved,
// in-budget specialists — never general-purpose, a fork, or another Zeus. Specialists
// get read-only + web tools at most, start only with the user's approval, run once, and
// cannot start anything. Enforced now (no shadow): these rules touch only spawns made
// BY Zeus or a specialist, plus any start of a specialist type.

export const PLUGIN = 'agent-org-reporter'
export const SPEC_PREFIX = `${PLUGIN}:spec-`

export type RosterSeat = {
  id: string
  name: string
  role: string
  reportsTo: string
  kind: 'chief' | 'seat' | 'independent' | 'standing-specialist'
  agentType: string
  canSpawn: boolean
}

export type SpecialistPolicy = {
  toolCeiling: string[]
  maxMinutes: number
  maxActive: number
  spawnedBy: string[]
  refuseTypes: string[]
}

export type Roster = { seats: RosterSeat[]; specialistPolicy: SpecialistPolicy }

export type Approval = {
  id: string
  slug: string
  agentType: string // `${PLUGIN}:spec-${slug}`
  status: 'approved' | 'declined' | 'started' | 'retired'
  decidedAt: string
  decidedVia: 'pane' | 'command'
  startBy: string // ISO; an approval not used by then lapses
  maxMinutes: number
  tools: string[]
  startedAt?: string
  retiredAt?: string
}

export type OrgData = {
  roster: Roster | null
  approvals: Record<string, Approval>
  loadedAt: number
}

export function isSpecialistType(t: string | null | undefined) {
  return typeof t === 'string' && t.startsWith(SPEC_PREFIX)
}

export function chiefType(roster: Roster | null) {
  return roster?.seats.find(s => s.kind === 'chief')?.agentType ?? 'zeus'
}

export function approvalForType(org: OrgData, agentType: string) {
  return Object.values(org.approvals).find(a => a.agentType === agentType) ?? null
}

export type SpawnFacts = {
  subagentType: string
  fork: boolean
  parentAgentId: string | null
  parentType: string | null // null when the parent is main, or unknown
  parentKnown: boolean // false: a nested spawn whose parent the reporter never saw
  activeSpecialists: number
  nowMs: number
  alreadyUsed?: boolean // A1: this process has already started this specialist type
}

// Returns the refusal text, or null to allow. The text is what the spawning agent
// reads as the Agent tool's error, so it says what to do instead.
export function decideSpawn(f: SpawnFacts, org: OrgData | null): string | null {
  const chief = chiefType(org?.roster ?? null)

  // 1. A specialist type may start only on a live approval — from anywhere.
  if (isSpecialistType(f.subagentType)) {
    if (!org) return 'Agent Org: approvals are still loading. Try again in a few seconds.'
    const a = approvalForType(org, f.subagentType)
    if (!a || a.status === 'declined') {
      return `Agent Org: ${f.subagentType} has no approval from the user. Propose it with propose_specialist and wait for approval.`
    }
    if (f.alreadyUsed || a.status === 'started' || a.status === 'retired') {
      return `Agent Org: ${f.subagentType} is single-use and has already run. Propose a new specialist if the task needs more work.`
    }
    if (Date.parse(a.startBy) < f.nowMs) {
      return `Agent Org: the approval for ${f.subagentType} lapsed at ${a.startBy}. Propose it again.`
    }
    const max = org.roster?.specialistPolicy.maxActive ?? 10 // default: up to 10 active
    if (f.activeSpecialists >= max) {
      return `Agent Org: ${f.activeSpecialists} specialists are already running (limit ${max}). Wait for one to finish.`
    }
  }

  // 2. Nested spawn whose parent the reporter never saw: we cannot tell whether
  //    it is Zeus or a specialist, so refuse rather than guess.
  if (f.parentAgentId && !f.parentKnown) {
    return 'Agent Org: this agent is not known to the org reporter, so it cannot start other agents. Ask the main conversation to start it.'
  }

  // 3. Specialists start nothing.
  if (isSpecialistType(f.parentType)) {
    return 'Agent Org: specialists cannot start other agents. Report back to Zeus with what you need.'
  }

  // 4. Zeus starts only roster seats and approved specialists.
  if (f.parentType === chief) {
    if (f.fork) return 'Agent Org: Zeus cannot fork itself. Delegate to a roster seat or propose a specialist.'
    const refuse = org?.roster?.specialistPolicy.refuseTypes ?? ['general-purpose', 'fork', chief]
    if (refuse.includes(f.subagentType) || f.subagentType === chief) {
      return `Agent Org: Zeus may not start ${f.subagentType}. Use a roster seat, or propose a specialist with propose_specialist.`
    }
    if (isSpecialistType(f.subagentType)) return null // approval checked in rule 1
    if (!org?.roster) return 'Agent Org: the roster is still loading. Try again in a few seconds.'
    const seat = org.roster.seats.find(s => s.agentType === f.subagentType)
    if (!seat) {
      return `Agent Org: ${f.subagentType} is not on the roster. Use a roster seat, or propose a specialist with propose_specialist.`
    }
    if (seat.kind === 'independent' || seat.kind === 'chief') {
      return `Agent Org: ${seat.name} sits outside Zeus's chain of command. Hand this back to the user.`
    }
    return null
  }

  // 5. Everything else (the main conversation, seats) is not governed here.
  return null
}

// Validates a specialist proposal against the policy. Returns the problems found.
export function checkProposal(p: { slug: string; tools: string[]; maxMinutes: number }, policy: SpecialistPolicy) {
  const problems: string[] = []
  if (!/^[a-z0-9][a-z0-9-]{2,39}$/.test(p.slug)) problems.push('slug must be 3-40 of a-z, 0-9 and -')
  const over = p.tools.filter(t => !policy.toolCeiling.includes(t))
  if (over.length) problems.push(`tools above the ceiling: ${over.join(', ')} (allowed: ${policy.toolCeiling.join(', ')})`)
  if (!p.tools.length) problems.push('ask for at least one tool')
  if (!(p.maxMinutes >= 1 && p.maxMinutes <= policy.maxMinutes)) problems.push(`maxMinutes must be 1-${policy.maxMinutes}`)
  return problems
}
