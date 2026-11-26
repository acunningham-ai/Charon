# Installing Charon

Charon is a CISO harness. We teach security-hygiene discipline through the rules, so we model it from the install instructions: **read the script before you run it**, and run it under the least-permissive policy that works.

## ⚠️ Known issues in v0.37 (fix in progress)

A fresh install on Linux can come up only partly working. Until the fix ships, check these after install:

1. **Every hook needs a `python` command.** Charon's hooks run `python`, and many Linux distributions
   ship only `python3`. Without `python`, no hook runs: rules don't load, start-up checks don't run and
   the safety gates are off. Check with `which python`. If nothing prints, on Debian or Ubuntu run
   `sudo apt install python-is-python3` (on other distributions, make `python` point at `python3`).
2. **Agent Org may not be switched on.** If there is no `/agent-org` command, run
   `python3 scripts/agent_org_setup.py` in the Charon folder, then quit and restart Claude Code.
3. **Requests are not yet routed to Zeus automatically.** The agents load, but nothing sends work to
   them. Ask for him by name ("Zeus, ...") until the routing rule ships.
4. **The Cisco rule-corpus update fails part way.** Update Charon itself only, for now:
   `python3 -m scripts.update.charon_update --source charon`. If a Cisco update already failed,
   `git checkout -- cerberus/` restores the shipped rules.
5. **Two update entries in the `/` menu.** `/charon-update` and `/update-charon` run the same thing.

## Quick start

Clone the repo (anywhere — outside cloud-synced folders is faster).

```bash
# macOS / Linux
git clone https://github.com/acunningham-ai/Charon.git "$HOME/second-brain"
cd "$HOME/second-brain"
```

```powershell
# Windows (PowerShell). Don't use `~/second-brain` — git is a native command and
# won't expand the tilde; you'll end up with a literal `~` directory.
git clone https://github.com/acunningham-ai/Charon.git "$env:USERPROFILE\second-brain"
cd "$env:USERPROFILE\second-brain"
```

**Step 1 — Inspect the installer.** Open `install.ps1` / `install.sh` in your editor. Each is several hundred lines, most of it comments and messages; the header comment at the top summarises every flag, environment variable and exit status. You're checking: which package manager it invokes, where it writes (your secrets folder, `~/.secrets/` by default, and on a protected Python the private virtual environment `~/.charon-venv`), and what Python deps it pulls.

**Step 2 — (Optional) verify integrity.** Every tagged release publishes a SHA-256 of `install.ps1` in the release notes. Compare:

```powershell
# Windows
Get-FileHash install.ps1 -Algorithm SHA256
```

```bash
# macOS / Linux
shasum -a 256 install.sh
```

Mismatch → don't run; open an issue.

**Step 3 — Run.**

```powershell
# Windows — RemoteSigned is the least-permissive policy that runs a locally-cloned script.
# git clone does NOT mark files with the internet Zone.Identifier, so RemoteSigned accepts it.
powershell -ExecutionPolicy RemoteSigned -File install.ps1
```

```bash
# macOS / Linux
bash install.sh
```

**Fallback for locked-down Windows machines.** If your policy is `AllSigned` (uncommon outside managed enterprise environments), `RemoteSigned` will reject the unsigned script. After you've inspected it:

```powershell
powershell -ExecutionPolicy Bypass -Scope Process -File install.ps1
```

`-Scope Process` confines the bypass to the single invocation; it does **not** change your machine or user policy. Avoid the older `-ExecutionPolicy Bypass` without `-Scope Process` — same blast radius for this run, but easier to copy-paste into other contexts without thinking.

The bootstrap installer:

1. Detects **Python 3.10+**, searching `python3`, then `python`, then `py -3`: the same order as the hook launcher (`scripts/hook`), so the Python that gets the packages is the one the hooks run. Offers auto-install via `winget` / `brew` / `apt|dnf|pacman`, OR shows the install URL for manual install, OR skips.
2. Detects **Obsidian**; same auto / manual / skip choice. Optional — Charon works with any markdown editor.
3. Detects **Node.js 18+** (needed only by the email capture pipeline); same choice.
4. Installs Python deps from `requirements.txt` (PyYAML, anthropic, mcp). If your Python is protected by your operating system (see [Protected Python](#protected-python-pep-668-charons-private-virtual-environment) below), it never forces an install into it: it makes Charon's private virtual environment and installs there instead.
5. Creates your **secrets directory** with restricted permissions (`~/.secrets/` by default).
6. Looks for a Charon backup drive and offers to restore it (see *Moving from another computer?* below).
7. Hands off to `scripts/first-run.py` — the interactive wizard, which now offers a **Quick path (4–6 questions, ~2 minutes) or Full path (39 questions, ~20 minutes)** at the top. Pick Quick to get productive immediately and refine any phase later; pick Full if you already know how you want the harness configured. See [`FIRST-RUN.md`](FIRST-RUN.md) for details.

At the end it checks again that PyYAML and mcp import for the Python in use, and exits with status 3 if either is still missing, so an install that only half worked never reports success.

### Protected Python (PEP 668): Charon's private virtual environment

Many Linux distributions (and Homebrew's Python) mark their Python as *externally managed* (PEP 668): the distribution owns its packages, and pip refuses to install into it. The installer checks for that before running pip (`install.sh` also recognises pip's own refusal if the check missed it).

On such a Python it **never** passes `--break-system-packages`. Instead it:

1. creates a private virtual environment with that same Python, at `~/.charon-venv` (`%USERPROFILE%\.charon-venv` on Windows);
2. installs `requirements.txt` into it;
3. runs the restore step and the first-run wizard with the venv's python.

**The hooks and MCP servers use it on their own.** The hook launcher (`scripts/hook`, and `scripts/hook.cmd` on Windows) tries the venv's interpreter first: `bin/python3`, then `bin/python` (on Windows, `Scripts\python.exe`), and only then searches `PATH` as before. You do not need to activate the venv before starting Claude Code. The installer still prints the activate command; it is only needed when you run Charon's scripts by hand (`python scripts/...`), or run them with the venv's python directly, e.g. `~/.charon-venv/bin/python scripts/score-vault.py`.

The launcher uses the venv's interpreter only if it really is Python 3: it must print a check value when run, so a broken venv, or a venv that is a link to something else, is skipped and the `PATH` search runs instead. A link (symlink or junction) to a real venv is fine. To stop using the venv, delete the `~/.charon-venv` folder.

If making the venv or installing into it fails, the installer says so loudly, prints the exact fix (your distribution's package, or the venv commands to run yourself), carries on to the wizard, and exits with status 3 at the end.

### Refusals: root, elevated and piped runs

The installer refuses to start, before it does anything, in two cases:

| Case | Exit | Why |
|---|---|---|
| Run as root (`sudo bash install.sh`), or in an elevated "Run as administrator" PowerShell | **77** | Charon installs for one user. A root or elevated run would leave the secrets folder, packages and venv owned by root or the administrators group. Run it as yourself; on Linux it asks for `sudo` itself, only when a package manager needs it. On Windows, `winget` installs per-user. |
| Piped in from the network (`curl ... \| bash`, `bash -s`, `irm ... \| iex`, or a PowerShell script block) | **66** | A piped script has no folder of its own, so it cannot find the Charon files, and every question would read the rest of the script as its answer. Clone or download Charon, read the script, then run it as a file. |

### Exit status

| Status | Meaning |
|---|---|
| 0 | Finished, and the required Python packages import. |
| 3 | Finished, but PyYAML or mcp is still missing (the fix was printed in Step 4). On Windows, also: Python was just installed by `winget` and this window cannot see it yet; open a new terminal and run the installer again. |
| 64 | Bad command-line arguments, including an `--answers` / `-AnswersFile` that is not a readable file. |
| 66 | Refused: piped run. |
| 77 | Refused: root or elevated. |
| other | A step failed, or the first-run wizard's own exit status. |


> **Moving from another computer?** Plug in your Charon backup drive before running the
> installer. It detects the drive and offers to restore your memory, session history and
> pipeline state **before** the first-run wizard - so you are not asked questions you already
> answered. Credentials are never restored; re-authenticate afterwards. See `/backup-brain`.

## What the bootstrap script asks you

For each prerequisite that's missing:

```
(a)uto-install / (m)anual install (open URL, then re-run) / (s)kip
```

- **Auto** runs your platform's package manager. No admin elevation on macOS (brew); Linux `apt`/`dnf`/`pacman` will prompt for sudo when needed; Windows `winget` runs per-user.
- **Manual** opens the install URL in your browser. You install, then re-run the bootstrap.
- **Skip** continues without that prereq — useful when you already have a custom install (e.g. pyenv, asdf, mise) that the script doesn't see.

## Non-interactive install, answers file and dry run

| What | Windows | macOS / Linux |
|---|---|---|
| Answer every **installer** question with its default (the wizard still asks its own) | `-AcceptDefaults` | `ACCEPT_DEFAULTS=1` |
| **Never prompt.** Every installer question takes its default, the restore offer is skipped (a restore overwrites memory, so it always needs a person), and the wizard is started with `--non-interactive`. On Linux, `sudo` runs as `sudo -n`, so it fails instead of waiting for a password. | `-NonInteractive` | `--non-interactive` |
| **Give the wizard its answers** from a JSON or YAML file (question id -> answer), passed on as `--answers`. Checked before anything runs: a missing file or a folder is exit 64. | `-AnswersFile FILE` | `--answers FILE` |
| **Dry run.** Detects and reports only, and prints each command it would run. It installs nothing, runs no `pip install`, creates no virtual environment and no secrets folder, restores nothing and starts no wizard. On Windows it also changes no permissions and opens no browser. | `-DryRun` | `--dry-run` |

For CI / unattended setups:

```powershell
# Windows
.\install.ps1 -NonInteractive -SkipObsidian -AnswersFile answers.yaml
```

```bash
# macOS / Linux
SKIP_OBSIDIAN=1 bash install.sh --non-interactive --answers answers.yaml
```

Non-interactive, the wizard cannot ask, so if a required answer is missing or invalid it stops, your profile is not set, and the installer says so loudly with both ways to fix it (an answers file, or running the wizard yourself).

To check what an install would do on a machine before doing it: `bash install.sh --dry-run` or `.\install.ps1 -DryRun`.

Skip flags: `-SkipPython` / `-SkipObsidian` / `-SkipNode` / `-SkipFirstRun` (Windows) or `SKIP_PYTHON=1` / `SKIP_OBSIDIAN=1` / `SKIP_NODE=1` / `SKIP_FIRST_RUN=1` (Unix).

**Where it looks for a backup drive.** On macOS / Linux it searches `/Volumes`, `/media`, `/media/$USER`, `/mnt` and `/run/media`, one or two folders deep, for a drive holding a Charon backup. Set `BACKUP_SEARCH_DIR=<folder>` to search only under that folder instead, e.g. `BACKUP_SEARCH_DIR=/mnt/usb bash install.sh`. On Windows it checks the top of every drive letter.

## Prerequisites reference

| What | Version | Why |
|---|---|---|
| **Claude Code** | Latest | The CLI this harness wraps. Install from [claude.com/claude-code](https://claude.com/claude-code). The bootstrap script doesn't install Claude Code itself — get that separately. |
| **Python** | 3.10+ | Hooks, MCP servers, utility scripts. Type-hint syntax `dict \| None` requires 3.10. |
| **PyYAML** | 6.0+ | First-run wizard question definitions. |
| **Anthropic Python SDK** | Latest | Used by the save-on-mention hook + knowledge-graph extractor (optional). |
| **MCP Python SDK** | Latest | Used by the vault-readonly, vault-ops, and vault-graph MCP servers. |
| **Obsidian** *(recommended)* | Latest | Optional markdown editor; pairs naturally with the vault structure. |
| **Git** | 2.x+ | Cloning, version control. |

### Optional feature deps

The base install stays lean. Features below are opt-in — install only what you want.

| Feature | Install | What it gives you |
|---|---|---|
| **Doc + web ingestion, Word export** | `pip install -r requirements-ingest.txt` (markitdown + requests + python-docx; local, no API calls) | `/ingest`, `/webfetch`, `/docs`, and `scripts/md_to_docx.py` (markdown note → styled Word document) |
| **Semantic search** | `pip install -r requirements-semantic.txt` (sentence-transformers + sqlite-vec + numpy; ~500MB) | The `semantic_search` MCP tool + `scripts/semantic_index.py` |
| **Knowledge graph** | `pip install -r requirements-graph.txt` (networkx; pure-Python, no native deps) + Anthropic API key | The `vault-graph` MCP server + `scripts/extract_entities.py` |
| **Voice capture** | `pip install -r requirements-voice.txt` (openai-whisper + sounddevice + scipy; ~600MB with Whisper small model) | The `/voice-note` slash command + `scripts/voice-capture.py` |

After installing an optional feature, you may need to build its index (e.g. `python scripts/semantic_index.py` or `python scripts/extract_entities.py`).

Supported operating systems:

| OS | Status |
|---|---|
| **Windows 10 / 11** | Primary — built and tested here. PowerShell + Windows Toast notifications first-class. |
| **macOS** | Supported. Notification-toast hook is a no-op (replace body with `osascript` if desired). |
| **Linux** | Supported. Notification-toast hook is a no-op (replace body with `notify-send` if desired). |

## Manual install (if you'd rather not run the bootstrap)

```bash
# Step 1 — verify Python
python --version    # need 3.10+

# Step 2 — Python dependencies
pip install -r requirements.txt

# Step 3 — environment variables (set in your shell profile)
# bash / zsh:
echo 'export HARNESS_VAULT_ROOT="$HOME/second-brain"' >> ~/.zshrc
echo 'export HARNESS_SECRETS_DIR="$HOME/.secrets"' >> ~/.zshrc

# PowerShell:
notepad $PROFILE
# Add:
#   $env:HARNESS_VAULT_ROOT = "$HOME\second-brain"
#   $env:HARNESS_SECRETS_DIR = "$HOME\.secrets"

# Step 4 — secrets directory with restricted permissions
mkdir -p ~/.secrets
chmod 700 ~/.secrets    # Unix
# Windows: icacls ~/.secrets /inheritance:r /grant:r "$env:USERNAME:(OI)(CI)F" /T

# Step 5 — first-run wizard
python scripts/first-run.py
```

The four environment variables (defaults are sensible — override if you need):

| Variable | Default | Purpose |
|---|---|---|
| `HARNESS_VAULT_ROOT` | current working directory | Your vault root. |
| `HARNESS_MEMORY_ROOT` | `~/.claude/projects/<sanitised-vault-path>/memory/` | Where Claude Code stores per-project memory files. The default replicates Claude Code's derivation. |
| `HARNESS_CAPTURE_ROOT` | `~/capture-pipeline` | Capture pipeline install (if you wire M365 / Slack / etc.). |
| `HARNESS_SECRETS_DIR` | `~/.secrets` | Where the harness reads credential JSON files. |

## Agent Org (asked during setup)

The setup wizard asks one question, *"Turn on Agent Org?"* (default yes), quick mode included. Yes adds the plugin folder to `CLAUDE_CODE_PLUGIN_DIRS` in `~/.claude/settings.json`. It merges with anything already there and keeps a backup. It needs Claude Code 2.1.287 or later; on an older version it changes nothing and tells you how to finish after `claude update`. Restart Claude Code afterwards. Existing installs are asked by `/charon-update`. Undo: `python scripts/agent_org_setup.py --disable`. See [AGENT-ORG.md](AGENT-ORG.md).

## Verify

From the vault root:

```bash
# Hooks importable?
python -c "from scripts.lib.harness_paths import vault_root; print(vault_root())"

# load-rules.py runs?
echo '{"prompt":"test","cwd":"."}' | python scripts/load-rules.py

# score-vault.py runs?
python scripts/score-vault.py
```

If `score-vault.py` reports a score, you're functional. Some findings are expected on a fresh install, and it's worth knowing which:

- **`MEMORY.md not found` (CRITICAL)** — expected *before* setup, and the loudest thing you'll see. The memory directory doesn't exist until first-run creates it. Run the wizard, then re-run this check: the finding goes away. It reads as alarming and isn't.
- **Vault folders** — the clone ships `00-Inbox/` and `07-References/`; the rest of the 00–09 skeleton is created by **first-run**, not by the clone (the user-content folders are gitignored, so they can't ship). Running the wizard in either mode scaffolds all nine — `00-Inbox`, `01-Daily`, `02-BUs`, `03-Domains`, `04-People`, `05-Meetings`, `06-Decisions`, `08-Projects`, `09-Archive` — each with an explainer README, skipping anything that already exists. They arrive **empty**: Charon gives every capability a home to grow into, but never generates org-specific content, so `02-BUs/` and `03-Domains/` are yours to populate. A folder finding before setup is expected; after setup it isn't.
- **`CLAUDE.md`** — what first-run populates is the *memory directory* (`user_role.md` and friends), not the vault tree.

## Re-run the wizard

You can re-run any time:

```bash
python scripts/first-run.py              # walk all phases; existing answers offer keep/update/wipe
python scripts/first-run.py --phase voice    # re-do voice profile only
python scripts/first-run.py --catch-up   # after an update: only the questions new capabilities need
python scripts/first-run.py --dry-run    # show planned writes; don't touch the filesystem
python scripts/first-run.py --logo full  # force the full ASCII banner (needs wide terminal)
```

See [`FIRST-RUN.md`](FIRST-RUN.md) for the question flow.

## Personalising the boot file — use `CLAUDE.local.md`

`CLAUDE.md` is tracked in git, and updates arrive as `git pull --ff-only`. So if you edit it and
commit, your branch diverges and `/charon-update` stops working — it reports *"local branch has N
commits not on upstream — manual merge needed"* and your install quietly stays on the version you
were on. It's an easy trap: `CLAUDE.md` is the most tempting file to personalise, and nothing
connects the two events for you afterwards.

Put personal instructions in **`CLAUDE.local.md`** at the repo root instead. Claude Code loads it
straight after `CLAUDE.md` every session, so it's the last thing read at that level, and it's
gitignored — updates keep flowing. Same pattern as `.claude/settings.local.json` for permissions.

If you've already committed changes to `CLAUDE.md` and want updates back: move your additions into
`CLAUDE.local.md`, then `git checkout <upstream-sha> -- CLAUDE.md` to restore the shipped version
and commit that.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ImportError: yaml` | `pip install PyYAML` (or re-run `install.ps1` / `install.sh`) |
| `ImportError: anthropic` | `pip install anthropic`. Save-on-mention hook will no-op until installed + API key configured. |
| `ImportError: mcp` | `pip install mcp` |
| `error: externally-managed-environment` from pip | Your Python is protected (PEP 668). Re-run the installer: it makes `~/.charon-venv` and installs there, and the hooks pick it up. Don't use `--break-system-packages`. See [Protected Python](#protected-python-pep-668-charons-private-virtual-environment). |
| Installer exits 77 | You ran it as root (`sudo`) or in an elevated window. Run it as yourself. |
| Installer exits 66 | It was piped in (`curl ... \| bash`, `irm ... \| iex`). Clone or download Charon and run the script as a file. |
| Installer exits 3 | A required package is still missing, or (Windows) Python was just installed and the window can't see it yet. Follow the fix printed in Step 4, or open a new terminal and re-run. |
| Bootstrap script blocked on Windows | Try `powershell -ExecutionPolicy RemoteSigned -File install.ps1` first (default policy for locally-cloned scripts). Locked-down machine? After inspecting the file: `powershell -ExecutionPolicy Bypass -Scope Process -File install.ps1` (process-scoped, not machine-wide). Or persistently relax for your user account: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. |
| `winget` not found (Windows) | Install App Installer from Microsoft Store, then re-run. Or pick (m)anual at the prompt. |
| Python install via bootstrap "succeeded" but `python --version` doesn't work | Open a fresh shell — PATH only updates for new sessions. |
| Hooks not firing (Linux) | `which python` prints nothing: install `python-is-python3` (Debian/Ubuntu) or make `python` point at `python3`. See Known issues at the top. |
| No `/agent-org` command, no live pane | `python3 scripts/agent_org_setup.py`, then restart Claude Code. |
| Hooks not firing | Verify `.claude/settings.json` exists and hooks point at `${CLAUDE_PROJECT_DIR}/scripts/...`. Set `CLAUDE_PROJECT_DIR` to your vault root. |
| Toast notifications don't appear (non-Windows) | Expected — the hook is a no-op outside Windows. See [`CONFIGURATION.md`](CONFIGURATION.md) for swapping in `notify-send` / `osascript`. |
| `MEMORY.md not found` on `score-vault` | First-run hasn't run yet, OR `HARNESS_MEMORY_ROOT` points at the wrong place. Confirm with `python -c "from scripts.lib.harness_paths import memory_root; print(memory_root())"`. |

## Next

→ [`FIRST-RUN.md`](FIRST-RUN.md) — what the wizard asks and why
→ [`EMAIL-PROVIDER-SETUP.md`](EMAIL-PROVIDER-SETUP.md) — if you plan to wire up the capture pipeline, read this BEFORE the wizard's workflow phase
→ [`CONFIGURATION.md`](CONFIGURATION.md) — env vars, scheduled tasks, optional integrations
→ [`CAPABILITIES.md`](CAPABILITIES.md) — full catalogue of what ships
