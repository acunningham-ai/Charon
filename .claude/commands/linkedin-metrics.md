---
description: Capture LinkedIn analytics for a published post — 48h or 7d snapshot
argument-hint: "[optional: post slug e.g. '2026-W19-agent-identity-loop' (default: list posts due for snapshot)]"
allowed-tools: Read, Edit, Glob
---

# /linkedin-metrics — log post analytics

You are capturing LinkedIn analytics into the frontmatter of a published post under `08-Projects/LinkedIn-Agent/published/`.

## Convention (already in use — don't reinvent)

Each published post has two metrics blocks in frontmatter:
- `metrics_48h:` — captured ~48h after publish
- `metrics_7d:` — captured ~7 days after publish (sometimes slipping to 8d)

Each block has these fields (DO NOT change the schema):
```yaml
metrics_48h:
  taken_at: 2026-05-09          # ISO date OR `not_captured` if window missed
  impressions: 10958
  members_reached: 8070
  reactions: 38
  comments: 5
  reposts: 9
  saves: 12
  sends_on_linkedin: 5
  social_engagements_total: 69
  profile_views_from_post: 13
  followers_gained: 6
  engagement_rate_pct: 0.47       # narrow = (reactions+comments+reposts) / impressions * 100
  engagement_rate_full_pct: 0.63  # broad = social_engagements_total / impressions * 100
```

Plus optional:
- `gut_reaction:` — the user's qualitative reaction in their words (capture verbatim, don't smooth it)
- `notes:` — anything noteworthy (one sales-pitch comment, a particular sender, etc.)

## Process

### 1. Identify the post
$ARGUMENTS

If empty, list candidate posts:
```
Glob: 08-Projects/LinkedIn-Agent/published/*.md
```
Read frontmatter, surface posts where:
- `posted` date is between 36h and 60h ago → due for **48h** snapshot
- `posted` date is between 6 and 9 days ago → due for **7d** snapshot
- Either block exists with `taken_at: not_captured` → already missed; flag but don't re-prompt

### 2. Prompt for the analytics paste
Show the user the post (sender, hook, posted date), tell them which window we're capturing (48h or 7d), and ask them to paste the LinkedIn analytics dump:

> Paste the analytics — I need: impressions, members reached, reactions, comments, reposts, saves, sends, social engagements total, profile views from post, followers gained.

### 3. Compute engagement rates yourself
The two engagement rate fields are derivable — compute them, don't ask the user:
- `engagement_rate_pct = (reactions + comments + reposts) / impressions * 100` (round to 2dp)
- `engagement_rate_full_pct = social_engagements_total / impressions * 100` (round to 2dp)

Keep the formula comments in the YAML.

### 4. Edit the post
Use `Edit` to update the right metrics block. Set `taken_at:` to today's date. Don't touch the post body — those are read-only after `posted:` is set per the voice-content rule. **Frontmatter metrics blocks are explicitly designed to be filled in over time, so editing them is fine.**

### 5. Capture the user's reaction
After saving, ask: *"Anything notable to log in `gut_reaction:` or `notes:`?"* — keep the answer verbatim, don't smooth into magazine prose.

## Self-checks
- Did you preserve the schema exactly? (Field names, order, comment lines)
- Did you compute both engagement rates?
- For 7d snapshots, did you check whether the 48h block was filled in or marked `not_captured`?
- Did you avoid touching the post body?
