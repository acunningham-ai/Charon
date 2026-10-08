// State contract for the agent-org pane (hooks/pane.tsx).
// `live` is written by the reporter (register.ts) from its in-session roll-up;
// `ambient` by the pane's own slow timer (gate verdicts + work waiting on the user).

export type PaneAgent = {
  key: string
  agentId: string | null
  parentAgentId: string | null
  type: string
  description: string
  state: string
  toolCalls: number
  tokensOut: number
  startedAt: string
  lastActivity: string
  currentTool: string | null
  currentSince: string | null
  lastTool: string | null
  callTimes: number[]
  finishedAt: string | null
  tier?: string | null // size it was started on
  tierNote?: string | null // 'below your model' / 'above your model'
}

export type PaneEvent = {
  ts: string
  who: string
  isSub: boolean
  what: string
  outcome: 'ok' | 'error' | 'blocked' | 'start' | 'done' | 'stopped'
}

export type PaneLive = {
  agents: PaneAgent[]
  recent: PaneEvent[]
  mainCalls: number
  tokensOut: number
}

export type PaneAmbient = {
  gates: { allow: number; observe: number; ask: number; deny: number } | null
  reviewQueue: number | null
  overdue: number | null
  checkedAt: string
}

export type PaneSpecialist = {
  id: string
  slug: string
  title: string
  purpose: string
  tools: string[]
  maxMinutes: number
  status: 'pending' | 'approved' | 'declined' | 'started' | 'retired' | 'lapsed'
  proposedAt: string
  task: string
  brief: string // first 600 chars of Zeus's brief (A2); untrusted, drawn as plain text
  model: string // proposed size: inherit | haiku | sonnet | opus
  modelReason: string // Zeus's reason (untrusted, capped, control chars stripped)
  sizeNote: string // 'your model' / 'below your model' / 'ABOVE your model'
  cardHash: string // sha256 of what the card shows; a decision is refused if the proposal changed
}

export type PaneOrg = {
  seats: { id: string; name: string; kind: string; reportsTo: string; running: number }[]
  specialists: PaneSpecialist[]
  loadedAt: string
}

declare module 'claude-code' {
  interface PluginState {
    'agent-org-reporter': {
      live: PaneLive | null
      ambient: PaneAmbient | null
      webNote: string | null
      agentTypes: Record<string, string>
      // Enforcement state that must survive a hot reload (model-sizing review S2).
      enforce: {
        tierExpect: Record<string, { type: string; expected: string | null; floor: string | null }>
        violators: string[]
        usedApprovals: string[]
        specRuns: Record<string, { approvalId: string; type: string; startedMs: number; done: boolean }>
      }
      org: PaneOrg | null
      liveRows: number
      demo: boolean
    }
  }
}
