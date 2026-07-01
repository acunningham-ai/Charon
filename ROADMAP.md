# Roadmap

Where Charon is going. Status, rationale, and what isn't on the list.

> Tagging: ✅ done · 🚧 in progress · 📅 planned · 💡 considering · 🚫 won't do
>
> Confidence on external claims: 🟢 verified this turn · 🟡 sourced from research / training data · 🔴 extrapolated. The capability-gap items below cite research that surveyed comparable harnesses in 2026.

---

## Done (recently shipped)

- ✅ 4 always-fire rules + 9 path-conditioned rules
- ✅ 11 hooks (load-rules, save-on-mention with Haiku Stage 2, poisoning-scan, deny-destructive, validate-write-path, validate-memory-frontmatter, voice-anchor-ralph-loop, skill-usage-log, ssh-recovery, notification-toast, check-reauth-flag; plus on-error, invoked by scheduled runners on failure)
- ✅ **Content-graph hygiene lint + workflow tools** (`v0.14.0`, 2026-07-01). `/vault-lint` (broken authored links + tag-taxonomy drift, read-only worklist) + `scripts/migrate-tags.py` (faceted-tag migrator, dry-run by default) + a user-owned faceted `07-References/tag-taxonomy.md` template (the engine reads it; ships no values). Plus `/brainstorm` (divergent→convergent idea generation) and `/systematic-debug` (hypothesis→test→eliminate). Guarded by a new D20 deterministic check; also fixed a latent D2 (the `_poisoning.py` standalone-hook allowlist, unflagged since v0.12.0). Ports proven in the author's harness first, then genericised.
- ✅ **KEV/CVE triage beat** (`v0.13.0`, 2026-06-30). Optional Prometheus pre-step (`scripts/kev-fetch.py`) — fetches the CISA Known-Exploited-Vulnerabilities catalogue, scores recent additions (recency × ransomware × due-date × broadly-deployed-vendor lens; no CVSS — KEV-only), writes a prioritised shortlist to `00-Inbox/_research/` for the digest's bulletin-worthy line. Vendor lens tunable via `--vendors`. Pattern borrowed from hoodinformatik/OpenThreat (AGPL not vendored). Layer 1 (digest-only); bulletin drafting stays human-gated
- ✅ **Runtime prompt-injection / poisoning detector** (`v0.12.0`, 2026-06-29). `UserPromptSubmit` hook (`poisoning-scan.py` + `_poisoning.py`) flags instruction-shaped attacks — override / role-switch / exfiltration / tool-coax / secret-solicit / encoded / special-token — at the choke point where untrusted pasted/fetched content enters. Hardened against confusable-homoglyph + base64/hex-encoded evasion. Observe-only (logs a verdict, never blocks). Closes the *runtime input* surface that the C-1..C-8 baseline (unattended runs) and the on-demand review skills don't cover. Patterns borrowed from microsoft/agent-governance-toolkit + sharma-open-source/opensentry (MIT)
- ✅ 3 MCP servers (vault-readonly, vault-ops, vault-graph)
- ✅ 39 slash commands across reporting / security / the research→compose pipeline / workflow / hygiene + the Cerberus suite
- ✅ Security baseline framework (C-1..C-8)
- ✅ OWASP LLM01-LLM10 + ASI01-ASI10 review skills + `/fp-check` false-positive verification gate
- ✅ First-run wizard (`scripts/first-run.py`) — YAML-defined questions, 5 phases, 39 questions (~25 always-asked + conditional), state-file resume, atomic write
- ✅ Bootstrap installers (`install.ps1` / `install.sh`) with auto/manual/skip per prereq
- ✅ Test suite — 16 LLM-behaviour scenarios + 19 automated deterministic checks
- ✅ ASCII trademark logo banner with auto-detect by terminal width
- ✅ **Local semantic search** — sentence-transformers + bge-micro-v2 (~80MB) + sqlite-vec; `semantic_search` MCP tool in `vault-readonly`; on-demand indexer at `scripts/semantic_index.py`
- ✅ **Knowledge graph** — networkx-backed `vault-graph` MCP server (read-only) with `get_entity` / `stats` tools; Haiku-driven extraction at `scripts/extract_entities.py`; closed entity-type + relationship-type vocabulary (C-3.1)
- ✅ **Multi-agent / subagents** — 7 agents in `.claude/agents/`: 5 review/synthesis subagents (secure-code-reviewer, owasp-llm-reviewer, owasp-agentic-reviewer, knowledge-synthesizer, cerberus) + 2 standing seats (prometheus research, calliope writing); dispatch pattern documented; least-privilege tool grants per agent
- ✅ **Research → compose pipeline** — `/prometheus` (research seat + ledger + newsletter email beat), `/calliope` (writing seat, drafts-only), `/forum-agenda` (recurring-forum feed); first-run `engines` phase seeds beats / senders / forums
- ✅ **Voice input** — local Whisper transcription via `scripts/voice-capture.py` + `/voice-note` slash command; audio never leaves the machine; transcripts land in `00-Inbox/_captured/voice/` as untrusted content per the captures rule
- ✅ **Cerberus — protects the harness itself** (`v0.3.0-preview`, 2026-05-25). 4 slash commands (`/cerberus-{setup,audit,vet,recover}`), 4 model-triggered skills in `.claude/skills/`, 1 subagent, OWASP LLM crosswalk + remediation library under `07-References/cerberus/`, 3 hook scripts (opt-in, not auto-wired). Original by [Joh Leonhardt](https://github.com/JohL29/claude-security-auditor) (MIT); Charon build extends with V0–V8 third-party-artifact threat model, MCP-specific coverage, and remediation library. Closes the install-side surface that the existing review skills (`/secure-code-review`, `/owasp-{llm,agentic}-review`) don't cover
- ✅ **`/cerberus-deps` + supply-chain pinning discipline** (`v0.4.0-preview`, 2026-05-25). New slash command + `audit-dependencies` skill that walks the target project's manifests and cross-references each declared dep against a maintained compromise registry (`07-References/dependency-pinning-discipline.md` — LiteLLM 1.82.7/8, telnyx 4.87.2, tiledesk-server 2.18.6–12, pino-sdk-v2 typosquat, Mini Shai-Hulud cascade). Sibling of `/cerberus-vet` — same registry, recurring own-project surface. V8 layer of `/cerberus-vet` also cross-references the same registry against the artifact being vetted. Borrowed from `usestrix/strix` pinning pattern

---

## Near-term

> The repo is already **public** — items below are no longer gated on a "public flip" (that's happened). They remain the next tranche of work.

### 🚧 R6: Internal-cohort validation

Run the LLM-behaviour scenarios (`test-scenarios/01..10-*.md`) in a **fresh Claude Code session** on a populated install. Open question: who counts as "internals"? Currently undefined — likely some mix of trusted peer CISOs + a clean parallel install of Charon by the author. Target: 9/10 scenarios PASS minimum.

### ✅ R7: Gate 2 git-history credential scrub — DONE (2026-06-09)

gitleaks 8.30.1 scanned all 43 commits of git history: **no real credentials, ever.** The 5 raw hits were all verified false positives — Stripe's official public docs test keys living inside Cerberus's own `known_test_values` suppression list, plus truncated fake placeholders (`sk-proj-abc123xyz789...`) in the threat-analysis prompt and one synthetic test fixture. A scanner's own corpus necessarily contains secret-shaped strings.

Suppression is now handled by `.gitleaks.toml` `[allowlist]`, matched by **literal value** (not by path) so a genuine secret in those same files would still trip. A plain `gitleaks git .` run (no flags) auto-loads the config and returns **no leaks found / exit 0** — the repo is audit-clean for anyone who scans it. (The earlier `.gitleaksignore` glob `cerberus/rules/**` was silently invalid — gitleaks `.gitleaksignore` accepts fingerprints only — and suppressed nothing; replaced.)

### 📅 Plugin-marketplace packaging

Ship Charon as an installable Claude Code plugin bundle, not just a `git clone`-able repo. The 2026 plugin marketplace ecosystem (anthropics/claude-plugins-official, claude-plugins.dev, buildwithclaude.com) is the distribution surface most users actually use 🟡. Without this Charon is invisible to anyone who isn't already in the manual-clone audience.

**Source:** https://code.claude.com/docs/en/plugin-marketplaces 🟡

### 📅 Automatic memory-promotion loop

`/promote-rule` exists as a surface today but the extraction pass that finds candidates is manual. Native Claude Code `/remember` ships a promotion loop that surfaces "you corrected this pattern across N sessions → make it a standing rule" 🟡. Bridge: a scheduled hook reads recent corrections from `~/.claude/history.jsonl`, clusters them, surfaces high-frequency rules as promotion candidates the user can accept.

**Source:** https://code.claude.com/docs/en/memory 🟡

### 📅 Charon-specific README marketing surface

Once public, the README is the recruitment doc. Currently emphasises capability + security baseline; should also surface (a) a 60-second value pitch, (b) screenshots / animated demo, (c) install-in-one-line for the bootstrap script, (d) one or two real-feel example sessions. Visual polish.

### 📅 Credential broker — sanctioned vault→process piping

When the harness operates a deployed service (SSH, `sudo`, remote DB), the credential must reach the process **without ever entering the assistant's context, transcript, or memory.** A broker reads a named secret from the secrets dir and pipes it to the STDIN of a strictly-constrained sink (allowlisted host + closed verb allowlist), behind the ask-gate, with an append-only audit log — value never printed, never in argv, never returned. Proven in the author's harness; generalise the host/verb allowlist for the public release. Closes the "how does an autonomous harness run privileged ops safely" gap that the write-path allowlist (for writes) leaves open for credential-bearing actions.

**Reinforced (2026-06) with a secret-substitution pattern** for the broader case where the harness *acts* on your behalf (mail/calendar/API): a `${keys.NAME}` reference resolves **after** the model emits its action, so the raw secret is never in the model's context, gated by a mandatory per-key destination allowlist. Pattern reimplemented clean from a security evaluation of an agent-UI framework — no third-party code vendored.

---

## Medium-term (3-6 months)

### 📅 Observability + replay layer (Langfuse self-host)

EU AI Act Article 19 requires 6-month log retention; Charon ships `skill-usage-log.py` (a fact, not a tamper-evident ledger linked to governance rationales) 🟡. Field has consolidated to six observability platforms in 2026 (LangSmith, Langfuse, Arize Phoenix, Helicone-now-maintenance-mode, Datadog LLM, Honeycomb LLM). Self-hosted Langfuse fits the on-device discipline. Capability adds: trace every LLM call across hooks + skills, replay a session against a new model to detect behaviour drift, surface anomaly patterns (token-burn spikes, unusual tool dispatch).

**Sources:** https://www.digitalapplied.com/blog/agent-observability-platforms-langsmith-langfuse-arize-2026 🟡 · https://dev.to/arkforge-ceo/the-audit-trail-paradox-why-your-llm-logs-aren-t-proof-1c21 🟡

### 🚧 Self-healing harness watch (verdict-gated)

The lightweight, local-first sibling of the observability item above. Charon already ships the **verdict vocabulary** (`allow`/`deny`/`ask`/`observe` + `monitor` mode) and the `harness-watch-review` skill; the forward arc completes a self-healing loop: a scheduled **watch routine** reads the harness's own health signals (token-cache age, capture freshness, TODO freshness, auth-expiry flags, audit anomalies) and surfaces drift; validated signals graduate `observe → ask` after a shadow window; later, **bounded auto-recovery** writes (re-auth prompts, safe restarts) behind the ask-gate. Phased so each signal earns trust before it can act. Distinct from the Langfuse item: that's heavyweight LLM-call tracing/replay; this is cheap local harness-health self-monitoring.

**Now in progress 🟡** — the watch routine is running a **shadow trial** on the author's harness (observe-only; surfaces what it *would* flag without acting). Auto-recovery stays deferred to two idempotent, post-checkable modes only (re-run a missed capture; re-fire a missed daily refresh) — never credential re-auth, service restarts, or content edits.

### 🚧 Safe self-improvement (verified-signal-only learning)

The counterpart to self-healing: where healing *restores* a known-good state, this *raises the baseline* — the harness learns to keep itself sharp over time. The load-bearing constraint is a **clean-signal gate**: a learning loop may only train on a signal it can **independently verify**, never on its own output (which collapses into self-reinforcing error). First prototype is live on the author's harness — it watches a fully deterministic signal (the harness's own hygiene audit, which can't lie because it's checked against the filesystem), learns which problems *recur*, and proposes a structural fix; whether the fix worked is confirmed by the same deterministic signal, not by the model's say-so. Proves the loop on an unimpeachable signal before it's pointed at anything softer. 🟡

**Source / rationale:** 2026 research that LLMs can't reliably self-correct without external verification, and that training on unverified/own output drives model collapse — so "no clean signal, no learning loop."

Cerberus already grades every finding `validation_status: theoretical | partial | validated` — nothing claims `validated` without a proof-of-concept. Extend the same discipline to `/secure-code-review` + `/owasp-{llm,agentic}-review`: a 🔴 should carry a **reproduction**, not just a `file:line` citation, before it blocks a merge. Raises the bar from "cite the line" to "show it's real" — the defensive mirror of the Artemis proof-by-exploitation principle, and a natural tightening of the existing `/fp-check` gate.

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

### 💡 Artemis — adversarial validation seat (offensive counterpart to Cerberus)

Cerberus is the defensive security seat — it inspects, scores, and reports. **Artemis** is its offensive counterpart: a standing seat that **proves** a risk is real rather than only flagging it — white-box (source-guided) adversarial validation that hunts attack paths and demonstrates them by exploitation in an ephemeral sandbox, then reports only findings backed by a working proof-of-concept. Pipeline shape: recon → parallel vuln-class probes → exploit → evidence-graded report.

**Load-bearing constraint — this is offensive capability, so it ships behind enforced guardrails, not docs:** every engagement runs against an explicit **Rules-of-Engagement allowlist** (authorised targets only, non-prod, written authorisation), behind the harness ask-gate, in a disposable sandbox. Artemis is a legal/authorisation artefact first — adoption routes through the user's own authorisation path, never a quiet install. Heavy lift + governance-gated; the unique-value claim is "a personal harness with a *gated, evidence-first* offensive seat, not just defensive review." Implementation is ours; no third-party offensive code vendored.

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
