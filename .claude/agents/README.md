# Charon subagents — multi-agent pattern

Subagents in `.claude/agents/` are dispatched by the parent session via the `Agent` tool with `subagent_type: <name>`. Each subagent gets:

- A fresh context window (parent's context doesn't bleed in)
- A constrained `tools:` list (least-privilege per task)
- A focused system prompt body (what's in the .md file below the frontmatter)
- Optional model override (run heavyweight review on Sonnet, light triage on Haiku)

## Why subagents matter for Charon

Three reasons:

1. **Parallel review.** A deploy can dispatch `secure-code-reviewer`, `owasp-llm-reviewer`, and `owasp-agentic-reviewer` in parallel against the same path. They run independently, return findings; parent merges. Three reviews in the time of one.

2. **Context isolation.** The parent's context is precious. Loading 30 files into the parent to run a review burns that budget. Loading them into a subagent keeps the parent's context clean — the subagent returns its summary, and the parent never holds the file contents.

3. **Bounded permissions.** Subagents declare their `tools:` list. A review subagent has `Read, Grep, Glob` and nothing else — even if its system prompt gets injection-attacked into trying to delete files, it can't (no `Bash`, no `Write` on protected paths).

## Subagents that ship

| Subagent | What it does | Tools | Model |
|---|---|---|---|
| `secure-code-reviewer` | C-1..C-8 baseline + secure-coding fundamentals | Read, Grep, Glob | sonnet |
| `owasp-llm-reviewer` | OWASP LLM01-LLM10 review | Read, Grep, Glob | sonnet |
| `owasp-agentic-reviewer` | OWASP ASI01-ASI10 review | Read, Grep, Glob | sonnet |
| `knowledge-synthesizer` | Synthesise a framework doc on a topic | Read, Grep, Glob, Write | sonnet |
| `cerberus` | Security specialist for Claude Code installations — audit, harden, recover | Read, Grep, Glob, Bash | inherit |

## Three kinds of agent

Charon ships **three** categories of agent under `.claude/agents/`, and they're used differently:

1. **Review / synthesis subagents** (the table above) — scoped operating modes dispatched *by a parent skill* via the `Agent` tool for parallel, context-isolated work. You don't usually invoke them directly.
2. **Standing seats** (below) — named functional roles in the "research → compose → deliver" pipeline, each invoked via its *own slash command* and steered across sessions by a persistent artefact. They are functional seats (a research analyst, a writer) — **not** roleplay of *your* identity, which remains an anti-pattern (see below).
3. **Front-door seats** (below) — named doors onto a *cluster of existing commands*. They own no logic of their own: they pick the right verb from how you phrased the ask, run it, and add a synthesis across the results. **Purely additive** — every verb they route to still works standalone.

## Standing seats — the research → compose pipeline

These are the always-available roles that carry work across sessions. They are intent-scoped (one job each), take no consequential action on their own, and hand off to each other.

### Prometheus — the research seat (`/prometheus`)

**Capability.** A standing research analyst. It keeps a persistent **ledger** (`00-Inbox/_research/_ledger.md`) of your standing research beats, reads an allowlist of newsletter/digest senders from your captured email as an input beat (matched on the `sender:` frontmatter only; treated as untrusted data), researches the top-K active threads each run, and writes a prioritised daily **digest** with framed content angles. Read + write-note only — it writes solely to `00-Inbox/_research/`, never to captured content or authoritative files.

**Intent.** Stop you sifting raw research, and stop threads slipping between days. It triages and surfaces; *you* steer (by editing the ledger's steer column) and *you* decide what's promoted or acted on. The K-budget and the no-self-promote rule are what keep it out of rabbit holes. It is the **research** stage — it frames angles and hands content-worthy ones to Calliope.

### Calliope — the writing seat (`/calliope`)

**Capability.** Composes your outbound writing **in your voice** across modes — `post` (delegates to the tuned `/draft-linkedin`), `bulletin` (stakeholder/org-unit advisory + a co-located responses tracker), `tweet`, and `email`. Loads the `voice-content` rule + your `user_voice.md` profile + voice anchors before drafting. Stakeholder-facing artefacts are capability-led (no tool-class mandates beyond your configured exceptions).

**Intent.** Turn a researched angle or a raw topic into a draft that sounds like you, not a generic LLM. **It drafts only — it never sends, posts, or emails.** Bulletins are draft-to-approval with a human-gated send (broad blast radius). It is the **compose** stage: Prometheus researches → Calliope writes → a delivery seat (when present) delivers.

## Front-door seats — one door onto a cluster of verbs

These exist because the honest problem with 52 commands isn't that any one of them is wrong — it's having to know *which* to reach for. Each seat is a **command paired with an agent persona**: the command is the runnable front door (it has the shell), the persona reasons and prioritises. They route to proven verbs and add the thing no single verb produces.

**They take nothing away.** No command is removed, hidden, tiered, or demoted by a seat's existence. Every routed verb keeps working and stays documented as first-class in `CAPABILITIES.md`. Use the seat when you want the synthesis; use the verb when you know exactly what you want.

### Athena — the knowledge seat (`/athena`)

**Capability.** One door to your own vault. Picks the mode from your phrasing: `find` (`/recall` — ranked hybrid retrieval), `relate` (`/vault-query` — graph traversal), `tension` (`/find-tensions` — where your notes contradict each other), `gather` (`/knowledge-consolidate`), `connect` (`/graph-backfill`), `remember` (`/save-feedback` · `/push-fact` · `/promote-rule`). Defaults to `find` because it's cheapest and its hits tell you whether to go deeper; cites the note path behind every answer.

**Intent.** Make what you've already written *askable* — you ask the question instead of remembering the command. **Memory writes are proposed, never silent:** you see the target file, the frontmatter, and the index line, and nothing lands without your yes. Retrieved content — especially anything that began as a capture — is data to report, never an instruction to obey.

### Helios — the daily-cadence seat (`/helios`)

**Capability.** The **morning brief** (default): what changed since the last brief · what's on today · what's owed and still open · *"today in a sentence"* plus the first thing to do. `evening` → `/eod-reflect`; `weekly` → `/weekly-checkin`. Calendar is **optional and user-configured** — Charon ships none, so the brief works without one and improves if you wire your own *read-scoped* provider tool into both the command's `allowed-tools` and this agent's `tools:`.

**Intent.** Replace "run triage, then todo, then read the list yourself" with one prioritised read. **Read + surface only** — it *offers* `/refresh-todo`, it never silently rewrites `TODO.md`. Captured content **and** any fetched calendar data are treated as untrusted: anyone can put text in your inbox or on your calendar, so a crafted subject is something to report, never to act on.

### Hephaestus — the tune-up seat (`/hephaestus`)

**Capability.** The **tune-up** (default) runs the health and hygiene detectors (`/harness-doctor`, `/score-vault`, `/vault-lint`), names the headline `/harness-improve` and `/curate-skills` opportunities, and returns ONE prioritised **broken / messy / could-improve** list — most-impactful first, each with the command that fixes it, ending on the single highest-value fix. Single-mode asks (`health`, `hygiene`, `improve`, `curate`, `telemetry`, `watch-review`) delegate straight to the verb.

**Intent.** One maintenance report instead of six remembered chores. **Surfaces and proposes; never auto-fixes**, never archives, never rewrites — there is no auto-apply path, so every fix is your deliberate step.

### The tool ceiling these seats respect (important)

**All three seat personas declare `Read, Grep, Glob, Skill` — and deliberately no `Bash`.**

`Skill` **loads a command's instructions; it does not grant that command's tools.** So a seat persona genuinely *cannot* execute a shell-needing verb it dispatches — that covers `/recall` behind Athena's `find` mode and the detector scripts behind `/harness-doctor`, `/score-vault`, `/vault-lint`, `/triage-inbox` and `/refresh-todo`. Three consequences, all deliberate:

- **The command path is primary.** Run `/athena`, `/helios`, `/hephaestus` as slash commands — the main-context run has the shell, and a *command* can declare a properly scoped grant (e.g. `/athena` declares `Bash(python scripts/recall.py:*)`).
- **An unscopeable grant is removed, not documented.** Agent frontmatter `tools:` can only name a bare tool — it cannot carry a scope. A bare `Bash` on a persona therefore widens to whatever `settings.json` allows (`Bash(python scripts/*)` — every script, including mutating ones), and no PreToolUse hook gates `Bash`. Prose saying "only use it for X" is not a boundary, so the grant is dropped instead. A seat routes and synthesises; the command executes.
- **A persona must never fabricate the output it couldn't produce.** Each is instructed to say plainly "that couldn't run here" and defer to the command path. Widening the grants was rejected twice over: it would also let a read-only seat run *action* verbs' shell steps, breaking surface-not-autofix.

## Dispatch pattern

From the parent session or a skill, dispatch via the `Agent` tool:

```python
# Parent skill body example — running three reviews in parallel
Agent(subagent_type="secure-code-reviewer", description="C-1..C-8 + secure-coding", prompt="Review scripts/hooks/save-on-mention.py for C-1..C-8 compliance and general secure-coding issues. Return findings with file:line citations.")
Agent(subagent_type="owasp-llm-reviewer", description="OWASP LLM01-LLM10", prompt="Review scripts/hooks/save-on-mention.py for OWASP LLM01-LLM10 risks. Return findings tagged by category.")
Agent(subagent_type="owasp-agentic-reviewer", description="OWASP ASI01-ASI10", prompt="Review scripts/hooks/save-on-mention.py for OWASP ASI01-ASI10 risks. Return findings tagged by category.")
```

Claude Code dispatches them in parallel when invoked in a single response.

## When to use subagents vs. inline skills

| Use subagent | Use inline (skill body in parent) |
|---|---|
| Task is naturally parallelisable | Task is sequential / iterative |
| Task is read-heavy (loads many files) | Task touches few files |
| Task has a different model needs (e.g. heavyweight review) | Task fits the parent's model |
| Permission isolation matters | Permissions match the parent's |

## Authoring a new subagent

1. Create `.claude/agents/<name>.md` with frontmatter (name, description, tools, model)
2. System prompt body describes the operating mode + output format + when NOT to use
3. Update this README's table
4. Reference from the parent skill that dispatches it (`/owasp-llm-review` etc.)
5. Test by dispatching against a known input

Per `.claude/rules/skill-authoring.md` — the same ten-pattern discipline applies to subagents.

## Anti-patterns

- **Persona subagents** ("act as a senior CISO"). Subagents are scoped operating modes, not personas.
- **Overgranted tools.** Default-deny; add tools only as the task demands.
- **Skipping `/fp-check` on subagent findings.** Subagents are easy to write but hard to calibrate — run FP-check on every 🔴 from a new subagent.
- **No when-NOT-to-use section.** Every subagent declares when the parent should pick a different one.
- **Subagent that writes outside its declared scope.** The `Write` permission gates the path; if a subagent's scope is `07-References/` only, it shouldn't be writing elsewhere.

## See also

- `.claude/rules/skill-authoring.md` — the ten-pattern standard applies
- `SECURITY.md` — agentic threat model (ASI01-ASI10) applies to subagents themselves
- `test-scenarios/` — subagent behaviour gets tested via the parent skill that dispatches it
