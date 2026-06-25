---
name: update-charon
description: Check every Charon update source (harness self + vendored rule corpora) and apply available updates. Reads scripts/update/sources.yaml; handles github-self (the Charon repo) and github-vendored (Cisco rule corpus, future borrows). Idempotent — re-running when up to date is a no-op.
---

# Update Charon — one command, all sources

You are running the **/charon-update** flow. This is the single user-facing command for keeping Charon and its vendored content current with upstream.

## What the user wants

A single, easy-to-use command that:

1. **Looks at every updateable source Charon knows about** — the harness itself, vendored rule corpora (currently Cisco's skill-scanner), any future borrows added to the manifest
2. **Reports clearly** what's up to date vs what has updates pending
3. **Applies cleanly** with user confirmation — no silent overwrites
4. **Verifies via smoke tests** — each source can declare its own post-update sanity check
5. **Leaves the user in control** — does NOT auto-commit; user reviews `git diff` and commits

## How it works

The mechanism is **manifest-driven**. The source-of-truth is `scripts/update/sources.yaml` at the Charon repo root. Each entry has:

- `name` — short identifier
- `description` — human-readable
- `type` — dispatches to an update strategy
- Type-specific config — `repo`, `branch`, `copy_paths`, `sha_pin_files`, etc.
- `post_update_smoke` — shell command to run after a successful update

Supported `type` values:

| Type | What it does |
|---|---|
| `github-self` | Compares local `HEAD` to `origin/<branch>` AND classifies the kind of update available. Reads the **nearest semver tag** reachable from local HEAD (`git describe --tags`) and the **highest semver tag** on origin (`git ls-remote --tags`). If they differ, the update is a **capability update** (new release tag — `v0.7.0 → v0.8.0`); otherwise it's **in-flight commits** past the latest tag (bug fixes, small refinements). If working tree is clean AND local is a strict ancestor of upstream, offers `git pull --ff-only`. Blocks on divergent commits or uncommitted changes with a clear reason. |
| `github-vendored` | Reads the currently pinned SHA from `sha_pin_files`. Compares against the upstream branch HEAD via GitHub API. If newer: shallow-clones upstream, copies the configured `copy_paths` into the local tree (overwriting), rewrites the SHA pin in every `sha_pin_files` entry, runs the post-update smoke check. For Cerberus's rule corpus, this is a **detection-rule refresh** — new / updated YARA, signatures, or policies. |

## Procedure

### 1. Confirm scope with the user

Ask if they want to check / apply all sources, or just one. Common forms:

- *"Update everything"* → run without `--source`
- *"Just the Cisco rules"* → `--source cisco-rule-corpus`
- *"Check what's available, don't apply"* → `--check`

If the user doesn't specify, default to *all sources, interactive (will prompt before each apply)*.

### 2. Run the check

```bash
python -m scripts.update.charon_update [--check] [--source NAME]
```

Output is a per-source status block:

```
Charon update check
  manifest: .../scripts/update/sources.yaml

  ✅ charon: up to date (891330c...)
  ⏫ cisco-rule-corpus: update available
     pinned  : ff708ea000
     upstream: abc1234567
```

If everything is up to date, the command exits 0 with *"All sources up to date"*. Tell the user that and stop.

### 3. Show the user what's available, then apply

If updates are available and the user wants to apply:

```bash
python -m scripts.update.charon_update         # interactive — prompts before each
python -m scripts.update.charon_update --yes   # non-interactive
```

The script prompts:

1. *"Apply N updates?"* (overall confirmation)
2. For each source, source-specific confirmation (e.g. *"Apply: git pull --ff-only origin main?"*)

### 4. Review results

After all sources are processed, the script prints a results summary including:

- Which sources applied
- Smoke-test outcome per source (`PASS` / `FAIL`)
- *"Review with git diff before committing"*

**Don't auto-commit.** The user reviews `git diff`, runs `git add`, commits manually. Charon's pre-publish checklist (`project_harness_publish_checklist.md`) still applies to any commit that pushes vendored content.

### 5. If smoke fails

If a `github-vendored` source's post-update smoke check fails (e.g. the new corpus contains a regex the engine can't parse), the script prints:

> *"⚠️ smoke: FAIL — review changes carefully before committing"*

This is a signal to:
- Run the smoke test directly: `python -m cerberus.engine.smoke_test`
- Read the warnings and decide if the rule loss is acceptable
- Optionally: `git checkout -- cerberus/rules/` to revert the corpus changes, file an issue upstream

## Adding a new update source

To add a new vendored corpus or registered project to the update flow:

1. Open `scripts/update/sources.yaml`
2. Add an entry with the appropriate `type`
3. Run `python -m scripts.update.charon_update --source <new-name> --check` to verify the manifest entry works

No code changes needed unless the source needs a brand-new type (e.g. `gitlab-vendored`, `npm-package`). New types require extending `scripts/update/charon_update.py`.

## Failure modes

- **Network unreachable** — `upstream check failed: <urllib error>`. Tell user, no changes made.
- **Charon has divergent commits** — `github-self` reports `diverged`, doesn't offer pull. Tell user *"your local clone has commits not on upstream; resolve manually with `git pull --rebase` or merge before re-running"*.
- **Uncommitted changes** — same handling: report, don't apply.
- **SHA pin mismatch** — `_read_pinned_sha` returns None if pin files have conflicting SHAs. Surface as error, ask user to reconcile manually.
- **Cisco moves directory structure** — copy fails. Smoke test will then fail. Surface in the result; user reverts via `git checkout -- cerberus/rules/`.

## What this skill does NOT do

- **Doesn't auto-commit.** Ever.
- **Doesn't push.** The user pushes manually after review.
- **Doesn't update the manifest itself.** Adding sources is a deliberate human action.
- **Doesn't run Cerberus-vet on updated corpora.** That's a separate /cerberus-vet invocation if the user wants to re-vet after pulling a new SHA.
