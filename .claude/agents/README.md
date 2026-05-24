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
