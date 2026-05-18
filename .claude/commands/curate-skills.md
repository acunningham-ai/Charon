---
description: Review the latest skill-curator report; with user approval, archive stale/dormant skills to .claude/commands/.archive/ (reversible)
allowed-tools: Bash, Read, Glob
---

# /curate-skills — act on the skill curator report

You are acting on the latest report from `scripts/skill-curator.py`. The script runs daily after the capture pipeline and lists skills that haven't been used within the configured thresholds (default: 180d stale, 365d archive candidate — configurable). This slash command reviews that report with the user, then archives approved skills.

Pattern: propose-don't-apply default, no auto-archive, archive folder is the rollback (no tar.gz snapshots needed).

## Recipe

### 1. Find the latest report

```
ls -t "00-Inbox/_reports/skill-curator/" | head -1
```

If no report exists, say so plainly and offer to run `python scripts/skill-curator.py` to generate one.

Note: reports land in `_reports/`, not `_captured/`. The latter is untrusted ingress; the curator is a deterministic analyser whose output is trusted.

### 2. Read the report and surface the action candidates

Show the user the report header (totals + threshold reminder) and the action-candidates table. Don't editorialise yet.

### 3. Per-row triage

For each action candidate, present a one-line judgement:

- **archive-candidate (≥365d):** default recommendation is *archive*, unless the skill is a low-use-by-design tool (quarterly cadence — e.g. `/quarterly-report-prep` — is intentionally rare; archiving it would be wrong).
- **stale (≥180d):** default recommendation is *keep with note*, unless the user confirms the skill is genuinely dead.

Tag every recommendation with 🟢 verified (you've read the skill file this turn) / 🟡 medium / 🔴 assumed per the confidence-tags rule.

When source is "mtime" (no telemetry yet), prefix recommendations with `[mtime-only]` — these are weaker signals and should default to *keep* unless there's other evidence.

### 4. Build an approval table — STOP for confirmation

```
| Skill | Last used | Recommendation | Reason |
|---|---|---|---|
| ... | ... | archive / keep / keep-with-note | ... |
```

Ask: *"Apply these recommendations? (Approve all / Approve subset / Cancel)"*. Do not move any files until the user confirms.

### 5. Apply approved archivals

For each approved archive:

1. Ensure `.claude/commands/.archive/<YYYY-MM-DD>/` exists.
2. Move `.claude/commands/<skill>.md` → `.claude/commands/.archive/<YYYY-MM-DD>/<skill>.md`.
3. Log the decision to `09-Archive/skill-curator-decisions/<YYYY-MM-DD>.md` (append; create if missing): one line per archive with skill name + reason + the user's approval timestamp.

### 6. Restore instructions

After applying, remind the user how to restore: move the file from `.claude/commands/.archive/<date>/<skill>.md` back to `.claude/commands/<skill>.md`. No special command needed.

## Output artifacts

- `.claude/commands/.archive/<YYYY-MM-DD>/<skill>.md` — archived skill (move, not delete).
- `09-Archive/skill-curator-decisions/<YYYY-MM-DD>.md` — append-only decision log.

## When NOT to use

- **Skill is missing — don't reach for /curate-skills.** Restore from `.claude/commands/.archive/` directly. The curator only archives, never deletes.
- **You haven't run the curator script today.** The report is stale; regenerate first with `python scripts/skill-curator.py`.
- **You want to *create* a new skill from a session pattern.** That's `/promote-rule`, not this. The curator only manages the lifecycle of existing skills.
- **You're working around a broken hook.** If skill-usage-log isn't capturing invocations, fix the hook (`scripts/hooks/skill-usage-log.py`) — don't compensate by archiving aggressively.

## Co-change couplings

- New archived skill → consider whether MEMORY.md or any path-conditioned rule (`.claude/rules/*.md`) referenced the skill. Update or remove references in the same approval step.
- After significant archival → run `/score-vault` to catch any cross-refs that now point at archived files.

## See also

- `scripts/skill-curator.py` — the read-only scanner that builds the report.
- `scripts/hooks/skill-usage-log.py` — the PostToolUse hook supplying telemetry.
- `.claude/rules/skill-authoring.md` — what shape new / revised skills should take.
