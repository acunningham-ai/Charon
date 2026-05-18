---
paths:
  - ".claude/commands/**"
  - ".claude/skills/**"
  - "scripts/mcp/**"
  - "scripts/hooks/**"
keywords:
  - "write a skill"
  - "new skill"
  - "new slash command"
  - "build a skill"
  - "new MCP"
  - "new mcp"
  - "skill authoring"
  - "skill-authoring"
  - "promote-rule"
  - "new hook"
  - "hook authoring"
---

# Skill-authoring standard

Auto-injected when editing skill files (`.claude/commands/`, `.claude/skills/`), MCP servers (`scripts/mcp/`), or hooks (`scripts/hooks/`), or when the prompt mentions skill/MCP authoring.

## The ten patterns

Every new skill, hook, or MCP server SHOULD satisfy these unless explicitly justified otherwise:

1. **Context-first** — state in the first 2 sentences what the skill does and *why it exists*. The reader (the assistant or the user) should know within 50 words whether to invoke it.

2. **Multi-mode** — if the skill has both interactive and unattended modes (e.g. interactive `/refresh-todo` vs scheduled `morning-update.bat`), document both. State the review-checkpoint behaviour explicitly.

3. **Reference separation** — skill file itself <10 KB. Deep reference material lives in `references/` next to the skill; templates in `templates/`. Reduces context-window load on every invocation.

4. **Confidence tagging on output** — prose findings get inline 🟢 verified / 🟡 medium / 🔴 assumed markers per `confidence-tags.md`. Skip on trivial status messages; apply to findings, judgements, recommendations.

5. **Proactive triggers** — if the skill should surface findings *without being asked* during normal work (not just when invoked), declare this in the skill body. Default is "only when invoked"; opt-in to proactive.

6. **Output artifacts** — name the output file(s) the skill produces, where they live, and what frontmatter they carry. Audit / score-vault tooling depends on consistent shapes.

7. **Quality loop** — every skill that writes a non-trivial file SHOULD have a review checkpoint OR a post-run audit. Pure scripts / deterministic checks are exempt; LLM-driven skills are not. See `07-References/security-baselines.md` C-3 + C-5.

8. **Constraint compliance** — Claude-only by default (no other LLMs, including embeddings, unless the user has explicitly opted into a mixed stack). Cite `feedback_classification_frontmatter.md` for files marked `confidential` (human-only handling).

9. **Co-change couplings** — every skill that writes new files MUST consider whether `MEMORY.md` index, CLAUDE.md, or `/score-vault` need updates. State which couplings apply at the bottom of the skill file.

10. **When-NOT-to-use** — every skill has a "When NOT to use" section. Distinguishes the skill from adjacent ones (e.g. `/eod-reflect` vs `/weekly-checkin` vs `/refresh-todo`). Prevents misuse.

## Frontmatter checklist

```yaml
---
description: <one line, concrete, names the output shape>
argument-hint: <if accepts $ARGUMENTS — example calls>
allowed-tools: <minimum set; default-deny Bash/Agent for unattended; deny WebFetch/WebSearch unless explicitly needed>
---
```

For MCP tools, also declare in the rendered `inputSchema` exactly what fields are accepted and which are required. Don't accept free-form blobs when a constrained shape works.

**LLM-generated frontmatter values** — wrap free-text scalars in double quotes. Mid-value `: ` (colon + space) breaks YAML parsing and renders as raw red error text in Obsidian. Applies to any skill that produces files with YAML frontmatter.

## Security-baseline reminders

- **C-1 hardened prompt** for any skill that may run unattended. Name protected files; name the single output target.
- **C-2 tool minimisation** by default. Add tools only with justification (deterministic wrapper invocation IS the justification — e.g. `Bash(python scripts/...)`, `Bash(<your-scheduled-runner>)`).
- **C-3 / C-3.1** — path-layer allowlist + value-layer enum constraint where applicable.
- **C-7** — captured-content discipline. No writing to `00-Inbox/_captured/**`.
- **C-8** — sensitive-data egress. Secrets read from your configured secrets directory (`~/.secrets/` by default) at moment of need, never embedded.

## First-run calibration — assume miscalibration

When a newly authored review/audit skill runs against the harness for the first time, **default position: the skill is miscalibrated until proven otherwise**. Run `/fp-check` on every 🟡/🔴 finding before applying any fix. New skills are easy to write but hard to calibrate without runtime feedback.

## Run before shipping a new skill / hook / MCP

| Skill | What it checks |
|---|---|
| `/secure-code-review <path>` | C-1..C-8 baseline + general secure-coding (input validation, dangerous functions, secrets handling, path traversal) |
| `/owasp-llm-review <path>` | LLM01-LLM10 if path has LLM-consumer surface (`claude -p`, Anthropic SDK calls, prompt construction) |
| `/owasp-agentic-review <path>` | ASI01-ASI10 if path has agentic surface (system prompts, tool dispatch, memory, sub-agents, MCP) |
| `/fp-check` | On every 🔴 finding from any of the three review skills, before merge |
| `/score-vault` | Hygiene check before shipping the change |

Companion rule: `secure-code.md` (auto-fires on these paths) — read it for the full review flow.

## Anti-patterns (catches reviewers should call out)

- **Persona skills** (`act as a senior CISO`). The user is themselves; persona-roleplay is wrong shape for a personal harness.
- **Generic framework implementers** (`ISO 27001 auditor`, `GDPR expert`) — fight the source-of-truth / per-org-calibration discipline. Frameworks are context, not citation.
- **Skills that write to memory or CLAUDE.md without explicit user invocation** — violate save-on-mention discipline (save-on-mention hook is the only auto-write path; everything else is human-confirmed).
- **Free-form $ARGUMENTS parsing** without an empty-input behaviour. Skills that hang waiting for input when none was provided are friction.
- **Output without source citations.** Synthesis without provenance is opinion, not insight.
- **Unquoted YAML scalars** in LLM-generated frontmatter.
- **Bash granted without inline wrapper invocation** — the wrapper IS the justification (`.bat`, `python scripts/...`, `ssh <alias>`). Ad-hoc shell without a documented pattern is the 🔴.
- **`curl ... | bash` install of third-party agent frameworks** — borrow patterns, don't install untrusted packages into the harness.
- **Skipping `/fp-check` on first-run findings** — first runs are calibration; verify before acting.

## Co-change couplings

- **New skill produces a new output frontmatter shape** → consider whether `/score-vault` needs an update to recognise it
- **New MCP server added to `.mcp.json`** → run through the MCP evaluation rubric for third-party; or apply secure-code review for local-internal (`scripts/mcp/**`)
- **New hook touches `.claude/settings.json`** → show the diff before applying; confirm permissions and write-path allowlist are tight
- **New scheduled runner added** → wire into the scheduled-audit script so it's caught by the quarterly audit
- **Skill body promoted a memory rule** → consider whether `/promote-rule` should surface it as a path-rule candidate

## See also

- `07-References/security-baselines.md` — C-1..C-8 + §Exemptions register
- `secure-code.md` (path-rule) — fires alongside this one for review skills + flow
- `confidence-tags.md` — convention used on every derived claim
- `.claude/commands/secure-code-review.md` — run before merge
- `.claude/commands/owasp-llm-review.md` — LLM01-LLM10 lens
- `.claude/commands/owasp-agentic-review.md` — ASI01-ASI10 lens
- `.claude/commands/fp-check.md` — false-positive verification gate
- `.claude/commands/curate-skills.md` — propose-don't-apply skill curation
- `.claude/commands/promote-rule.md` — surface memory-rule promotion candidates
