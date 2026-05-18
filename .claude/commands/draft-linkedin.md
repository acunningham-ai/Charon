---
description: Claude-native LinkedIn / voice-content drafter — auto-loads voice rule, reads anchors, drafts inline for iteration
argument-hint: "[topic, news hook, or capture path to seed from]"
allowed-tools: Read, Write, Edit, Glob, Grep
---

# /draft-linkedin — interactive voice-driven content drafting

You are drafting a LinkedIn post (or other voice-driven content) in the user's voice. The `linkedin` keyword in this command auto-loads the `voice-content.md` rule — read it before you do anything else. **The rule is load-bearing.**

This command is the **interactive** drafter. Fire-and-forget weekly / on-demand runners (if you have them wired up) live at `capture-pipeline/linkedin-{weekly,on-demand}.bat` and produce N drafts in one shot. This command produces ONE draft you iterate on with the user in the same session.

## Seed
$ARGUMENTS

The seed can be:
- A topic — *"agent identity loop"*, *"the new browser bridge thing"*
- A news hook — *"GitHub policy change April 24"*
- A capture path — *"00-Inbox/_captured/email/.../briefing.md"*
- Empty — ask the user what's on their mind today, or surface 2-3 candidate topics from recent captures

## Process — strict order

### 1. Load voice anchors (NON-NEGOTIABLE)
Per the voice-content rule: **read at least 2 of your voice-anchor files** before drafting. Voice-anchor directory is configured during first-run (typically `08-Projects/LinkedIn-Agent/voice-examples/` or similar). Pick anchors that match the energy of the topic.

**Talk / event transcripts** — use as **premise**, never **copy**. Per the rule, source content is premise, not lift-text.

### 2. Confirm scope with the user
Before drafting, lock in:
- **Format** — short-feed-post (~150-300 words) vs long-form-article (~600-900 words)?
- **Hook structure** — Story Time? Stat lead? Question lead? Scene → gap → action?
- **Audience cue** — *"any GMs in the room"*, *"for those of you running an AI roadmap"* — pick the archetype they're writing AT
- **What's the principle** — the durable thinking they want the post to carry forward (the *premise*, not the source line)

### 3. Source check
If the post will reference real events / products / policies, verify them:
- For news / policy claims, ask the user for the source or check captures
- For dates / numbers, no hallucination — if you're not sure, mark `[VERIFY: …]` and ask before publishing

### 4. Draft inline
Write the draft in the chat (not a file yet). The user reacts in their own voice — that reaction IS the next-draft direction.

While drafting, hold the voice rule in working memory (the user's specific signatures are captured in their voice profile):
- Emphasis moments per their voice (caps / italics / em-dash)
- Their typical sentence-length cadence
- Their recurring metaphors / refrains
- Their closer style
- Some grammatical roughness if their voice calls for it
- Acronyms spelled out: `MCP (Model Context Protocol — …)`

### 5. Self-check (the three questions, calibrated to their voice)
Before showing the user, read it back yourself:
1. Does it have their emphasis moments?
2. Is there a personality moment somewhere (confession / wink / aside)?
3. Does it sound like them, not a brand?

If all three are NO, the voice is too clean — rewrite before showing.

### 6. Iterate
The user will push back. **Watch for the chat-context-vs-post-copy trap** — if their pushback includes personal facts (age, family, feelings, career arc), those are usually the *why* behind the change, not literal copy. Capture the energy, not the personal frame. (See voice-content rule for the worked example.)

### 7. Save when the user approves
Path: `08-Projects/LinkedIn-Agent/drafts/{ISO-week}/{slug}/post-1.md`
- ISO week format: `2026-W19`
- Slug: kebab-case from the topic
- If multiple iterations land, increment `draft_number` rather than overwriting

Frontmatter (mirror your existing convention — see your first published draft for the canonical example):
```yaml
---
draft_number: 1
generated: {today ISO}
format: short-feed-post | long-form-article
word_count: {count}
topic: {short topic line}
hook_structure: {one-line description}
signature_devices: [pull-quote, parenthetical-confession, recurring-metaphor, ...]
sources:
  - vault: {path/to/capture.md}        # if seeded from a capture
  - {url}                              # if seeded from external
audience_check: {who the post is talking to and why now}
---
```

### 8. Don't touch published posts
Files under `08-Projects/LinkedIn-Agent/published/` with `posted:` set are **read-only** per the voice-content rule — except for the post-publication mutable-field set (typically metrics + your private gut-reaction notes).

## Voice traps to avoid (recap of the rule's "don'ts")

- ❌ Direct verbatim from source talks / events
- ❌ Callbacks to events the audience hasn't seen ("as I said at <event>…") — lands as performative
- ❌ Smoothing the user's chat caps into lowercase post copy when caps were emphasis directives
- ❌ Lifting personal-frame chat context (age, family, feelings) as post copy
- ❌ Uniformly tight magazine prose with one polished aphorism per paragraph — unless that IS their voice

If the draft starts feeling like a brand LinkedIn post, **stop and re-read the voice anchors**.
