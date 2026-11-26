---
name: charon-update
description: Check every Charon update source (Charon harness itself + vendored rule corpora) for upstream changes and apply them. One command, all sources. Manifest-driven via scripts/update/sources.yaml.
---

The user wants to check and apply updates across all Charon update sources. Run the `update-charon` skill. That skill is hidden from the `/` menu (`user-invocable: false`), so this command is the one update entry the user sees; Claude can still load the skill when the user asks to update in plain words.

The skill runs the updater through Charon's launcher, from the Charon folder:

```bash
sh scripts/hook scripts/update/charon_update.py [--check] [--yes] [--source NAME]
```

The launcher finds `python3`, `python` or `py -3`, whichever this machine has. The updater:

1. Loads the source manifest at `scripts/update/sources.yaml`
2. For each source, checks upstream for changes:
   - `github-self`: compares local HEAD vs origin/<branch> and offers a fast-forward pull. Only **modified tracked files** block it. **Untracked files** (folders the setup wizard made, your own notes) are listed as a warning and do not block; git itself refuses to overwrite one.
   - `github-vendored`: compares the pinned SHA in NOTICE / cerberus/README.md vs upstream HEAD
3. Reports a status summary
4. On user confirmation, applies each available update and runs the source's post-update smoke check (a smoke starting with `python` runs on the updater's own interpreter).
   - A vendored corpus update is **all or nothing**: it checks every upstream path exists first, stages the copies, swaps them in, and only then re-pins the SHA. Any failure rolls everything back and says *"nothing was changed"*.
   - After a `github-self` update it **ensures the 00-09 base-folder skeleton** exists (idempotent `first-run.py --scaffold-only`), so any newly-added base folders land one-touch. Best-effort; never fails the update.
   - It then prints **"New in this update"**: one plain-language line per capability just received (from `scripts/capability-notes.json`, each shown once). If one of them needs a setting, it tells the user to run `python scripts/first-run.py --catch-up`, which asks only those questions. Relay that list to the user in plain words; don't summarise it away.
   - Finally it **re-checks the Claude Code wiring** (`scripts/post_install_wiring.py --mode update`): the Agent Org pane and the status line. If either is not wired, it prints a block of `!!` lines with the exact fix. **Tell the user first and plainly** when wiring is `NOT COMPLETE` or `NOT CHECKED`; the update still applied.
5. Leaves the user to review with `git diff` and commit

**One-touch scope:** new commands, scripts, rules, hooks, and docs all arrive with the fast-forward pull. Base folders and Claude Code wiring are checked automatically (step 4). The only change that still needs a manual step is a new Python dependency: if a release adds one, `pip install -r requirements*.txt` is on you (the update reports it).

Pass `--check` to inspect without applying. Pass `--source NAME` to operate on a single source. Pass `--yes` for non-interactive (CI-friendly) runs; the wiring step then never asks and leaves a status line you chose in place.
