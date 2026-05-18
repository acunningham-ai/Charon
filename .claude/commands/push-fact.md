---
description: Natural-language fact → identify the right vault file → make a targeted patch edit. Inverse of /score-vault.
argument-hint: "<fact in natural language>, e.g. 'vuln scanning confirmed live in all <region>' or '<Person> now Tier 2 not Tier 1'"
allowed-tools: Read, Glob, Grep, mcp__vault-ops__patch_note, mcp__vault-ops__frontmatter_query, mcp__vault-ops__manage_tags
---

# /push-fact — natural-language fact routing into the vault

You are routing a natural-language fact from the user into the right vault file with a surgical edit. This is the inverse of `/score-vault` — score-vault finds drift; push-fact resolves drift before it accumulates.

## Scope

$ARGUMENTS

If $ARGUMENTS is empty, stop and ask: *"What's the fact? Examples: '<Person> promoted to Director', 'Anthropic CISO call moved to 18 May', 'add gotcha tag to feedback_X.md', '<Project> Stage 2 paused'. Be specific about the fact."*

If provided: treat the full $ARGUMENTS as the fact statement.

## Recipe

### 1. Parse the fact — what kind is this?

Classify into one of these shapes:

| Shape | Example | Likely target |
|---|---|---|
| **Update a memory file** (rule / people / project) | "<Person> promoted to Director" | `~/.claude/projects/<...>/memory/reference_person_<slug>.md` |
| **Update a project card** | "<Project> Stage 2 paused" | `08-Projects/<Project>/README.md` or card file |
| **Update a framework doc** | "Add <topic> to the <doc> agenda" | `07-References/<slug>.md` |
| **Update a decision record** | "Decided <date> to skip <option>" | `06-Decisions/<file>.md` |
| **Add a tag to an existing memory** | "tag feedback_X.md with [gotcha]" | memory file via `manage_tags` |
| **Goes to dashboard, not vault** | "<Unit> Q1 score = 68" | User updates the source-of-truth dashboard; suggest the URL, don't write to vault |
| **Belongs in TODO** | "Need to call <Person> tomorrow about contract review" | `TODO.md` — but `/push-fact` does NOT write TODO; surface as a candidate |

**Per the vault-vs-source-of-truth principle:** structured ground-truth facts (scores, control statuses, vendor ratings) go to the dashboard, not the vault. If the fact is shaped like a dashboard row, stop and tell the user to update the dashboard — don't fabricate a vault location.

### 2. Search for the target

Use `frontmatter_query` (MCP) or `Grep` / `Glob` to find the most likely file. For people facts: search memory dir for `reference_person_*.md`. For project facts: search `08-Projects/<slug>/`. For framework facts: search `07-References/`.

Show the user your top 1–3 candidate paths with a confidence rating:

> Candidate target(s):
> 1. `path/to/file.md` — high confidence (matches person name + tier-1 frontmatter)
> 2. `path/to/alt.md` — medium confidence (mentions same person but for a different context)
>
> Going with #1 — confirm?

### 3. Propose the patch — STOP HERE for confirmation

Show the user the EXACT patch you intend to apply:

```yaml
patch_note:
  path: <target path>
  frontmatter_patch:
    {key: new_value, ...}   # if updating fields
  body_search: "<exact existing string>"
  body_replace: "<replacement>"
  # OR
  body_append: "<text to add>"
```

Ask: *"Apply this patch?"* — **do not call the MCP until the user confirms.**

### 4. Apply via vault-ops MCP

Use `mcp__vault-ops__patch_note` (or `mcp__vault-ops__manage_tags` for tag-only updates).

The MCP will:
- Refuse writes to protected files (CLAUDE.md, MEMORY.md, TODO.md).
- Refuse writes under `00-Inbox/_captured/**` or `09-Archive/**`.
- Enforce the tag allowlist on `manage_tags`.

If the MCP returns BLOCKED, stop and tell the user why.

### 5. Confirm + co-change

After successful patch:
- State what changed in one line.
- Suggest co-change couplings per `CLAUDE.md`: e.g. "this person's tier just changed — should I bump the `reference_key_people.md` routing index?" Do not auto-apply co-changes; surface as questions.

## Constraints

- **One target per call.** If the fact implies updating 3 different files, propose them sequentially with separate confirmations. Don't batch.
- **No memory-content writes.** Memory files have a specific structure; `/push-fact` can patch frontmatter or surgical body sections, but not rewrite a memory file wholesale. For new memory files, use `/save-feedback`.
- **Cite the source.** When the patch is applied, leave a footprint — typically the body_append includes a one-line note like `<!-- pushed YYYY-MM-DD via /push-fact -->` so future audits know the origin. Don't add this to frontmatter; it pollutes the schema.
- **Don't push to the dashboard / external source of truth.** Vault only.

## Done criteria

- Fact parsed into a known target shape.
- Target file(s) identified with confidence rating.
- Patch proposed and the user confirmed before MCP call.
- MCP returned success.
- Co-change couplings surfaced as questions, not auto-applied.

## When to use

- "I just heard X" — quick fact that has a known home in the vault.
- After a meeting where the user wants to update a person's profile, a project card, or a framework doc with a specific change.
- When you have a tag to add or remove from a known file.

## When NOT to use

- For new memory entries — use `/save-feedback` or write the file directly.
- For new framework docs — use `/knowledge-consolidate`.
- For dashboard updates — go to the dashboard.
- For TODO additions — surface them; let next `/refresh-todo` pick up.
- For captures — the capture pipeline handles those automatically.
