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
  minTier?: string // optional floor: this seat never runs below this size (can raise, never lower, the code floor)
}

export type SpecialistPolicy = {
  toolCeiling: string[]
  maxMinutes: number
  maxActive: number
  spawnedBy: string[]
  refuseTypes: string[]
  allowedTiers?: string[] // model sizes Zeus may choose; default DEFAULT_ALLOWED_TIERS
  requireTierReason?: boolean // a size other than the user's model needs a stated reason (default true)
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
  model?: string // the size approved on the card ('inherit' when absent)
  cardHash?: string // what the approval was made on: title, purpose, task, brief, model, reason
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

// The same slug can be proposed more than once (ids get a -2, -3 suffix) and every
// copy has the same agent type, so prefer a live approval, newest first, over any
// older or retired one. A plain find() could pick the retired first proposal.
export function approvalForType(org: OrgData, agentType: string) {
  const live = (a: Approval) => a.status === 'approved' || a.status === 'started'
  const all = Object.values(org.approvals).filter(a => a.agentType === agentType)
  all.sort((x, y) => (live(x) === live(y) ? (x.decidedAt < y.decidedAt ? 1 : -1) : live(x) ? -1 : 1))
  return all[0] ?? null
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
export function checkProposal(
  p: { slug: string; tools: string[]; maxMinutes: number; model?: string; modelReason?: string },
  policy: SpecialistPolicy,
) {
  const problems: string[] = []
  if (!/^[a-z0-9][a-z0-9-]{2,39}$/.test(p.slug)) problems.push('slug must be 3-40 of a-z, 0-9 and -')
  const over = p.tools.filter(t => !policy.toolCeiling.includes(t))
  if (over.length) problems.push(`tools above the ceiling: ${over.join(', ')} (allowed: ${policy.toolCeiling.join(', ')})`)
  if (!p.tools.length) problems.push('ask for at least one tool')
  if (!(p.maxMinutes >= 1 && p.maxMinutes <= policy.maxMinutes)) problems.push(`maxMinutes must be 1-${policy.maxMinutes}`)
  const model = p.model ?? 'inherit'
  const allowed = policy.allowedTiers ?? DEFAULT_ALLOWED_TIERS
  if (!allowed.includes(model)) problems.push(`model must be one of: ${allowed.join(', ')}`)
  const reason = (p.modelReason ?? '').trim()
  if (model !== 'inherit' && (policy.requireTierReason ?? true) && !reason) {
    problems.push('a model other than inherit needs a modelReason: why this size suits the task')
  }
  if (reason.length > TIER_REASON_MAX) problems.push(`modelReason must be at most ${TIER_REASON_MAX} characters`)
  if ((model === 'haiku' || model === 'sonnet') && toolFloored(p.tools)) {
    problems.push(`a smaller model is only for specialists limited to ${SAFE_SMALL_TOOLS.join(', ')}; use inherit (or opus) with these tools`)
  }
  return problems
}

// ---------------------------------------------------------------- model size ---
// Which model an agent runs on (see AGENT-ORG.md, "Model sizes").
// The rule it
// serves: the user's own model is the default, and anything else is an explicit,
// reasoned override, never a silent one. Sizes are aliases, never pinned ids; the
// user's model is READ at spawn time (the spawn's parentModel) and mapped by family.

// Smallest to largest. `fable` is known (so a model id can be placed) but is not in
// the default allowed list: a user may add it to their own roster.
export const TIER_ORDER = ['haiku', 'sonnet', 'opus', 'fable'] as const
export const DEFAULT_ALLOWED_TIERS = ['inherit', 'haiku', 'sonnet', 'opus']
export const TIER_REASON_MAX = 160
const SEAT_REASON_MAX = 80

// Never below the user's model, whatever the roster says: the
// security reviewers, Zeus himself, and the seats whose work is judgement or the
// user's voice. A roster `minTier` can add a floor; it can never remove one of these.
export const FLOOR_TYPES = [
  'zeus',
  'secure-code-reviewer',
  'owasp-llm-reviewer',
  'owasp-agentic-reviewer',
  'calliope',
  'prometheus',
  'athena',
]

// Tool-based floor (after the security review): an agent that can write or act,
// reads untrusted content, or whose tools are unknown never runs below the user's model,
// whatever its name. `Skill` counts as able to act until a test shows a subagent's Skill
// grants no extra tools. Only Read/Grep/Glob-only work is eligible for a smaller model.
export const SAFE_SMALL_TOOLS = ['Read', 'Grep', 'Glob']

export function toolFloored(tools: string[] | null | undefined) {
  if (!tools || !tools.length) return true // unknown or unrestricted: inherits everything
  return tools.some(t => !SAFE_SMALL_TOOLS.includes(t))
}

// Floors match on the agent's own name, so a namespaced type (`plugin:athena`) still counts.
export function baseType(t: string) {
  return t.includes(':') ? t.slice(t.lastIndexOf(':') + 1) : t
}

export function tierOf(model: string | null | undefined): string | null {
  if (!model) return null
  const m = model.toLowerCase()
  for (const t of TIER_ORDER) if (m.includes(t)) return t
  return null
}

export function tierRank(t: string | null): number {
  return t ? (TIER_ORDER as readonly string[]).indexOf(t) : -1
}

export type TierFacts = {
  subagentType: string
  requestedModel: string | null // the spawn's `model` as given; null/'' = not set
  parentModel: string | null // what `inherit` resolves to for this spawn
  userModel: string | null // the user's own model (the main conversation's)
  description: string
  parentType: string | null
  approvalModel: string | null // a specialist's approved size ('inherit' when none recorded)
  nested?: boolean // started by another agent (parentAgentId set), not the main conversation
  agentTools?: string[] | null // the target's tool grant (specialist: approved tools); null = unknown
  workflow?: boolean // a Workflow agent: the engine ignores a model rewrite, so a hook can only refuse
  // The `model:` in the agent's own definition, which the engine uses before the parent's
  // when the spawn sets none (re-review NF-D). undefined = no definition read (a built-in
  // such as Explore, or a plugin's agent): what it would run on is not known.
  definitionModel?: string | null
}

export type TierDecision = {
  decision: 'allow' | 'rewrite' | 'refuse'
  model?: string // for 'rewrite': what the spawn is set to
  reason?: string // for 'refuse': what the spawning agent reads
  userTier: string | null
  requestedTier: string | null
  floorTier: string | null
  effectiveTier: string | null
}

// The reason for a non-default size rides in the Agent tool's description (the tool
// has no other field): `tier=haiku; why=<short reason>; <task>`.
export function parseTierPrefix(description: string) {
  const m = /^\s*tier=([A-Za-z0-9._-]+);\s*why=([^;]*);/.exec(description || '')
  return m ? { tier: m[1], why: m[2].trim() } : null
}

export function decideTier(f: TierFacts, org: OrgData | null): TierDecision {
  const roster = org?.roster ?? null
  const policy = roster?.specialistPolicy
  const allowed = policy?.allowedTiers ?? DEFAULT_ALLOWED_TIERS
  const requested = f.requestedModel && f.requestedModel.trim() ? f.requestedModel : null
  const userTier = tierOf(f.userModel)
  const seat = roster?.seats.find(s => s.agentType === f.subagentType)
  const named = FLOOR_TYPES.includes(baseType(f.subagentType)) || f.subagentType === chiefType(roster)
  const floored = named || toolFloored(f.agentTools ?? null)
  const floorTier = floored ? userTier : null
  const seatFloor = tierOf(seat?.minTier ?? null)
  const out = (d: Partial<TierDecision>): TierDecision => ({
    decision: 'allow',
    userTier,
    requestedTier: requested && requested !== 'inherit' ? requested : null,
    floorTier: tierRank(seatFloor) > tierRank(floorTier) ? seatFloor : floorTier,
    effectiveTier: null,
    ...d,
  })
  const refuse = (reason: string) => out({ decision: 'refuse', reason: `Agent Org: ${reason}` })
  // A rewrite cannot be applied to a Workflow agent (the engine ignores it), so refuse instead.
  const rewrite = (model: string, effective: string) =>
    f.workflow
      ? refuse(`a workflow agent cannot be set to ${model}; start ${f.subagentType} on that size directly, or without a model.`)
      : out({ decision: 'rewrite', model, effectiveTier: effective })

  // An explicit value must be one of the allowed aliases, exactly. Ids, other spellings
  // and anything unknown are refused, never quietly cleaned up.
  if (requested !== null && !allowed.includes(requested)) {
    return refuse(`model "${requested.slice(0, 40)}" is not allowed. Use one of: ${allowed.join(', ')} (inherit = the user's model).`)
  }

  // Specialists run on the size on their approval card, and only that size. An approved
  // smaller size also needs Read/Grep/Glob-only tools (the tool floor).
  if (isSpecialistType(f.subagentType)) {
    const approved = f.approvalModel && f.approvalModel !== 'inherit' ? f.approvalModel : null
    const asked = requested && requested !== 'inherit' ? requested : null
    if (asked && asked !== approved) {
      return refuse(`${f.subagentType} was approved for ${approved ?? 'the user\'s model'}, not ${asked}. Start it without a model.`)
    }
    if (approved && userTier && tierRank(approved) < tierRank(userTier) && toolFloored(f.agentTools ?? null)) {
      return refuse(`${f.subagentType} has tools that keep it on the user's model; it cannot run on ${approved}.`)
    }
    if (approved) return asked ? out({ effectiveTier: approved }) : rewrite(approved, approved)
    // Approved for the user's model: pin it explicitly so its real size can be checked (S3).
    if (userTier && !asked) return rewrite(userTier, userTier)
    return out({ effectiveTier: userTier ?? tierOf(f.parentModel) })
  }

  // Who the size rules bind (S4): everyone, the main conversation
  // included (re-review NF-E). An explicit size from anywhere meets the same ceiling,
  // floor and reason checks below.

  // Not set, or inherit. With no model set the engine runs the agent's own default first,
  // then the parent's (NF-D). A floored agent must not end up below the user's size (S5),
  // and when its default can't be known (no definition read) it is pinned to the user's
  // size so what it runs on is known. Nothing runs above the user's size by default either.
  if (requested === null || requested === 'inherit') {
    const ownDefault = requested === null ? tierOf(f.definitionModel ?? null) : null
    const baseline = ownDefault ?? tierOf(f.parentModel)
    const unknownDefault = requested === null && f.definitionModel === undefined
    if (floored && userTier) {
      const below = baseline !== null && tierRank(baseline) < tierRank(userTier)
      if (below) return rewrite(userTier, userTier)
      if (unknownDefault && !f.workflow) return rewrite(userTier, userTier)
    }
    if (userTier && baseline && tierRank(baseline) > tierRank(userTier) && !isSpecialistType(f.subagentType)) {
      return rewrite(userTier, userTier)
    }
    return out({ effectiveTier: unknownDefault && f.workflow ? null : baseline })
  }

  if (!userTier) {
    return refuse(`the user's model (${(f.userModel ?? 'unknown').slice(0, 40)}) could not be placed in a size, so only inherit is allowed.`)
  }
  if (tierRank(requested) > tierRank(userTier)) {
    return refuse(`${f.subagentType} may not run above the user's model (${userTier}). Only an approved specialist can.`)
  }
  const floor = tierRank(seatFloor) > tierRank(floorTier) ? seatFloor : floorTier
  if (floor && tierRank(requested) < tierRank(floor)) {
    return refuse(`${f.subagentType} never runs below ${floor}. Start it without a model.`)
  }
  if (tierRank(requested) < tierRank(userTier) && (policy?.requireTierReason ?? true)) {
    const p = parseTierPrefix(f.description)
    if (!p) return refuse(`a smaller model needs its reason in the description: "tier=${requested}; why=<reason>; <task>".`)
    if (p.tier !== requested) return refuse(`the description says tier=${p.tier.slice(0, 20)} but the model is ${requested}.`)
    if (!p.why) return refuse('the reason for a smaller model is empty.')
    if (p.why.length > SEAT_REASON_MAX) return refuse(`the reason for a smaller model must be at most ${SEAT_REASON_MAX} characters.`)
  }
  return out({ effectiveTier: requested })
}

// After the fact: is the model an agent actually ran on consistent with what was
// decided? (Catches a later plugin changing it, or an agent that skipped the spawn
// check.) Returns a problem, or null.
export function tierViolation(
  subagentType: string,
  actualModel: string | null,
  expectedTier: string | null,
  floorTier: string | null,
) {
  const actual = tierOf(actualModel)
  if (!actual) {
    // A model id that can't be placed (a cloud-provider id, a renamed family) is never
    // silently fine when something was expected of it (S6).
    return expectedTier || floorTier ? `${subagentType} ran on a model that could not be placed in a size (${(actualModel ?? '').slice(0, 40)})` : null
  }
  if (floorTier && tierRank(actual) < tierRank(floorTier)) {
    return `${subagentType} ran on ${actual}, below its floor (${floorTier})`
  }
  if (expectedTier && actual !== expectedTier) return `${subagentType} ran on ${actual}, not the ${expectedTier} it was started on`
  return null
}
