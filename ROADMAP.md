# Roadmap

Where Charon is going. Status, rationale, and what isn't on the list.

> Tagging: ✅ done · 🚧 in progress · 📅 planned · 💡 considering · 🚫 won't do
>
> Confidence on external claims: 🟢 verified this turn · 🟡 sourced from research / training data · 🔴 extrapolated. The capability-gap items below cite research that surveyed comparable harnesses in 2026.

---

## Done (recently shipped)

- ✅ 4 always-fire rules + 7 path-conditioned rules
- ✅ 9 hooks (load-rules, save-on-mention with Haiku Stage 2, deny-destructive, validate-write-path, validate-memory-frontmatter, skill-usage-log, ssh-recovery, notification-toast, on-error)
- ✅ 3 MCP servers (vault-readonly, vault-ops, vault-graph)
- ✅ 22 slash commands across reporting / security / workflow / hygiene (incl. `/voice-note`)
- ✅ Security baseline framework (C-1..C-8)
- ✅ OWASP LLM01-LLM10 + ASI01-ASI10 review skills + `/fp-check` false-positive verification gate
- ✅ First-run wizard (`scripts/first-run.py`) — YAML-defined questions, 4 phases, 24 questions, state-file resume, atomic write
- ✅ Bootstrap installers (`install.ps1` / `install.sh`) with auto/manual/skip per prereq
- ✅ Test suite — 10 LLM-behaviour scenarios + 7 automated deterministic checks
- ✅ ASCII trademark logo banner with auto-detect by terminal width
- ✅ **Local semantic search** — sentence-transformers + bge-micro-v2 (~80MB) + sqlite-vec; `semantic_search` MCP tool in `vault-readonly`; on-demand indexer at `scripts/semantic_index.py`
- ✅ **Knowledge graph** — kuzu-backed `vault-graph` MCP server with `get_entity` / `query_graph` / `stats` tools; Haiku-driven extraction at `scripts/extract_entities.py`; closed entity-type + relationship-type vocabulary (C-3.1)
- ✅ **Multi-agent / subagents** — 4 subagent specs in `.claude/agents/` (secure-code-reviewer, owasp-llm-reviewer, owasp-agentic-reviewer, knowledge-synthesizer); dispatch pattern documented; least-privilege tool grants per subagent
- ✅ **Voice input** — local Whisper transcription via `scripts/voice-capture.py` + `/voice-note` slash command; audio never leaves the machine; transcripts land in `00-Inbox/_captured/voice/` as untrusted content per the captures rule

---

## Near-term — before public flip

### 🚧 R6: Internal-cohort validation

Run the LLM-behaviour scenarios (`test-scenarios/01..10-*.md`) in a **fresh Claude Code session** on a populated install. Open question: who counts as "internals"? Currently undefined — likely some mix of trusted peer CISOs + a clean parallel install of Charon by the author. Target: 9/10 scenarios PASS minimum before public flip.

### 📅 R7: Gate 2 git-history credential scrub

Run gitleaks / trufflehog over the entire git history before flipping the repo from private to public. File-level Gate 1 (in-place file scan) is clean ✅; history-level Gate 2 is the irreversible step. Required because once public, force-pushing to remove leaked content is unreliable and observable.

### 📅 Plugin-marketplace packaging

Ship Charon as an installable Claude Code plugin bundle, not just a `git clone`-able repo. The 2026 plugin marketplace ecosystem (anthropics/claude-plugins-official, claude-plugins.dev, buildwithclaude.com) is the distribution surface most users actually use 🟡. Without this Charon is invisible to anyone who isn't already in the manual-clone audience.

**Source:** https://code.claude.com/docs/en/plugin-marketplaces 🟡

### 📅 Automatic memory-promotion loop

`/promote-rule` exists as a surface today but the extraction pass that finds candidates is manual. Native Claude Code `/remember` ships a promotion loop that surfaces "you corrected this pattern across N sessions → make it a standing rule" 🟡. Bridge: a scheduled hook reads recent corrections from `~/.claude/history.jsonl`, clusters them, surfaces high-frequency rules as promotion candidates the user can accept.

**Source:** https://code.claude.com/docs/en/memory 🟡

### 📅 Charon-specific README marketing surface

Once public, the README is the recruitment doc. Currently emphasises capability + security baseline; should also surface (a) a 60-second value pitch, (b) screenshots / animated demo, (c) install-in-one-line for the bootstrap script, (d) one or two real-feel example sessions. Visual polish.

---

## Medium-term (3-6 months)

### 📅 Observability + replay layer (Langfuse self-host)

EU AI Act Article 19 requires 6-month log retention; Charon ships `skill-usage-log.py` (a fact, not a tamper-evident ledger linked to governance rationales) 🟡. Field has consolidated to six observability platforms in 2026 (LangSmith, Langfuse, Arize Phoenix, Helicone-now-maintenance-mode, Datadog LLM, Honeycomb LLM). Self-hosted Langfuse fits the on-device discipline. Capability adds: trace every LLM call across hooks + skills, replay a session against a new model to detect behaviour drift, surface anomaly patterns (token-burn spikes, unusual tool dispatch).

**Sources:** https://www.digitalapplied.com/blog/agent-observability-platforms-langsmith-langfuse-arize-2026 🟡 · https://dev.to/arkforge-ceo/the-audit-trail-paradox-why-your-llm-logs-aren-t-proof-1c21 🟡

### 📅 MITRE ATLAS technique tagging in OWASP review skills

ATLAS v5.4.0 (Feb 2026) shipped 16 tactics, 84 techniques, 32 mitigations — including agent-specific entries like "Publish Poisoned AI Agent Tool" and "Escape to Host" 🟢. Charon's `/owasp-llm-review` + `/owasp-agentic-review` skills tag findings to OWASP categories but not to ATLAS. Adding ATLAS tagging gives findings two-layer provenance (OWASP for what kind of bug, ATLAS for what attack technique). One-day lift — the mapping table exists; the skills just need to render the tag.

**Source:** https://atlas.mitre.org/ 🟢

### 📅 Skill-catalog discovery skill

`stevesolun/ctx` indexes ~91,432 skills, ~10,787 MCPs, 13 harnesses in a queryable LLM-wiki graph 🟡. A new `/discover-skill` slash command that queries this index would close the "what skill should I install" gap that Charon currently doesn't surface. Lightweight skill; uses an external read-only data source.

**Source:** https://github.com/stevesolun/ctx 🟡

### 💡 Code-signed installer + per-release SHA-256

`install.ps1` / `install.sh` currently ship unsigned. The README/INSTALL flow already teaches inspect-first + `RemoteSigned`, but signed binaries are the only fully tamper-evident option for users on `AllSigned` policies (managed enterprise environments) and for users who can't be expected to read the script. Two-step rollout: (1) publish a SHA-256 of `install.ps1` in every tagged GitHub release (zero cost, immediate); (2) acquire a code-signing cert and sign release artefacts (~$300-700/yr for an EV cert from a public CA 🔴 — verify before purchase). Considering rather than planned because (a) cost vs. user base in the validation phase isn't justified yet, and (b) self-signed-cert-with-fingerprint is a cheaper middle option that's worth evaluating before paying for a CA-issued cert.

### 💡 Encryption at rest for memory files

Anthropic docs explicitly note Claude Code artifacts are NOT encrypted at rest 🟡. CISO-relevant. `llmsecrets.com` ships LLM Secrets + Secret Vault skill that encrypts `.env`-style content so Claude never reads plaintext. Charon's memory files contain operational facts the user wouldn't want leaked from a stolen laptop. Considering rather than planned because encryption-at-rest is a significant UX cost (key management, Claude can't read encrypted files without the key being in context, which defeats the point) — needs design before commitment.

**Source:** https://llmsecrets.com/ 🟡

---

## Long-term / strategic (6-12 months)

### 💡 Local-LLM routing for cheap/private tasks

Already on the parked roadmap. Defer non-time-sensitive overnight work (capture triage, weekly synthesis, batch promotion-loop runs) to a local model — Ollama / llama.cpp / vLLM. Keeps Claude budget for interactive day work. Investigation needed: which workloads benefit (vs. where Claude's quality is load-bearing), stack choice, revision of the harness's current Claude-only-by-default stance (any classification rules / content with `classification: confidential` frontmatter would need explicit local-LLM eligibility), LLM08 (vector and embedding weaknesses) coverage, new supply-chain checks (ASI04), separate budget / audit / allowlist for the local-LLM lane. **Hard rule preserved across all stacks:** any local-LLM tier runs in a separate batch lane, never in interactive sessions.

**Sources:** https://medium.com/@karunsharma1920/building-a-local-ai-agent-with-ollama-and-open-interpreter-an-offline-hybrid-assistant-6c8b0ac470b9 🟡

### 💡 Vision / screenshot OCR pipeline beyond text

`/capture-screenshot` exists but processes images as opaque VLM input. SOTA in 2026 (DeepSeek-OCR + VLM-based extraction for tables/charts/layout) would let the capture pipeline structure-extract from screenshots — dashboard snaps become parseable tables, whiteboard photos become structured notes. Two-step pipeline: image → structured extraction → markdown with frontmatter.

**Source:** https://www.bentoml.com/blog/multimodal-ai-a-guide-to-open-source-vision-language-models 🟡

### 💡 Mobile remote bridge integration

Anthropic Remote Control (Feb 2026 research preview) + Happy + AgentsRoom Mobile + Tactic Remote 🟡 all let users drive Claude Code from iOS/Android. Charon is desktop-only. Mobile capture (voice note → save-on-mention) is the killer use case. Integration likely a thin compatibility layer — Charon's existing capture pipeline + first-run wizard need to work against a mobile-initiated session.

**Source:** https://code.claude.com/docs/en/remote-control 🟡

### 💡 Provenance / citation graph for synthesised claims

Charon ships confidence tags (🟢🟡🔴) at the *claim* level. SOTA (`Imbad0202/academic-research-skills` 🟡) ships a 3-layer citation anchor system + trust-chain frontmatter that links every synthesised claim back to source-document spans. For a CISO writing board-level synthesis, citation-back-to-source for every claim is governance gold.

**Source:** https://github.com/Imbad0202/academic-research-skills 🟡

### 💡 Prompt-injection gateway (NeMo Guardrails / Llama Prompt Guard 2)

Production pattern is dual-gate: 20-50ms fast classifier (Llama Prompt Guard 2 86M) then heavier LlamaGuard 3 8B 🟡. Charon's `validate-write-path` hook controls writes; doesn't classify *inbound* captured content for injection-score before it lands in the captures zone. A pre-capture gateway is on the defensive baseline most production agents now ship.

**Source:** https://github.com/NVIDIA-NeMo/Guardrails 🟡

### 💡 Red-team automation (DeepTeam / PyRIT / Garak)

Charon's test suite is 10 LLM-behaviour scenarios + 7 deterministic checks — handwritten, single-shot. SOTA is automated adversarial probing: DeepTeam / PyRIT / Garak running ATLAS techniques as continuous test cases against the harness. Heavy lift but unique value for a security-positioned harness — "this is the only second-brain harness with automated agentic red-teaming."

**Source:** https://www.trydeepteam.com/docs/frameworks-introduction 🟡

### 💡 Calendar / email native beyond M365

Cognosys, mem.ai-era assistants, most personal-AI competitors ship Gmail / Google Cal / Notion natively 🟡. Charon's capture pipeline pattern accommodates these but ships only the M365 reference. Add Gmail / Google Workspace + Notion / Granola / Slack reference implementations as separate runners — keeps the capture-pipeline pattern; expands the surface.

### 💡 Slack / Teams / Discord native bot

Standard in personal-AI for executives who live in chat. Charon's `vault-ops` MCP could expose a `post_to_channel` tool, but the harness-side discipline (don't auto-post anything not human-confirmed) needs design before this ships.

---

## 🚫 Won't do

Explicit exclusions — these would dilute Charon's defensibility or break a load-bearing rule.

| Item | Why not |
|---|---|
| **Persona-roleplay skills** ("Act as a senior CISO") | The user is themselves; persona-roleplay is wrong shape for a personal harness. Captured in `.claude/rules/skill-authoring.md` anti-patterns. |
| **Generic framework auditor skills** ("ISO 27001 auditor", "GDPR expert") | Fight the source-of-truth / per-org-calibration discipline. Frameworks are context, not citation. |
| **Specific named vendor scanner skills** | Charon shouldn't bind to a specific scanner / SAST / dependency-audit vendor. Users with their own scanner wire it via the skill-authoring pattern. |
| **One-click "install all 100+ community skills"** | The skill catalog discovery roadmap item supports recommending skills; auto-installing a third-party pack violates the no-curl-bash rule from `.claude/rules/skill-authoring.md`. |
| **Auto-rewriting the user's existing CLAUDE.md without consent** | First-run wizard preserves user content unless they explicitly choose `wipe`. |

---

## Comparator scan (2026 state of the field)

| Project | What it ships | Where Charon differs |
|---|---|---|
| **affaan-m/everything-claude-code** | 230+ skills, 8 hook events, 29+ rules, AgentShield static analyzer with 102 rules + secret detection + MCP risk profiling 🟡 | Massively wider general-purpose skill catalog; Charon is opinionated-CISO-discipline focused, not general-purpose |
| **rohitg00/awesome-claude-code-toolkit** | Aggregator: 135 agents, 35 curated skills (~400k via SkillKit), 42 commands, 176+ plugins, 20 hooks, 15 rules — bundles claude-mem, Cortex (thermodynamic decay), Supermemory, hybrid BM25+vector retrieval, VibeGuard (88 rules + 13 hooks) 🟡 | Distribution surface Charon lacks; many of the bundled memory/retrieval projects expose capability gaps Charon should pull patterns from |
| **anthropics/skills** | Official source-available demo skills + docx/pdf/pptx/xlsx skills powering Claude.ai document workflows 🟢 | Narrow scope, no memory/capture/governance |
| **coleam00/Archon** | 21.6k stars. "First open-source harness builder for AI coding" — deterministic + repeatable harness assembly | A competitor frame (harness-builder, not personal-AI); deterministic-replay framing is what Charon's test scenarios should aspire to |
| **brianpetro/obsidian-smart-connections** | Local embeddings (bge-micro-v2, 384d, on-device, no API keys), chat-with-vault, semantic Lookup 🟡 | Pure retrieval; no Claude Code integration, no governance, no skills — but the local-embedding pattern is the highest-value gap to close |
| **C-Bjorn/MegaMem** | Obsidian vault → Graphiti-backed temporal knowledge graph + MCP, AI-extracted entities + relationships + timestamps 🟡 | Knowledge graph layer Charon doesn't have |
| **thedotmack/claude-mem** | 5-hook lifecycle memory layer + Bun worker + SQLite + Chroma vector search + web viewer UI, "progressive disclosure" pattern claiming ~10× token saving 🟡 | Memory-as-a-product; lacks the rule/security framework Charon ships but ships retrieval Charon doesn't |
| **stevesolun/ctx** | LLM-wiki recommendation index: 91,432 skills, 10,787 MCPs, 13 harnesses 🟡 | Discovery layer Charon could query |

**Where Charon's bet is sharpest today:** opinionated discipline for executive knowledge work, security baseline depth (C-1..C-8 + OWASP LLM/agentic review skills + FP-check verification gate), tested-not-just-documented (deterministic checks + 10 scenarios), refuse-to-fabricate reporting discipline, document-layering doctrine encoded as rules, persistent voice-content discipline, write-path allowlist for unattended runs.

**Where the roadmap extends next:** retrieval layer (semantic search + knowledge graph), observability + replay, multimodal capture (voice + vision), mobile bridge, plugin-marketplace distribution, automated red-teaming. Most of these are well-trodden in adjacent harnesses — see the medium- and long-term sections above for the specific patterns Charon plans to pull from.

---

## How this roadmap is maintained

Items move between sections as work happens. **The bar to add a roadmap item** is one of:

1. A specific user-reported gap with a concrete use case
2. A capability shipped by ≥2 comparable harnesses that Charon lacks
3. A security or governance requirement that's emerging in the field (e.g. EU AI Act, ATLAS, ASI updates)
4. A pattern Charon's author hits in their own use that would benefit other users

**The bar to mark "Won't do"** is one of:

1. The item conflicts with a load-bearing rule (e.g. Claude-only-by-default conflicts with persona-roleplay)
2. The item would require a different product (cloud-hosted, enterprise-tenanted)
3. The item is a third-party dependency Charon shouldn't bind to (specific vendor scanners)

When a 💡 item moves to 📅, an issue should be opened with a one-paragraph design note. When a 📅 item ships, it moves to ✅ in the next CHANGELOG entry.
