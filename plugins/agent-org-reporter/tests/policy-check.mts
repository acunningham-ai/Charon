// Spawn-rule regression check (pure policy, no engine). Run:
//   node tests/policy-check.mts ../../../../state/agent-org/roster.json
// Expect ALL PASS. 26 cases as of 2026-10-08.
import { decideSpawn, checkProposal } from '../hooks/policy.ts'
import { readFileSync } from 'node:fs'
const roster = JSON.parse(readFileSync(process.argv[2], 'utf8'))
const now = Date.now()
const appr = (status, startByMs) => ({ id:'x', slug:'dpa', agentType:'agent-org-reporter:spec-dpa', status, decidedAt:'', decidedVia:'pane', startBy:new Date(startByMs).toISOString(), maxMinutes:10, tools:['Read'] })
const org = (a) => ({ roster: { seats: roster.seats, specialistPolicy: roster.specialistPolicy }, approvals: a ? { x: a } : {}, loadedAt: now })
const f = (o) => ({ subagentType:'athena', fork:false, parentAgentId:null, parentType:null, parentKnown:true, activeSpecialists:0, nowMs:now, ...o })
const cases = [
 ['main starts general-purpose (ungoverned)', f({subagentType:'general-purpose'}), org(), 'allow'],
 ['main starts zeus', f({subagentType:'zeus'}), org(), 'allow'],
 ['zeus starts athena', f({parentAgentId:'z1', parentType:'zeus'}), org(), 'allow'],
 ['zeus starts secure-code-reviewer', f({subagentType:'secure-code-reviewer', parentAgentId:'z1', parentType:'zeus'}), org(), 'allow'],
 ['zeus starts general-purpose', f({subagentType:'general-purpose', parentAgentId:'z1', parentType:'zeus'}), org(), 'deny'],
 ['zeus starts Explore (not on roster)', f({subagentType:'Explore', parentAgentId:'z1', parentType:'zeus'}), org(), 'deny'],
 ['zeus starts zeus', f({subagentType:'zeus', parentAgentId:'z1', parentType:'zeus'}), org(), 'deny'],
 ['zeus starts cerberus (independent)', f({subagentType:'cerberus', parentAgentId:'z1', parentType:'zeus'}), org(), 'deny'],
 ['zeus forks', f({fork:true, parentAgentId:'z1', parentType:'zeus'}), org(), 'deny'],
 ['zeus starts unapproved specialist', f({subagentType:'agent-org-reporter:spec-dpa', parentAgentId:'z1', parentType:'zeus'}), org(), 'deny'],
 ['zeus starts approved specialist', f({subagentType:'agent-org-reporter:spec-dpa', parentAgentId:'z1', parentType:'zeus'}), org(appr('approved', now+3600e3)), 'allow'],
 ['main starts approved specialist', f({subagentType:'agent-org-reporter:spec-dpa'}), org(appr('approved', now+3600e3)), 'allow'],
 ['approved but lapsed', f({subagentType:'agent-org-reporter:spec-dpa', parentAgentId:'z1', parentType:'zeus'}), org(appr('approved', now-1)), 'deny'],
 ['single-use already started', f({subagentType:'agent-org-reporter:spec-dpa', parentAgentId:'z1', parentType:'zeus'}), org(appr('started', now+3600e3)), 'deny'],
 ['A1: approved but already started in this process (race)', f({subagentType:'agent-org-reporter:spec-dpa', parentAgentId:'z1', parentType:'zeus', alreadyUsed:true}), org(appr('approved', now+3600e3)), 'deny'],
 ['declined', f({subagentType:'agent-org-reporter:spec-dpa'}), org(appr('declined', now+3600e3)), 'deny'],
 ['9 active is under the limit of 10', f({subagentType:'agent-org-reporter:spec-dpa', activeSpecialists:9}), org(appr('approved', now+3600e3)), 'allow'],
 ['10 active hits the limit', f({subagentType:'agent-org-reporter:spec-dpa', activeSpecialists:10}), org(appr('approved', now+3600e3)), 'deny'],
 ['specialist starts athena', f({parentAgentId:'s1', parentType:'agent-org-reporter:spec-dpa'}), org(), 'deny'],
 ['unknown parent nested', f({parentAgentId:'q1', parentType:null, parentKnown:false}), org(), 'deny'],
 ['general-purpose (main child) starts Explore', f({subagentType:'Explore', parentAgentId:'g1', parentType:'general-purpose'}), org(), 'allow'],
 ['org not loaded, zeus starts athena', f({parentAgentId:'z1', parentType:'zeus'}), null, 'deny'],
 ['org not loaded, main starts athena', f({}), null, 'allow'],
]
let fail = 0
for (const [name, facts, o, want] of cases) {
  const got = decideSpawn(facts, o) === null ? 'allow' : 'deny'
  if (got !== want) fail++
  console.log(`${got === want ? 'PASS' : 'FAIL'}  ${name}: ${got}`)
}
const pol = roster.specialistPolicy
const pc = [
 [{slug:'dpa-check', tools:['Read','WebFetch'], maxMinutes:20}, 0],
 [{slug:'dpa-check', tools:['Read','Bash'], maxMinutes:20}, 1],
 [{slug:'dpa-check', tools:['Read'], maxMinutes:90}, 1],
 [{slug:'../x', tools:['Read'], maxMinutes:5}, 1],
 [{slug:'ok-slug', tools:[], maxMinutes:5}, 1],
]
for (const [p, wantN] of pc) { const n = checkProposal(p, pol).length; const ok = (n>0) === (wantN>0); if (!ok) fail++; console.log(`${ok?'PASS':'FAIL'}  proposal ${JSON.stringify(p)} -> ${n} problem(s)`) }
console.log(fail ? `${fail} FAILED` : 'ALL PASS')
process.exit(fail ? 1 : 0)
