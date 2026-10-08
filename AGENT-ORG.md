# Agent Org

Agent Org lets you see your agents working, live, and gives them a chain of command you control:

- **Zeus**, a Chief of Staff, plans multi-part tasks and hands each part to the right seat.
- Rules the system enforces decide who may start which agent.
- Single-use specialists run only after you approve them.
- A live pane beside the conversation, and a local webpage, show everything as it happens.

It needs **Claude Code 2.1.287 or later**. It was built and tested on 2.1.286 and 2.1.292.

---

## 1. First, what are Claude Code mods?

On 1 October 2026 Anthropic added **mods** to Claude Code: *"small TypeScript functions that change how Claude Code
works"* ([Anthropic: Customize Claude Code with mods in TypeScript](https://claude.com/resources/articles/claude-code-mods)).

A mod is a plugin whose code Claude Code calls when things happen: a tool is about to run, a prompt is submitted,
an agent is about to start, the screen is drawn. Each handler can **watch** the event, **change** it, **answer** it
itself, or **refuse** it. Anthropic rebuilt some of its own features this way.

Technical reference: [Create a mod](https://code.claude.com/docs/en/plugins/mods/create) ·
[Mods reference](https://code.claude.com/docs/en/plugins/mods/reference) ·
[Manage mods for your organization](https://code.claude.com/docs/en/plugins/mods/admin).

### Why it matters for a harness like Charon

Until mods, a harness could only shape Claude Code from the outside. It had rules it *asks* the model to follow, and
shell hooks that see a tool call as text and answer allow or deny. Mods move the harness **inside** the agent loop:

| Before mods | With mods |
|---|---|
| "Only start approved agents" was an **instruction** the model could ignore | The spawn is **refused by the system** before it starts |
| Activity was reconstructed from logs after the fact | Every spawn, tool call and finish is **observed as it happens** |
| Status lived in files you had to open | A **live pane** beside the conversation, with graphics and buttons |
| Approvals were a chat message | An **Approve button** that only your press, or your typed command, can trigger |
| A new agent type meant editing config files | An approved specialist is **registered as a real agent type** at runtime, with exactly the tools approved |

Agent Org is Charon's first capability built on mods.

### What to know before turning it on

- **Version:** Claude Code 2.1.287 or later (Anthropic's documented floor). The installer checks.
- **Trust:** mods *"aren't sandboxed"* and *"run with the same access to your machine as Claude Code itself"*: the
  same trust bar as any program you install. Agent Org's source is in this repo (`plugins/agent-org-reporter/`) and
  was reviewed (see [SECURITY.md](SECURITY.md#agent-org)).
- **Organisations:** on Team and Enterprise plans a built-in `sec-default` mod *"loads first"* and can stop
  user-installed mods; admins can also block mods in managed settings. If Agent Org does nothing, check that first.
- **The API moves:** Anthropic notes events and methods *"can change between releases"*. Agent Org states the version
  it was tested with, and `claude plugin validate plugins/agent-org-reporter` tells you whether your version still
  accepts it.

---

## 2. Zeus, and how the brain works on a complex task

### Why Zeus exists

Charon's seats each do one kind of work well:

- **Athena** answers from your own vault.
- **Prometheus** researches the outside world.
- **Calliope** drafts in your voice.
- **Helios** runs your day.
- **Hephaestus** keeps the harness healthy.

Real tasks rarely fit one seat. "Prepare the weekly security brief" needs your notes (Athena), this week's
advisories (Prometheus), and a draft for the team (Calliope).

Without Zeus, *you* are the router: you remember which command each part needs, run them in order, and stitch the
results together. With Zeus you hand over the whole task, and he turns it into a plan, delegates each part to the
right seat, and merges what comes back into one answer. He plans and delegates; he does not do the work himself,
and he writes nothing.

### How a complex task flows

| Step | What happens |
|---|---|
| **1. You ask** | You give Zeus a task that spans more than one seat. |
| **2. He plans** | Zeus breaks it into parts and picks the seat for each. |
| **3. Seats work** | Each seat runs as its own agent, in parallel where it can. You watch them in the pane. |
| **4. No seat fits?** | Zeus **proposes** a specialist instead of improvising: its purpose, its single task, the exact tools it needs, a time limit and the full brief it will be given. |
| **5. You decide** | The proposal appears in the pane with **Approve** and **Decline** buttons and the brief in full. Nothing runs until you press Approve or type `/agent-org approve <id>`. |
| **6. The specialist runs once** | Approved, it becomes a real agent type with only the tools you approved, read-only and web at most. It runs once, within 24 hours of approval, for at most its time limit. |
| **7. Zeus merges** | He checks each result against what you actually asked, follows up on anything fixable, and gives you one answer. |

### The rules the system enforces

These are not instructions to the model. The mod refuses the spawn before it starts:

- Zeus may start **only** seats on the roster and specialists you approved. He may never start a general-purpose
  agent, a fork, or another Zeus.
- **Cerberus** sits outside Zeus's chain of command. It checks the others, so it reports to you directly, and Zeus
  cannot start it.
- A specialist's tools never exceed the ceiling (Read, Grep, Glob, WebSearch, WebFetch). Once its time limit has
  passed, its tool calls are refused, though it can always still report back.
- At most 10 specialists run at once. Each approval is used once. An approval not used within 24 hours lapses.
- An approval counts **only** when you press the button or type the command. A command sent by a model, another
  plugin, the SDK or a scheduled prompt is refused.

### Looking ahead

Zeus, the seats and every specialist run on the model you have set in Claude Code (the four standing reviewers name
their own in their agent files). A natural next step is for Zeus to propose the
model for each agent based on what it needs to do: a small, fast one for a mechanical lookup, a stronger one for
judgement. It would show on the approval card with its reason, it would never be silent, and your own model would
stay the default. It's on the roadmap, not in this release.

---

## 3. The pane and the dashboard: what each section tells you

The **pane** opens beside the conversation automatically once your terminal is 144 columns wide, or at any width with
`/agent-org`. The **dashboard** is a local webpage: `/agent-org web`, or the button at the bottom of the pane.

Each section below gives what it shows, where the data comes from, and the questions it answers.

### Pane

| Section | What it shows | Questions it answers |
|---|---|---|
| **SYSTEM** | The time, plus today's tool calls, tokens written and agents running. `● LIVE` while something ran in the last minute. | Is the harness working right now? How much has it done today? |
| **ACTIVITY** | Tool calls per 10 seconds and tokens per minute over the last 15–20 minutes. | When was it busy? Is something looping (calls spike, no tokens)? Is a long task still moving? |
| **GATES** | Today's safety-gate verdicts: allowed, watched, asked, blocked. | How often did the gates step in today? Is a rule firing more than expected? |
| **LIVE AGENTS** | One lane per running agent, across every open session, with children indented under the agent that started them. Each lane shows the tool it's in now, a spark of recent calls, and its run time (used/limit for specialists). | What is running right now, who started it, what is it doing, is it stuck, how long has it run? |
| **ORG** | The org chart: you, Zeus, the seats, the standing reviewers, approved specialists, and Cerberus off to the side. Running seats light up. | Which seats are in use? Is Zeus delegating as expected? Which specialists exist right now? |
| **APPROVAL NEEDED** | Each pending specialist: title, tools, time limit, purpose, task, the start of the brief, Approve and Decline. | What exactly will this specialist be told and allowed to do before I approve it? |
| **FEED** | The last few events, newest first. | What just happened? Which call failed or was blocked? |
| **WAITING ON YOU** | Harness failures waiting for `/harness-review`, and overdue commitments. | What needs a person? |

### Dashboard (webpage)

| Section | What it shows | Questions it answers |
|---|---|---|
| **Live agents** | The pane's lanes, full width. | As above, with room for long descriptions. |
| **Who's working** | A constellation: you at the centre, seats around you, specialists in between. | Who has worked today, and who is working now? |
| **What it's doing** | Every tool call, spawn and finish in the last 24 hours, filterable to subagents. | What happened, in order, across sessions? |
| **Sessions** | Each session with its agents, calls and tokens, plus a 24-hour calls-per-hour chart. | Which session did the work? When was the harness busiest? |
| **Gates today** | Verdicts by hook, and the most recent asks and blocks with their reasons. | Which gate is doing the work? Why did it stop something? |
| **Waiting on you** | Pending specialists with Zeus's **full brief**, the review queue by automation, and overdue commitments. | What am I being asked to approve, word for word? What's owed? |

### Demo mode, for screenshots and talks

`/agent-org demo` switches the pane to a sample org with moving activity. The clock bar reads **◆ DEMO DATA**, and the
dashboard button opens a demo page on its own port. Nothing real appears, and Approve and Decline record nothing.
`/agent-org live` (or `/agent-org demo off`) returns to your activity.

---

## 4. Turning it on and off

- **New install:** the setup wizard asks *"Turn on Agent Org?"* (default yes).
- **Existing install:** `/charon-update` tells you it arrived and asks the same question.
- **By hand:** `python scripts/agent_org_setup.py` to turn it on, `--check` to see what it would change, and
  `--disable` to turn it off. Restart Claude Code afterwards.

Turning it on adds this repo's `plugins/agent-org-reporter` folder to `CLAUDE_CODE_PLUGIN_DIRS` in the `env` block of
`~/.claude/settings.json`. Anything already listed there stays, a timestamped backup is kept beside the file, and
running it twice changes nothing. It refuses to touch a settings file it cannot parse.

### Where it finds your vault

The mod finds your vault by walking up from its own folder to the first directory that holds `.claude/` and
`scripts/load-rules.py` (any Charon clone). Set `HARNESS_VAULT_ROOT` to override. The capture pipeline is
`HARNESS_CAPTURE_ROOT`, else `~/capture-pipeline`. If no vault is found, nothing is logged, a status line says so, and
the spawn rules still hold, using the roster shipped with the plugin.

---

## 5. Files and configuration

| File | What it is | Who writes it |
|---|---|---|
| `plugins/agent-org-reporter/roster.default.json` | The default org chart and specialist limits | Shipped; not edited in place |
| `state/agent-org/roster.json` | Your own org chart, if you copy and edit the default (takes precedence) | You, in a reviewed change (a policy rule asks first) |
| `state/agent-org/approvals.json` | Your approve and decline decisions | **Only** the pane, on your press or typed command (a policy rule blocks every other writer) |
| `state/agent-org/specialists/*.json` | Zeus's proposals | **Only** Zeus's `propose_specialist` tool |
| `state/agent-org/audit/<local date>/<session>.jsonl` | One line per event | The reporter |
| `state/agent-org/status/<session>/<agent>.json` | Each agent's current state | The reporter |

`state/` is git-ignored: none of this leaves your machine. Specialist limits are set in the roster's
`specialistPolicy`: `toolCeiling`, `maxMinutes` (default 30) and `maxActive` (default 10).

---

## 6. Privacy and security, in brief

- **No content is recorded.** The reporter writes tool **names**, timings, outcomes and token counts. It never writes
  your prompts, the model's answers, or tool inputs and outputs. An agent's short description and another hook's
  deny reason are kept, capped at 120 and 200 characters.
- **Local only.** The dashboard binds to `127.0.0.1` and refuses requests addressed to any other host (a guard
  against DNS rebinding). It is read-only, serves fixed routes under a strict content-security policy, and stops by
  itself two minutes after its last tab closes. No network calls.
- **Untrusted text stays text.** Descriptions, deny reasons and Zeus's briefs can quote anything an agent saw. The
  pane draws them as plain text, and the page places them with `textContent`, never as HTML.
- **Known limits.** Time limits are enforced; token cost is not. Specialists are registered in interactive sessions
  (the pane does it). Agents a Workflow starts don't pass through `agent.spawn`, so the spawn rules don't see them.
  Only the main conversation can run a workflow, and Zeus has no Workflow tool.

Full detail: [SECURITY.md](SECURITY.md#agent-org).

## 7. Troubleshooting

| Symptom | Check |
|---|---|
| No pane, no `/agent-org` command | `claude --version` is 2.1.287 or later; `CLAUDE_CODE_PLUGIN_DIRS` names the folder (`python scripts/agent_org_setup.py --check`); you restarted Claude Code; your organisation hasn't blocked mods. |
| The pane doesn't open by itself | It opens unasked only at 144 terminal columns or wider. Type `/agent-org`. |
| "no vault found" status line | Set `HARNESS_VAULT_ROOT` to your vault folder. |
| Zeus says "the roster is still loading" | Wait a few seconds after starting a session; if it persists, check `state/agent-org/roster.json` is valid JSON. |
| The dashboard won't start | Python must be on PATH. Run `python plugins/agent-org-reporter/dashboard/server.py --serve` to see the error. |
| Validation | `claude plugin validate plugins/agent-org-reporter` and `claude plugin test plugins/agent-org-reporter`. |
