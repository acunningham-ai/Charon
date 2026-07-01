---
name: charon-update
description: Check every Charon update source (Charon harness itself + vendored rule corpora) for upstream changes and apply them. One command, all sources. Manifest-driven via scripts/update/sources.yaml.
---

The user wants to check and apply updates across all Charon update sources. Run the `update-charon` skill.

The skill orchestrates `python -m scripts.update.charon_update`, which:

1. Loads the source manifest at `scripts/update/sources.yaml`
2. For each source, checks upstream for changes:
   - `github-self` — compares local HEAD vs origin/<branch>; offers fast-forward pull
   - `github-vendored` — compares pinned SHA in NOTICE / cerberus/README.md vs upstream HEAD
3. Reports a status summary
4. On user confirmation, applies each available update and runs the source's post-update smoke check. After a `github-self` update it also **ensures the 00-09 base-folder skeleton** exists (idempotent `first-run.py --scaffold-only`), so any newly-added base folders land one-touch — no manual first-run re-run. Best-effort; never fails the update.
5. Leaves the user to review with `git diff` and commit

**One-touch scope:** new commands, scripts, rules, hooks, and docs all arrive with the fast-forward pull. Base folders are ensured automatically (step 4). The only change that still needs a manual step is a new Python dependency — if a release adds one, `pip install -r requirements*.txt` is on you (the update reports it).

Pass `--check` to inspect without applying. Pass `--source NAME` to operate on a single source. Pass `--yes` for non-interactive (CI-friendly) runs.
