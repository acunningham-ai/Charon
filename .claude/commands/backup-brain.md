---
name: backup-brain
description: Back up or restore your brain to an offline drive. Covers the half nobody syncs — ~/.claude memory, session history and pipeline state — so a new machine gets your brain, not just your notes. Also the migration path when moving computers.
argument-hint: "[status | restore | dry-run]"
allowed-tools: Bash(python scripts/backup-brain.py *), Read
---

# /backup-brain — take your brain to the new machine

## Why this exists

A brain has two halves and they live in different places:

| Half | Where it lives | Usually synced? |
|---|---|---|
| **Your notes** (the vault) | Dropbox / OneDrive / iCloud / git | ✅ almost always |
| **What the harness learned** (`~/.claude`) | a hidden home-directory folder | ❌ almost never |

Half two is the memory files, the session history and the pipeline state — everything
the harness has learned about how *you* work. No sync tool touches it, because nobody
thinks to point one at a dotfolder.

So the failure mode isn't dramatic. You set up a new laptop, your notes are all there,
and the brain is quietly amnesiac. This command is the fix.

## Usage

```bash
python scripts/backup-brain.py              # back up to the marked drive
python scripts/backup-brain.py --dry-run    # show what would copy, write nothing
python scripts/backup-brain.py --status     # when did a backup last SUCCEED?
python scripts/backup-brain.py --restore    # restore onto this machine
```

## One-time setup

Create a marker file in the root of the drive you want to use:

```
Windows   D:\.charon-backup-target
macOS     /Volumes/<name>/.charon-backup-target
Linux     /media/<user>/<name>/.charon-backup-target
```

The drive is found by that marker, **never by drive letter or mount path** — those change
between machines and reboots, which is exactly the situation a migration tool has to
survive.

## What gets copied

- `~/.claude` — memory, session summaries, transcripts
- the capture-pipeline directory — including its state and cursors
- your vault, if `HARNESS_VAULT` is set

**Never copied:** credentials, daemon keys, token caches, `node_modules`, virtualenvs.

## Moving your credentials — you do this part, on purpose

**There is no option to back up your secrets. Not a flagged one, not a guarded one.**

That is a deliberate design decision, not an oversight. This tool cannot encrypt, and
running as a normal user it cannot verify that your drive is encrypted — reading BitLocker
status needs administrator rights, and FileVault and LUKS are equally opaque without
elevation. So a "copy my secrets" option would be an unprotected copy wearing a warning
label. Warning labels lose to convenience eventually; a missing feature does not.

What you get instead: every backup writes **`SECRETS-INVENTORY.json`** — the filenames,
sizes, dates and the *shape* of each credential file (a description field if it has one,
otherwise just the key names). **Never a value.** It answers the question that actually
blocks you on a new machine: *what did I have?*

Then move them yourself, once, deliberately. In rough order of preference:

1. **Re-issue them.** Best option where the provider allows it. A credential that has
   never travelled cannot have been intercepted in transit, and you get rotation for free.
2. **Your password manager.** Most already sync securely and are built for exactly this.
3. **An encrypted volume you control** — BitLocker To Go, FileVault, LUKS, an encrypted
   archive. Handle it as a distinct task, not as a side effect of a weekly job.

The one case worth planning ahead for is a credential you **cannot** re-issue — a
one-time-view key with no reset path. Identify those *before* you wipe the old machine.
The inventory is what tells you they exist.

> **Restore never writes credentials either.** After a restore, re-authenticate the
> capture pipeline and recreate your secrets directory. The restore output reminds you.

## Restoring — and the question it asks you

`--restore` is offered automatically by `install.ps1` / `install.sh` when a marked drive
is plugged in, **before** the first-run wizard, so a migrating user isn't asked questions
they already answered on the old machine.

If a vault already exists at the target, restore stops and asks whether you still have
access to the cloud sync behind it:

- **Yes** → it skips the vault. Your notes are already on their way; restoring on top of a
  live sync folder causes conflicts and duplicates.
- **No** (left the employer, dead tenant, closed account) → it restores the vault from the
  drive, because that copy is now the only one.

A cloud folder sitting on disk does **not** prove you still have access to the account
behind it — someone who has left a company still has the folder. Only you know which case
you're in, so it asks rather than guesses. Use `--vault restore|skip` to answer up front
in a script.

Restore also refuses to write over non-empty targets unless you pass `--force`.

## Silence is not success

The drive is usually stored somewhere safe, so most scheduled runs legitimately find
nothing. A job that quietly no-ops in that situation looks identical to a job that has
been broken for months.

So every run records `last_attempt` **and** `last_success` separately in
`state/last-brain-backup.json`. Liveness checks must judge `last_success` — never the log's
mtime, which stays fresh forever while nothing is actually being backed up.

Check it any time with `--status`.

## Scheduling

Wire `backup-brain.py` to run weekly. On Windows set the task's **"Run task as soon as
possible after a scheduled start is missed"** — otherwise a run scheduled while the machine
is asleep is simply refused, and the backup silently never happens.

## When NOT to use

- **Not a version-control substitute.** It mirrors current state; it has no history. Keep
  your vault in git if you want that.
- **Not off-site.** A drive next to the laptop shares the laptop's fire and flood. Store it
  somewhere else.
- **Not for secrets.** By design. Re-auth instead.

## Co-change couplings

- New secret-bearing path appears under `~/.claude` → add it to the exclusion lists in
  `scripts/backup-brain.py` (`EXCLUDE_NAMES` / `EXCLUDE_DIRS` / `EXCLUDE_SUFFIXES`).
- Install flow changes → keep the restore step in `install.ps1` **and** `install.sh` in step.
