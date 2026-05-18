# Contributing

Thanks for considering a contribution. This is a small, opinionated project — contributions that align with the harness's philosophy are welcome; ones that fight it will get pushed back on.

## License

This project is MIT-licensed. By contributing, you agree your contributions are MIT-licensed.

## Philosophy

Before opening a PR, read these — they shape what's likely to be accepted:

- **Harness teaches structure; user supplies content.** Rules ship universal patterns (audience-tailoring is required) — they do NOT ship audience names, framework specifics, vendor exceptions, or personnel. Those are user-supplied during first-run.
- **No assumptions** — if uncertain, ask rather than guess in an issue or PR comment.
- **Save on mention** — when you discover a rule or convention through working in the codebase, write it to memory or to a CLAUDE.md the same change.
- **Security baselines apply to harness code itself** — see `SECURITY.md`. New hooks / MCP tools / unattended runners must satisfy C-1..C-8.

## How to open a PR

### Before you start

1. **Open an issue first** for non-trivial changes — saves wasted work if the change isn't a good fit.
2. **Run `/score-vault`** on your branch — confirm you haven't introduced drift in MEMORY.md / CLAUDE.md / rules references.
3. **Run `/secure-code-review <path>`** on any code path you've touched.
4. **For new skills / hooks / MCP tools:** run `/owasp-llm-review` (if LLM-consumer) and `/owasp-agentic-review` (if agentic).

### Branch + commit conventions

- Branch from `main`. Name: `<type>/<short-description>` (e.g. `feat/quarterly-prep-csv-import`, `fix/captures-rule-trust-tag`).
- Commit messages: imperative, present tense. *"Add MCP exemption for local-internal servers"*, not *"Added"* or *"Adds"*.
- One logical change per PR. Bundled refactors get pushed back to be split.

### PR description

Include:

- **What changed** — short
- **Why** — the problem it solves, with reference to issue if applicable
- **Test plan** — what you ran and what passed
- **Breaking changes** — any. Note in CHANGELOG.md.

### Code style

Python:

- Type hints on new functions
- `from __future__ import annotations` if you need 3.9 compat (we target 3.10+)
- No external dependencies beyond `anthropic` and `mcp` without strong justification
- Fail-silent in hooks (`return 0` on any exception); fail-loud in scripts (raise)

Markdown:

- 80-100 char soft wrap is fine; lines longer are fine too if they're tables
- Headings: ATX style (`#`, `##`)
- Code blocks with language fences (` ```python `)

YAML frontmatter on rules / skills / memory files:

```yaml
---
description: <one line, concrete, names the output shape>
argument-hint: <example calls if accepts $ARGUMENTS>
allowed-tools: <minimum set>
---
```

For LLM-generated frontmatter values that may contain colons, em-dashes, or other YAML-special chars: **double-quote the value**. Mid-value `: ` breaks YAML parsing.

## Skill-authoring standard

If your PR adds a new slash command in `.claude/commands/`, the `skill-authoring.md` rule applies. Every new skill should satisfy:

1. **Context-first** — what the skill does and why, in the first 2 sentences
2. **Multi-mode** — interactive vs unattended documented
3. **Reference separation** — skill file <10 KB; deep refs in `references/` next to skill
4. **Confidence tagging on output** — 🟢/🟡/🔴 markers
5. **Proactive triggers declared** if applicable
6. **Output artifacts named** — what files, where, what frontmatter
7. **Quality loop** — review checkpoint or post-run audit
8. **Constraint compliance** — Claude-only by default
9. **Co-change couplings** — what else needs updating when this fires
10. **When-NOT-to-use** section

See `.claude/rules/skill-authoring.md` for the full pattern.

## Rule-authoring conventions

If you're adding or modifying a path-conditioned rule:

- **Trigger discipline** — `paths:` and/or `keywords:`, OR `always: true`. Triggers should be specific enough not to over-fire.
- **Lean over comprehensive** — the harness's convention is rules teach structure, user supplies specifics. Avoid embedding example tier names, example framework calibrations, example personnel.
- **Anti-patterns section** — every rule has one. List the failure modes you've seen.
- **Co-change couplings** — what else might need to change when this rule fires.
- **See also** — pointer to related rules + memory files.

## Hook-authoring conventions

New hooks live in `scripts/hooks/`. They:

- Read from stdin (Claude Code's hook event JSON)
- Write to stdout (becomes additional context) OR stderr (becomes visible message)
- Return exit code 0 (allow) / 2 (block, for PreToolUse) / 1 (warning)
- **Fail silent on internal errors** — log to telemetry, but don't break Claude Code
- Use `from lib.harness_paths import ...` for path resolution
- Use `_telemetry.log_event(...)` for telemetry (fail-silent helper)

## MCP-server conventions

New MCP servers go in `scripts/mcp/`. They:

- Use the `mcp` Python SDK
- Use `argparse` for CLI args, defaulting from `harness_paths`
- Refuse writes to protected paths (`CLAUDE.md`, `MEMORY.md`, `TODO.md`, `00-Inbox/_captured/**`, `09-Archive/**`)
- Refuse to leave VAULT_ROOT via `_safe_resolve()`
- Document every tool in the schema with usage examples
- Are stdio-only by default; HTTP/SSE transports need explicit security review

## What won't get accepted

Without significant motivation:

- New external dependencies beyond `anthropic` and `mcp`
- Persona skills (*"act as a senior CISO"*) — the user IS the user
- Generic framework implementers (*"ISO 27001 auditor"*) — fight the source-of-truth discipline
- Skills that auto-write to memory or CLAUDE.md without user invocation
- Hooks that block Claude Code on internal errors (must fail-silent)
- Vendor-coupling — *"requires Vendor X"* without an "or similar tool" path
- Embedded org-specific calibrations (audience tier names, control counts, etc.) — those are user-supplied
- Unsupervised installs of third-party agent frameworks via `curl | bash`
- Cross-platform regressions — Windows is first-class but contributions must not break macOS / Linux

## Security disclosures

Don't open public issues for security vulnerabilities. See `SECURITY.md` for the responsible-disclosure process.

## Questions

Open a GitHub Discussion, or open an issue tagged `question`.
