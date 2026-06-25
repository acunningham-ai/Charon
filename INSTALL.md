# Installing Charon

Charon is a CISO harness. We teach security-hygiene discipline through the rules, so we model it from the install instructions: **read the script before you run it**, and run it under the least-permissive policy that works.

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

**Step 1 — Inspect the installer.** Open `install.ps1` / `install.sh` in your editor. It's short (≈100 lines). You're checking: which package manager it invokes, where it writes (your `~/.secrets/`), what Python deps it pulls.

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

1. Detects **Python 3.10+**; offers auto-install via `winget` / `brew` / `apt|dnf|pacman`, OR opens the install URL for manual install, OR skips.
2. Detects **Obsidian**; same auto / manual / skip choice. Optional — Charon works with any markdown editor.
3. Installs Python deps from `requirements.txt` (PyYAML, anthropic, mcp).
4. Creates your **secrets directory** with restricted permissions (`~/.secrets/` by default).
5. Hands off to `scripts/first-run.py` — the interactive wizard, which now offers a **Quick path (4–6 questions, ~2 minutes) or Full path (39 questions, ~20 minutes)** at the top. Pick Quick to get productive immediately and refine any phase later; pick Full if you already know how you want the harness configured. See [`FIRST-RUN.md`](FIRST-RUN.md) for details.

## What the bootstrap script asks you

For each prerequisite that's missing:

```
(a)uto-install / (m)anual install (open URL, then re-run) / (s)kip
```

- **Auto** runs your platform's package manager. No admin elevation on macOS (brew); Linux `apt`/`dnf`/`pacman` will prompt for sudo when needed; Windows `winget` runs per-user.
- **Manual** opens the install URL in your browser. You install, then re-run the bootstrap.
- **Skip** continues without that prereq — useful when you already have a custom install (e.g. pyenv, asdf, mise) that the script doesn't see.

## Non-interactive install

For CI / unattended setups:

```bash
# Windows
.\install.ps1 -AcceptDefaults -SkipObsidian

# macOS / Linux
ACCEPT_DEFAULTS=1 SKIP_OBSIDIAN=1 bash install.sh
```

Skip flags: `-SkipPython` / `-SkipObsidian` / `-SkipFirstRun` (Windows) or `SKIP_PYTHON=1` / `SKIP_OBSIDIAN=1` / `SKIP_FIRST_RUN=1` (Unix).

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

If `score-vault.py` reports a score, you're functional. Findings against missing files (`CLAUDE.md not found`, etc.) are expected on a fresh install — first-run sorts those.

## Re-run the wizard

You can re-run any time:

```bash
python scripts/first-run.py              # walk all phases; existing answers offer keep/update/wipe
python scripts/first-run.py --phase voice    # re-do voice profile only
python scripts/first-run.py --dry-run    # show planned writes; don't touch the filesystem
python scripts/first-run.py --logo full  # force the full ASCII banner (needs wide terminal)
```

See [`FIRST-RUN.md`](FIRST-RUN.md) for the question flow.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ImportError: yaml` | `pip install PyYAML` (or re-run `install.ps1` / `install.sh`) |
| `ImportError: anthropic` | `pip install anthropic`. Save-on-mention hook will no-op until installed + API key configured. |
| `ImportError: mcp` | `pip install mcp` |
| Bootstrap script blocked on Windows | Try `powershell -ExecutionPolicy RemoteSigned -File install.ps1` first (default policy for locally-cloned scripts). Locked-down machine? After inspecting the file: `powershell -ExecutionPolicy Bypass -Scope Process -File install.ps1` (process-scoped, not machine-wide). Or persistently relax for your user account: `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`. |
| `winget` not found (Windows) | Install App Installer from Microsoft Store, then re-run. Or pick (m)anual at the prompt. |
| Python install via bootstrap "succeeded" but `python --version` doesn't work | Open a fresh shell — PATH only updates for new sessions. |
| Hooks not firing | Verify `.claude/settings.json` exists and hooks point at `${CLAUDE_PROJECT_DIR}/scripts/...`. Set `CLAUDE_PROJECT_DIR` to your vault root. |
| Toast notifications don't appear (non-Windows) | Expected — the hook is a no-op outside Windows. See [`CONFIGURATION.md`](CONFIGURATION.md) for swapping in `notify-send` / `osascript`. |
| `MEMORY.md not found` on `score-vault` | First-run hasn't run yet, OR `HARNESS_MEMORY_ROOT` points at the wrong place. Confirm with `python -c "from scripts.lib.harness_paths import memory_root; print(memory_root())"`. |

## Next

→ [`FIRST-RUN.md`](FIRST-RUN.md) — what the wizard asks and why
→ [`EMAIL-PROVIDER-SETUP.md`](EMAIL-PROVIDER-SETUP.md) — if you plan to wire up the capture pipeline, read this BEFORE the wizard's workflow phase
→ [`CONFIGURATION.md`](CONFIGURATION.md) — env vars, scheduled tasks, optional integrations
→ [`CAPABILITIES.md`](CAPABILITIES.md) — full catalogue of what ships
