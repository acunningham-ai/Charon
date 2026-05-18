---
paths:
  - "08-Projects/LinkedIn-Agent/**"
  - "08-Projects/*Writing*/**"
  - "08-Projects/*Content*/**"
keywords:
  - "linkedin"
  - "draft a post"
  - "voice anchor"
  - "weekly drafts"
  - "on-demand draft"
  - "published post"
  - "newsletter"
  - "blog post"
  - "social post"
---

# Voice-driven content rules

Auto-loaded when working on voice-driven content (LinkedIn posts, blog drafts, newsletters, anything the user ships in their own voice).

**This rule ships the universal patterns.** Your voice signatures, your immutability conventions, your favourite metaphors and refrains — all user-supplied during first-run via a guided voice-profile exercise. The harness can't write your voice for you; it can hold the discipline that keeps the voice intact.

## Hard rules — apply on every draft

| Rule | What it means |
|---|---|
| **Always read voice anchors first** | Before writing or editing, read ≥2 of your voice-anchor files (location configured during first-run — typically `08-Projects/<content-project>/voice-examples/`). These are canonical "this is what I ship". Don't skip. |
| **Published posts are immutable** | Once `posted:` is set in frontmatter, only the post-publication mutable fields (typically metrics + your private gut-reaction notes) are editable. Body content and most frontmatter are frozen. Configure your mutable-field set during first-run; don't widen it. |
| **Source content is PREMISE, not COPY** | If your draft was sparked by a talk you gave, a meeting, a captured email — use the *thinking* as a premise. **Never** lift source lines verbatim. Never signal callbacks the audience can't follow. |
| **Chat context ≠ post copy** | Personal context the user adds in chat (age, family, frame of mind, "I'm 46 and tired") is scaffolding for tone, not literal copy. Caps in chat ≠ caps in post unless emphasis is intentional. |
| **Quote free-text YAML scalars** | LLM-generated frontmatter must wrap free-text values in double quotes — mid-value `: ` breaks YAML parsing and Obsidian renders the block as red error text. |
| **Acronyms spelled out** | Format: `ACRONYM (Spelled Out — plain-English context)`. Undefined acronyms read as gatekeeping. |

## Voice signatures — user-supplied during first-run

The first-run wizard runs a guided voice-profile exercise that captures (at minimum):

- What "emphasis" looks like in your voice — caps? italics? em-dashes? parens?
- Your typical sentence-length cadence — uniform crisp, loose-and-rough, conversational drift?
- Whether you confess in parens, whether you yell words for emphasis, whether you wink at the reader
- Your recurring metaphors / refrains that show up multiple times across the same post
- Your closer style — reflective, punchy, list, question?
- What you DON'T want to sound like — uniformly tight magazine prose, polished aphorisms, etc.

Output: your own `user_voice.md` memory file. **This rule reads that file via its frontmatter pointer or `feedback_voice.md`**, then applies your specific signatures to every draft. Without a populated voice profile, the harness can write competent prose but not *your* prose.

## Chat context ≠ post copy

When the user adds personal context in their messages — about themselves, family, frame of mind — that context is **scaffolding for tone**, not literal copy.

- *"phase one of OUR loop"* (caps in chat for conversational emphasis) → *"phase one of our loop"* (lowercase in post). Caps were chat formatting, not post directive.
- *"I'm a 46 year old man, my daughter would be proud I used 'Don't @ me' correctly"* → post says *"Don't @ me — and yes, I checked"*. The age and daughter were context for the assistant, not post copy.

**Pattern to watch:** any time the user's message includes personal facts followed by a request to change a line — those personal facts are usually telling you **why** they want the change, not **what** to write. Capture the energy, don't transcribe the personal frame.

## Self-check before save

Read the draft back. Three questions (calibrate to your voice profile):

1. Are the emphasis moments yours? (caps / italics / em-dash, however your voice signals)
2. Are there at least one or two moments of personality — confession, wink, aside?
3. Does it sound like *you*, not like a brand?

If the answer is no on all three, the voice is too clean — rewrite.

Plus one structural check: is every free-text frontmatter scalar quoted? If no, fix before save.

## How to run — supporting skills

| Skill | When | What it produces |
|---|---|---|
| `/draft-linkedin` | Interactive drafting from a topic, anchor, or captured event | Voice-matched draft inline for iteration |
| `/linkedin-metrics` | After a post has lived for 48h / 7d | Captures analytics into the published-post's metrics frontmatter |
| `linkedin-weekly-drafts.bat` | Scheduled (your choice of cadence + time) | N candidate drafts for the coming period |
| `linkedin-on-demand.bat` | Ad-hoc, user-triggered | Single draft from a passed-in topic + premise |

## Anti-patterns (auto-flag if I'm drifting)

- **Editing a published post** (anything with `posted:` set) — only your configured mutable fields are editable
- **Smoothing the voice into corporate think-piece prose** — roughness IS the voice for some users
- **Lifting source lines verbatim** — source content is premise, not copy
- **Transcribing chat-context as post copy** — personal facts inform tone, not text
- **Unquoted YAML scalars** containing colons, leading hyphens, or other YAML-special chars
- **Generic / brand-voice prose** — defeats the purpose of voice-anchored drafting
- **Undefined acronyms**
- **One-shot metaphors** when the user's voice profile calls for refrain-style repetition

## Co-change couplings

- **New voice anchor added** → consider whether the user's voice profile needs updating
- **Weekly-drafts prompt updated** → check this rule's frontmatter-quoting and acronym rules still match the prompt's instructions
- **New published post** → confirm immutability rule is being honoured by any future scripts touching the published tree

## See also

- `confidence-tags.md` — used on framing claims in voice content
- `.claude/commands/draft-linkedin.md` — interactive drafter
- `.claude/commands/linkedin-metrics.md` — analytics capture
- User memory (populated during first-run): your `user_voice.md`, `feedback_voice.md`, `feedback_published_post_immutability.md`, `feedback_yaml_frontmatter_quoting.md`
- Your voice-anchor directory (path configured during first-run) — read ≥2 before drafting
