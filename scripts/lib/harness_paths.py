"""harness_paths.py — env-var-first path resolution for harness scripts.

Provides four functions every harness script SHOULD use instead of
hardcoding paths:

  vault_root()              HARNESS_VAULT_ROOT   (your second-brain root)
  memory_root()             HARNESS_MEMORY_ROOT  (Claude-Code per-project memory dir)
  capture_pipeline_root()   HARNESS_CAPTURE_ROOT (capture-pipeline install dir)
  secrets_dir()             HARNESS_SECRETS_DIR  (default: $HOME/.secrets)

Defaults are sensible cross-platform values. Set the env vars in your
shell profile (.bashrc / .zshrc / PowerShell $PROFILE) or via the
first-run wizard's environment configuration.
"""
import os
from pathlib import Path


def vault_root() -> Path:
    """Second-brain vault root. Defaults to the current working directory
    if HARNESS_VAULT_ROOT is unset — harness scripts called from inside the
    vault `Just Work`. Set explicitly for scheduled / unattended use."""
    explicit = os.environ.get("HARNESS_VAULT_ROOT")
    if explicit:
        return Path(explicit).resolve()
    return Path.cwd().resolve()


def memory_root() -> Path:
    """Harness memory directory (Claude-Code per-project memory).

    Default: `~/.claude/projects/<sanitised-vault-path>/memory/`.
    Claude Code derives the per-project dir from the vault path by replacing
    path separators with hyphens; we replicate that here for the default.
    Override via HARNESS_MEMORY_ROOT if you need a non-standard layout.
    """
    explicit = os.environ.get("HARNESS_MEMORY_ROOT")
    if explicit:
        return Path(explicit).resolve()
    vault = vault_root()
    # Claude Code's transform: replace `:`, `/`, `\`, ` ` with `-`, prefix `C--`-style
    sanitised = str(vault).replace(":", "-").replace("\\", "-").replace("/", "-").replace(" ", "-")
    return (Path.home() / ".claude" / "projects" / sanitised / "memory").resolve()


def capture_pipeline_root() -> Path:
    """Capture-pipeline install dir (separate physical install per host)."""
    explicit = os.environ.get("HARNESS_CAPTURE_ROOT")
    if explicit:
        return Path(explicit).resolve()
    return (Path.home() / "capture-pipeline").resolve()


def secrets_dir() -> Path:
    """Per-host secrets directory. Default `$HOME/.secrets` (works on both
    Windows and Linux/macOS). Override via HARNESS_SECRETS_DIR for non-standard
    layouts (e.g. keychain-backed wrappers)."""
    explicit = os.environ.get("HARNESS_SECRETS_DIR")
    if explicit:
        return Path(explicit).resolve()
    return (Path.home() / ".secrets").resolve()
