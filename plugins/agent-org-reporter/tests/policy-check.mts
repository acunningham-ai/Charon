// Spawn-rule regression check (pure policy, no engine). Run:
//   node tests/policy-check.mts ../../../../state/agent-org/roster.json
// Expect ALL PASS. Spawn rules, proposals, and the model-size table (decideTier).
import { decideSpawn, checkProposal, decideTier, tierViolation, approvalForType } from '../hooks/policy.ts'
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
// Proposals with a model size.
for (const [p, wantN] of [
 [{slug:'dpa-check', tools:['Read','WebFetch'], maxMinutes:20, model:'haiku', modelReason:'x'}, 1],
 [{slug:'dpa-check', tools:['Read','WebFetch'], maxMinutes:20, model:'opus', modelReason:'needs deep reading'}, 0],
 [{slug:'dpa-check', tools:['Read'], maxMinutes:20, model:'haiku', modelReason:'one lookup in a named file'}, 0],
 [{slug:'dpa-check', tools:['Read'], maxMinutes:20, model:'haiku'}, 1],
 [{slug:'dpa-check', tools:['Read'], maxMinutes:20, model:'claude-haiku-4-5'}, 1],
 [{slug:'dpa-check', tools:['Read'], maxMinutes:20, model:'fable', modelReason:'x'}, 1],
 [{slug:'dpa-check', tools:['Read'], maxMinutes:20, model:'opus', modelReason:'x'.repeat(161)}, 1],
 [{slug:'dpa-check', tools:['Read'], maxMinutes:20, model:'inherit'}, 0],
]) { const n = checkProposal(p, pol).length; const ok = (n>0) === (wantN>0); if (!ok) fail++; console.log(`${ok?'PASS':'FAIL'}  proposal model ${p.model} reason=${p.modelReason ? p.modelReason.length : 0} -> ${n} problem(s)`) }

// Model size: decideTier(facts, org) -> allow | rewrite | refuse.
const OPUS = 'claude-opus-5-5', SONNET = 'claude-sonnet-5-5'
const t = (o) => ({ subagentType:'hephaestus', requestedModel:null, parentModel:OPUS, userModel:OPUS, description:'tune-up', parentType:'zeus', approvalModel:null, ...o })
const tierOrg = (a) => org(a)
const apprM = (model) => ({ ...appr('approved', now+3600e3), model })
const tierCases = [
 ['unset, definition read (inherit) -> allow', t({definitionModel:null}), tierOrg(), 'allow'],
 ['unset, definition unknown (built-in), floored -> rewrite: pinned to the user size (NF-D)', t({}), tierOrg(), 'rewrite'],
 ['unset, floored definition defaults to haiku -> rewrite to the user size (NF-D)', t({definitionModel:'haiku'}), tierOrg(), 'rewrite'],
 ['unset, read-only definition defaults to haiku -> allow', t({subagentType:'scout', definitionModel:'haiku', agentTools:['Read','Grep','Glob']}), tierOrg(), 'allow'],
 ['unset, definition defaults ABOVE the user size -> rewrite down', t({subagentType:'scout', definitionModel:'opus', userModel:SONNET, parentModel:SONNET, agentTools:['Read','Grep','Glob']}), tierOrg(), 'rewrite'],
 ['unset, unknown definition, workflow -> allow (cannot rewrite; checked after start)', t({workflow:true}), tierOrg(), 'allow'],
 ['inherit -> allow', t({requestedModel:'inherit'}), tierOrg(), 'allow'],
 ['haiku + reason on hephaestus (has Skill: tool floor) -> refuse', t({requestedModel:'haiku', description:'tier=haiku; why=list three files; tidy', agentTools:['Read','Grep','Glob','Skill']}), tierOrg(), 'refuse'],
 ['haiku + reason on a read-only agent Zeus starts -> allow', t({subagentType:'scout', requestedModel:'haiku', description:'tier=haiku; why=list three files; tidy', agentTools:['Read','Grep','Glob']}), tierOrg(), 'allow'],
 ['haiku without reason -> refuse', t({requestedModel:'haiku'}), tierOrg(), 'refuse'],
 ['prefix and model disagree -> refuse', t({requestedModel:'haiku', description:'tier=sonnet; why=x; y'}), tierOrg(), 'refuse'],
 ['empty reason -> refuse', t({requestedModel:'haiku', description:'tier=haiku; why=; y'}), tierOrg(), 'refuse'],
 ['full model id -> refuse', t({requestedModel:'claude-haiku-4-5'}), tierOrg(), 'refuse'],
 ['capitalised alias -> refuse', t({requestedModel:'Haiku', description:'tier=Haiku; why=x; y'}), tierOrg(), 'refuse'],
 ['fable (not in default list) -> refuse', t({requestedModel:'fable'}), tierOrg(), 'refuse'],
 ['haiku on secure-code-reviewer (floor) -> refuse', t({subagentType:'secure-code-reviewer', requestedModel:'haiku', description:'tier=haiku; why=x; y'}), tierOrg(), 'refuse'],
 ['haiku on athena (floor) -> refuse', t({subagentType:'athena', requestedModel:'haiku', description:'tier=haiku; why=x; y'}), tierOrg(), 'refuse'],
 ['haiku on calliope (floor) -> refuse', t({subagentType:'calliope', requestedModel:'haiku', description:'tier=haiku; why=x; y'}), tierOrg(), 'refuse'],
 ['haiku on zeus started from main (floor) -> refuse', t({subagentType:'zeus', parentType:null, requestedModel:'haiku', description:'tier=haiku; why=x; y'}), tierOrg(), 'refuse'],
 ['opus on a seat when the user is on sonnet -> refuse', t({requestedModel:'opus', userModel:SONNET, parentModel:SONNET}), tierOrg(), 'refuse'],
 ['unknown user model + haiku -> refuse', t({requestedModel:'haiku', userModel:'mystery-model', description:'tier=haiku; why=x; y'}), tierOrg(), 'refuse'],
 ['main conversation sets haiku on a roster seat -> refuse (S4: binds everyone)', t({parentType:null, requestedModel:'haiku', agentTools:['Read','Grep','Glob']}), tierOrg(), 'refuse'],
 ['main conversation sets haiku on a read-only non-roster agent, with reason -> allow', t({subagentType:'Explore', parentType:null, requestedModel:'haiku', description:'tier=haiku; why=list files; x', agentTools:['Read','Grep','Glob']}), tierOrg(), 'allow'],
 ['main conversation sets haiku on a read-only non-roster agent, no reason -> refuse (NF-E)', t({subagentType:'Explore', parentType:null, requestedModel:'haiku', agentTools:['Read','Grep','Glob']}), tierOrg(), 'refuse'],
 ['main conversation sets opus above a sonnet user on a non-roster agent -> refuse (NF-E)', t({subagentType:'Explore', parentType:null, requestedModel:'opus', userModel:SONNET, parentModel:SONNET, agentTools:['Read','Grep','Glob']}), tierOrg(), 'refuse'],
 ['main conversation sets haiku on general-purpose (tools unknown) -> refuse (tool floor)', t({subagentType:'general-purpose', parentType:null, requestedModel:'haiku'}), tierOrg(), 'refuse'],
 ['specialist with no model, approved haiku, read-only -> rewrite', t({subagentType:'agent-org-reporter:spec-dpa', approvalModel:'haiku', agentTools:['Read','Grep','Glob']}), tierOrg(apprM('haiku')), 'rewrite'],
 ['specialist approved haiku but has WebFetch -> refuse (tool floor)', t({subagentType:'agent-org-reporter:spec-dpa', approvalModel:'haiku', agentTools:['Read','WebFetch']}), tierOrg(apprM('haiku')), 'refuse'],
 ['specialist asks opus, approved haiku -> refuse', t({subagentType:'agent-org-reporter:spec-dpa', requestedModel:'opus', approvalModel:'haiku'}), tierOrg(apprM('haiku')), 'refuse'],
 ['specialist approved above the user (Q1) -> rewrite', t({subagentType:'agent-org-reporter:spec-dpa', userModel:SONNET, parentModel:SONNET, approvalModel:'opus'}), tierOrg(apprM('opus')), 'rewrite'],
 ['specialist approved inherit -> rewrite to the user\'s size (S3 pin)', t({subagentType:'agent-org-reporter:spec-dpa', approvalModel:'inherit'}), tierOrg(apprM('inherit')), 'rewrite'],
 ['helios (calendar MCP) haiku -> refuse (tool floor)', t({subagentType:'helios', requestedModel:'haiku', description:'tier=haiku; why=x; y', agentTools:['Read','Grep','Glob','Skill','mcp__m365-action__list_calendar']}), tierOrg(), 'refuse'],
 ['knowledge-synthesizer (Write) sonnet -> refuse (tool floor)', t({subagentType:'knowledge-synthesizer', requestedModel:'sonnet', description:'tier=sonnet; why=x; y', agentTools:['Read','Grep','Glob','Write']}), tierOrg(), 'refuse'],
 ['nested general-purpose sets opus on hephaestus, user on sonnet -> refuse (S4)', t({parentType:'general-purpose', nested:true, requestedModel:'opus', userModel:SONNET, parentModel:SONNET, agentTools:['Read','Grep','Glob','Skill']}), tierOrg(), 'refuse'],
 ['floored athena inherits a smaller parent -> rewrite to the user\'s size (S5)', t({subagentType:'athena', parentType:'general-purpose', nested:true, parentModel:'claude-haiku-4-5'}), tierOrg(), 'rewrite'],
 ['workflow agent that would need a rewrite -> refuse (S8)', t({subagentType:'agent-org-reporter:spec-dpa', approvalModel:'haiku', workflow:true, agentTools:['Read','Grep','Glob']}), tierOrg(apprM('haiku')), 'refuse'],
 ['namespaced plugin:athena still floored (N4)', t({subagentType:'someplugin:athena', requestedModel:'haiku', description:'tier=haiku; why=x; y', agentTools:['Read']}), tierOrg(), 'refuse'],
]
for (const [name, facts, o, want] of tierCases) {
  const got = decideTier(facts, o).decision
  if (got !== want) fail++
  console.log(`${got === want ? 'PASS' : 'FAIL'}  tier: ${name}: ${got}`)
}
// A roster minTier can raise a floor but never lower the code floor.
{
  const r = { ...roster, seats: roster.seats.map(s => s.agentType === 'athena' ? { ...s, minTier: 'haiku' } : s.agentType === 'hephaestus' ? { ...s, minTier: 'sonnet' } : s) }
  const o = { roster: { seats: r.seats, specialistPolicy: roster.specialistPolicy }, approvals: {}, loadedAt: now }
  const a = decideTier(t({subagentType:'athena', requestedModel:'haiku', description:'tier=haiku; why=x; y'}), o).decision
  const h = decideTier(t({requestedModel:'haiku', description:'tier=haiku; why=x; y'}), o).decision
  const ok = a === 'refuse' && h === 'refuse'
  if (!ok) fail++
  console.log(`${ok ? 'PASS' : 'FAIL'}  tier: roster minTier haiku cannot lower athena's code floor (${a}); minTier sonnet raises hephaestus's (${h})`)
}
// After-the-fact check.
for (const [name, args, want] of [
 ['floored seat ran below its floor', ['athena', 'claude-haiku-4-5', null, 'opus'], true],
 ['downsized seat ran on the size it was started on', ['hephaestus', 'claude-haiku-4-5', 'haiku', null], false],
 ['specialist ran on a different size than approved', ['agent-org-reporter:spec-dpa', 'claude-opus-5-5', 'haiku', null], true],
 ['unplaceable model id when a floor is set -> flagged (S6)', ['athena', 'arn:aws:bedrock:custom-profile', null, 'opus'], true],
 ['unplaceable model id with nothing expected -> fine', ['Explore', 'arn:aws:bedrock:custom-profile', null, null], false],
]) { const v = tierViolation(...args); const ok = Boolean(v) === want; if (!ok) fail++; console.log(`${ok ? 'PASS' : 'FAIL'}  violation: ${name}: ${v ?? 'none'}`) }

{
  const ty = 'agent-org-reporter:spec-dpa'
  const old = { ...appr('retired', now + 3600e3), id: 'p1', decidedAt: '2026-10-08T01:00:00Z' }
  const neu = { ...appr('approved', now + 3600e3), id: 'p2', decidedAt: '2026-10-08T02:00:00Z' }
  const o = { roster: { seats: roster.seats, specialistPolicy: roster.specialistPolicy }, approvals: { p1: old, p2: neu }, loadedAt: now }
  const got = approvalForType(o, ty)?.id
  const ok = got === 'p2'
  if (!ok) fail++
  console.log(`${ok ? 'PASS' : 'FAIL'}  B1: a re-approved slug resolves to the live approval (${got})`)
}
console.log(fail ? `${fail} FAILED` : 'ALL PASS')
process.exit(fail ? 1 : 0)
