#!/usr/bin/env bash
# Charon bootstrap installer - macOS / Linux
# -------------------------------------------
# Pre-Python bootstrap. Detects prerequisites, offers auto-install via the
# system package manager (brew on macOS, apt/dnf/pacman on Linux), or
# shows install instructions, then hands off to the first-run wizard.
#
# Usage:
#   bash install.sh [--non-interactive] [--dry-run] [--answers FILE] [--help]
#
#   --non-interactive  Never prompt. Every question takes its default, sudo
#                      runs as `sudo -n` (fails instead of asking for a
#                      password), the restore offer is skipped, and the
#                      first-run wizard is started with --non-interactive.
#   --dry-run          Side-effect free. Detects and reports only: never
#                      installs a package, never runs pip install, never
#                      creates a virtual environment or the secrets folder,
#                      never restores, never starts the wizard (it prints the
#                      commands it would run).
#   --answers FILE     Hand FILE to the first-run wizard as its answers (JSON
#                      or YAML, question id -> answer). Checked before
#                      anything runs: a missing file or a folder is exit 64.
#
# Run it from a saved copy (`bash install.sh`), never piped in from the
# network (`curl ... | bash`). A piped run is refused (exit 66): the script
# cannot find its own folder, and every question would read the rest of the
# script as its answer. Running as root is refused too (exit 77): Charon is
# per-user, and a root run leaves root-owned files in your home folder.
#
# Accept-defaults mode (answers every installer question with its default,
# but the wizard still asks its own questions):
#   ACCEPT_DEFAULTS=1 bash install.sh
#
# Skip flags:
#   SKIP_PYTHON=1   skip Python detection / install
#   SKIP_OBSIDIAN=1 skip Obsidian detection / install
#   SKIP_NODE=1     skip Node detection / install
#   SKIP_FIRST_RUN=1 skip running the wizard
# Restore search:
#   BACKUP_SEARCH_DIR=<folder>  look for a backup drive only under <folder>
#                               (default: /Volumes /media /mnt /run/media)
#
# Python interpreter: searched in the same order the hook launcher uses
# (python3, then python, then `py -3`), Python 3 only. The interpreter found
# here is the one that gets the dependencies and runs the wizard, so the
# hooks and the installer agree on which Python is in use.
#
# Python packages: installed with `pip install --user`. A Python your distro
# protects (PEP 668, "externally managed") is never forced: Charon makes a
# private virtual environment at ~/.charon-venv with it instead, installs the
# requirements into that, and runs the wizard with the venv's python. The
# hooks use the first python3 on PATH, so start Claude Code from a shell
# where that venv is active (the installer prints the command).
#
# Exit status:
#   0  finished, required Python packages importable
#   3  finished, but a required Python package (PyYAML, mcp) is still
#      missing; the remedy was printed in Step 4 (3, not 2, so it is never
#      confused with a usage error from the wizard's argument parser)
#   64 bad command-line arguments (including a bad --answers FILE)
#   66 refused: the script was piped in on stdin
#   77 refused: running as root
#   anything else: a step failed (or the wizard's own exit status)
#
# This script will request sudo only when invoking a Linux package
# manager. On macOS, brew never needs sudo. It never passes
# --break-system-packages to pip.

set -euo pipefail

# --- Refusals, before anything else runs ---
# A piped run (`curl ... | bash`, `bash -s`, `bash <(curl ...)`) has no script
# file: there is no repo folder to install from, and any prompt would swallow
# the rest of the script from stdin.
SELF="${BASH_SOURCE[0]:-}"
if [ -z "$SELF" ] || [ ! -f "$SELF" ]; then
    echo "install.sh: refusing to run from a pipe (curl ... | bash, or bash -s)." >&2
    echo "  Clone or download Charon, read install.sh, then run: bash install.sh" >&2
    exit 66
fi
# Root: Charon is a per-user install. A root run would put the secrets folder,
# pip --user packages and the venv in root's home, owned by root.
if [ "$(id -u 2>/dev/null || echo unknown)" = "0" ]; then
    echo "install.sh: refusing to run as root. Charon installs for one user:" >&2
    echo "  run it as yourself, without sudo. It asks for sudo itself only when a" >&2
    echo "  Linux package manager needs it." >&2
    exit 77
fi

REPO_ROOT="$(cd "$(dirname "$SELF")" && pwd)"
ACCEPT_DEFAULTS="${ACCEPT_DEFAULTS:-}"
SKIP_PYTHON="${SKIP_PYTHON:-}"
SKIP_OBSIDIAN="${SKIP_OBSIDIAN:-}"
SKIP_NODE="${SKIP_NODE:-}"
SKIP_FIRST_RUN="${SKIP_FIRST_RUN:-}"
NON_INTERACTIVE=""
DRY_RUN=""
ANSWERS=""

USAGE_LINE="Usage: bash install.sh [--non-interactive] [--dry-run] [--answers FILE] [--help]"

usage() {
    cat <<'USAGE'
Usage: bash install.sh [--non-interactive] [--dry-run] [--answers FILE] [--help]

  --non-interactive  Never prompt: every question takes its default, sudo runs
                     as `sudo -n`, the restore offer is skipped, and the wizard
                     is started with --non-interactive.
  --dry-run          Detect and report only. Installs nothing, runs no pip
                     install, creates no folders, starts no wizard.
  --answers FILE     Give the first-run wizard its answers from FILE (JSON or
                     YAML, question id -> answer).

Environment: ACCEPT_DEFAULTS=1, SKIP_PYTHON=1, SKIP_OBSIDIAN=1, SKIP_NODE=1,
SKIP_FIRST_RUN=1, BACKUP_SEARCH_DIR=<folder> (see the header of install.sh).
USAGE
}

bad_args() {
    echo "install.sh: $1" >&2
    echo "$USAGE_LINE" >&2
    exit 64
}

while [ "$#" -gt 0 ]; do
    case "$1" in
        --non-interactive) NON_INTERACTIVE=1 ;;
        --dry-run)         DRY_RUN=1 ;;
        --answers)
            if [ "$#" -lt 2 ] || [ -z "$2" ]; then
                bad_args "--answers needs a FILE"
            fi
            ANSWERS="$2"
            shift
            ;;
        --answers=*)
            ANSWERS="${1#--answers=}"
            [ -n "$ANSWERS" ] || bad_args "--answers needs a FILE"
            ;;
        -h|--help)         usage; exit 0 ;;
        *)                 bad_args "unknown option: $1" ;;
    esac
    shift
done

# --answers must name a readable file, checked before anything runs.
if [ -n "$ANSWERS" ]; then
    if [ ! -f "$ANSWERS" ] || [ ! -r "$ANSWERS" ]; then
        bad_args "--answers: not a readable file: $ANSWERS"
    fi
    # Absolute, so the wizard reads the same file wherever it runs from.
    ANSWERS="$(cd "$(dirname "$ANSWERS")" && pwd)/$(basename "$ANSWERS")"
fi

# sudo must never prompt in non-interactive mode: -n makes it fail instead.
if [ -n "$NON_INTERACTIVE" ]; then
    SUDO="sudo -n"
else
    SUDO="sudo"
fi

# ANSI colors (only if stdout is a tty)
if [ -t 1 ]; then
    C_GREEN=$'\033[32m'; C_YELLOW=$'\033[33m'; C_CYAN=$'\033[36m'; C_RED=$'\033[31m'; C_RESET=$'\033[0m'
else
    C_GREEN=""; C_YELLOW=""; C_CYAN=""; C_RED=""; C_RESET=""
fi

# --- Small inline banner (pre-Python) ---
cat <<'BANNER'

+----------------------------------------------------------+
|                                                          |
|        CHARON  -  second-brain harness                   |
|        for Claude Code                                   |
|                                                          |
+----------------------------------------------------------+

Bootstrap installer (macOS / Linux)
BANNER
echo

# --- Helpers ---
ask() {
    # ask <prompt> [default]
    local prompt="$1"
    local default="${2:-}"
    local suffix=""
    [ -n "$default" ] && suffix=" [$default]"
    if [ -n "$NON_INTERACTIVE" ]; then
        # Never read from the terminal in non-interactive mode.
        echo "$default"
        return
    fi
    if [ -n "$ACCEPT_DEFAULTS" ] && [ -n "$default" ]; then
        echo "$default"
        return
    fi
    local answer
    read -r -p "  ${prompt}${suffix}: " answer || true
    if [ -z "$answer" ] && [ -n "$default" ]; then
        answer="$default"
    fi
    echo "$answer"
}

ask_choice() {
    # ask_choice <prompt> <default> <choice1> <choice2> ...
    local prompt="$1"
    local default="$2"
    shift 2
    while true; do
        local a
        a="$(ask "$prompt" "$default")"
        a="$(echo "$a" | tr '[:upper:]' '[:lower:]')"
        for c in "$@"; do
            if [ "$a" = "$c" ]; then
                echo "$a"
                return
            fi
        done
        echo "    ${C_YELLOW}Please answer one of: $*${C_RESET}" >&2
    done
}

have_cmd() { command -v "$1" >/dev/null 2>&1; }

# --- Python interpreter: the hook launcher's order ---
# The hook launcher tries python3, then python, then `py -3`, and accepts
# Python 3 only. The installer searches in exactly that order, so the
# interpreter that gets the dependencies and runs the wizard is the one the
# hooks will run. A Python 3 older than 3.10 is still the launcher's choice:
# it is reported as too old rather than skipped, so the two never disagree.
PY=""        # command to run ("py" means `py -3`; a path for the venv)
PY_LABEL=""  # how to show it to the user
PY_VER=""    # major.minor
VENV_PY=""   # the private venv's python, once Step 4 has set it up

PY_VERSION_PROBE='import sys; print("%d.%d" % sys.version_info[:2])'

run_py() {
    if [ "$PY" = "py" ]; then
        py -3 "$@"
    else
        "$PY" "$@"
    fi
}

find_python() {
    # Sets PY / PY_LABEL / PY_VER to the first Python 3 in launcher order.
    PY=""; PY_LABEL=""; PY_VER=""
    local c v
    for c in python3 python py; do
        have_cmd "$c" || continue
        # -S and a closed stdin, as the launcher probes: a candidate the
        # launcher would accept is never rejected here, and the reverse.
        if [ "$c" = "py" ]; then
            v="$(py -3 -S -c "$PY_VERSION_PROBE" </dev/null 2>/dev/null || true)"
        else
            v="$("$c" -S -c "$PY_VERSION_PROBE" </dev/null 2>/dev/null || true)"
        fi
        v="$(printf '%s' "$v" | tr -d '\r' | head -n 1)"
        case "$v" in
            3.[0-9]|3.[0-9][0-9])
                PY="$c"
                if [ "$c" = "py" ]; then PY_LABEL="py -3"; else PY_LABEL="$c"; fi
                PY_VER="$v"
                return 0
                ;;
        esac
    done
    return 1
}

use_python() {
    # The interpreter for every step after the venv decision: Charon's private
    # venv once Step 4 has set it up (same Python version), else the
    # launcher's choice.
    if [ -n "$VENV_PY" ]; then
        PY="$VENV_PY"
        PY_LABEL="\"$VENV_PY\""
        return 0
    fi
    find_python
}

python_new_enough() {
    # True when the launcher's Python is 3.10 or newer.
    [ -n "$PY_VER" ] || return 1
    local minor="${PY_VER#*.}"
    [ "$minor" -ge 10 ]
}

# --- Required Python packages ---
# Import names checked after Step 4. PyYAML is needed by the first-run wizard;
# mcp by the vault MCP servers. anthropic is optional (the hook that uses it
# no-ops without it), so it is reported but never fails the install.
REQUIRED_MODULES="yaml mcp"
OPTIONAL_MODULES="anthropic"
# Both probes drop the current folder from sys.path before importing anything,
# so a yaml.py / mcp.py (or sysconfig.py) lying in the folder you ran the
# installer from is never loaded and never mistaken for the real package.
# (Not `python -I`: that would also hide PYTHONPATH and the user site-packages
# that `pip install --user` fills, and report installed packages as missing.)
# One line on purpose: the \n escapes are Python string escapes inside exec().
DEP_PROBE='import os, sys; c = os.path.normcase(os.path.realpath(os.getcwd())); sys.path[:] = [p for p in sys.path if p and os.path.normcase(os.path.realpath(p)) != c]; exec("m=[]\nfor n in sys.argv[1:]:\n try:\n  __import__(n)\n except Exception:\n  m.append(n)\nprint(chr(32).join(m))")'
PEP668_PROBE='import os, sys; c = os.path.normcase(os.path.realpath(os.getcwd())); sys.path[:] = [p for p in sys.path if p and os.path.normcase(os.path.realpath(p)) != c]; import sysconfig; print(int(sys.prefix == sys.base_prefix and os.path.isfile(os.path.join(sysconfig.get_path("stdlib"), "EXTERNALLY-MANAGED"))))'

module_to_package() {
    case "$1" in
        yaml) echo "PyYAML" ;;
        *)    echo "$1" ;;
    esac
}

missing_modules() {
    # missing_modules <import names...>  -> prints the ones that fail to import.
    # Fails closed: no interpreter, or a probe that errors, reports all missing.
    if [ -z "$PY" ]; then
        echo "$*"
        return
    fi
    local out
    if out="$(run_py -c "$DEP_PROBE" "$@" 2>/dev/null)"; then
        printf '%s' "$out" | tr -d '\r' | head -n 1
    else
        echo "$*"
    fi
}

# --- Charon's private virtual environment (for a PEP 668 Python) ---
CHARON_VENV="${HOME}/.charon-venv"

on_windows_bash() {
    case "$(uname -s 2>/dev/null || echo unknown)" in
        MINGW*|MSYS*|CYGWIN*) return 0 ;;
    esac
    return 1
}

venv_python_expected() {
    # Where the venv's python will be: bin/python, or Scripts/python.exe when
    # this bash runs on Windows (Git Bash).
    if on_windows_bash; then
        echo "$CHARON_VENV/Scripts/python.exe"
    else
        echo "$CHARON_VENV/bin/python"
    fi
}

venv_activate_expected() {
    if on_windows_bash; then
        echo "$CHARON_VENV/Scripts/activate"
    else
        echo "$CHARON_VENV/bin/activate"
    fi
}

venv_python() {
    # The venv's python if it exists, else fail.
    if [ -x "$CHARON_VENV/bin/python" ]; then
        echo "$CHARON_VENV/bin/python"
        return 0
    fi
    if [ -f "$CHARON_VENV/Scripts/python.exe" ]; then
        echo "$CHARON_VENV/Scripts/python.exe"
        return 0
    fi
    return 1
}

print_dep_remedy() {
    # Exact remedy for a Python that pip cannot install into. Every path is
    # spelled out and quoted, so it can be pasted as it stands.
    echo "  ${C_YELLOW}How to fix it (pick one):${C_RESET}"
    echo
    echo "  1. Distro packages for what your distro ships:"
    case "$OS_KIND" in
        debian) echo "       sudo apt-get install python3-yaml" ;;
        rhel)   echo "       sudo dnf install python3-pyyaml" ;;
        arch)   echo "       sudo pacman -S python-yaml" ;;
        mac)    echo "       (Homebrew does not package these libraries; use option 2)" ;;
        *)      echo "       install your distro's PyYAML package (often python3-yaml)" ;;
    esac
    echo "     mcp is not packaged by most distros; use option 2 for it."
    echo
    echo "  2. Charon's private virtual environment, then launch Claude Code from a"
    echo "     shell where it is active (the hooks use the first python3 on PATH):"
    if [ "$OS_KIND" = "debian" ]; then
        echo "       sudo apt-get install python3-venv"
    fi
    echo "       ${PY_LABEL:-python3} -m venv \"${CHARON_VENV}\""
    echo "       \"$(venv_python_expected)\" -m pip install -r \"${REPO_ROOT}/requirements.txt\""
    echo "       . \"$(venv_activate_expected)\""
    echo
    echo "  This installer never passes --break-system-packages to pip. Overriding"
    echo "  your distro's package protection is your decision to make, not ours."
}

# Detect OS
OS_KIND="unknown"
if [ "$(uname)" = "Darwin" ]; then
    OS_KIND="mac"
elif [ -f /etc/os-release ]; then
    . /etc/os-release
    case "${ID_LIKE:-${ID:-}}" in
        *debian*|*ubuntu*) OS_KIND="debian" ;;
        *rhel*|*fedora*)   OS_KIND="rhel" ;;
        *arch*)            OS_KIND="arch" ;;
        *) OS_KIND="linux" ;;
    esac
fi

install_python() {
    case "$OS_KIND" in
        mac)
            if have_cmd brew; then
                echo "  ${C_CYAN}Running: brew install python@3.12${C_RESET}"
                brew install python@3.12
                return $?
            else
                echo "  ${C_YELLOW}Homebrew not installed. Install brew first: https://brew.sh${C_RESET}"
                return 1
            fi
            ;;
        debian)
            echo "  ${C_CYAN}Running: $SUDO apt-get update && $SUDO apt-get install -y python3 python3-pip${C_RESET}"
            $SUDO apt-get update && $SUDO apt-get install -y python3 python3-pip
            return $?
            ;;
        rhel)
            echo "  ${C_CYAN}Running: $SUDO dnf install -y python3 python3-pip${C_RESET}"
            $SUDO dnf install -y python3 python3-pip
            return $?
            ;;
        arch)
            echo "  ${C_CYAN}Running: $SUDO pacman -S --noconfirm python python-pip${C_RESET}"
            $SUDO pacman -S --noconfirm python python-pip
            return $?
            ;;
        *)
            echo "  ${C_YELLOW}Unsupported OS - install Python 3.10+ from https://www.python.org/downloads/${C_RESET}"
            return 1
            ;;
    esac
}

node_major() {
    # Returns the major version of `node` if present and >=0; empty string otherwise.
    if have_cmd node; then
        local v
        v="$(node --version 2>/dev/null || true)"
        # node --version emits e.g. "v20.10.0"
        if [[ "$v" =~ ^v([0-9]+) ]]; then
            echo "${BASH_REMATCH[1]}"
            return 0
        fi
    fi
    echo ""
}

install_node() {
    case "$OS_KIND" in
        mac)
            if have_cmd brew; then
                echo "  ${C_CYAN}Running: brew install node${C_RESET}"
                brew install node
                return $?
            else
                echo "  ${C_YELLOW}Homebrew not installed. Install brew first: https://brew.sh${C_RESET}"
                return 1
            fi
            ;;
        debian)
            echo "  ${C_CYAN}Running: $SUDO apt-get update && $SUDO apt-get install -y nodejs npm${C_RESET}"
            echo "  ${C_YELLOW}Note: distro nodejs may be older than 18. If so, see https://nodejs.org/ for nvm or the NodeSource setup script.${C_RESET}"
            $SUDO apt-get update && $SUDO apt-get install -y nodejs npm
            return $?
            ;;
        rhel)
            echo "  ${C_CYAN}Running: $SUDO dnf install -y nodejs npm${C_RESET}"
            $SUDO dnf install -y nodejs npm
            return $?
            ;;
        arch)
            echo "  ${C_CYAN}Running: $SUDO pacman -S --noconfirm nodejs npm${C_RESET}"
            $SUDO pacman -S --noconfirm nodejs npm
            return $?
            ;;
        *)
            echo "  ${C_YELLOW}Unsupported OS - install Node.js 18+ from https://nodejs.org/${C_RESET}"
            return 1
            ;;
    esac
}

install_obsidian() {
    case "$OS_KIND" in
        mac)
            if have_cmd brew; then
                echo "  ${C_CYAN}Running: brew install --cask obsidian${C_RESET}"
                brew install --cask obsidian
                return $?
            else
                echo "  ${C_YELLOW}Homebrew not installed. Get Obsidian: https://obsidian.md/download${C_RESET}"
                return 1
            fi
            ;;
        debian|rhel|arch|linux)
            echo "  ${C_YELLOW}Obsidian on Linux: AppImage or Flatpak. See https://obsidian.md/download${C_RESET}"
            if have_cmd flatpak; then
                echo "  ${C_CYAN}Or:  flatpak install -y flathub md.obsidian.Obsidian${C_RESET}"
            fi
            return 1
            ;;
        *)
            echo "  ${C_YELLOW}Get Obsidian: https://obsidian.md/download${C_RESET}"
            return 1
            ;;
    esac
}

# --- Step 1: Python ---
if [ -n "$DRY_RUN" ]; then
    echo "${C_CYAN}Dry run: detecting and reporting only. Nothing is installed, created or started.${C_RESET}"
    echo
fi
echo "${C_GREEN}Step 1 - Python 3.10+${C_RESET}"
if [ -n "$SKIP_PYTHON" ]; then
    echo "  Skipped per SKIP_PYTHON"
else
    if find_python && python_new_enough; then
        echo "  Found: Python $PY_VER via '$PY_LABEL' (the interpreter the hooks will use)"
    else
        if [ -n "$PY" ]; then
            echo "  ${C_YELLOW}Found Python $PY_VER via '$PY_LABEL', which is the interpreter the hooks will use. Need 3.10+.${C_RESET}"
        else
            echo "  ${C_YELLOW}Python 3 not found (looked for python3, python, py -3).${C_RESET}"
        fi
        echo
        echo "  Install URL:  https://www.python.org/downloads/"
        case "$OS_KIND" in
            mac)    echo "  brew:         brew install python@3.12" ;;
            debian) echo "  apt:          sudo apt-get install python3 python3-pip" ;;
            rhel)   echo "  dnf:          sudo dnf install python3 python3-pip" ;;
            arch)   echo "  pacman:       sudo pacman -S python python-pip" ;;
        esac
        echo
        if [ -n "$DRY_RUN" ]; then
            choice="dry"
            echo "  [dry-run] would offer to auto-install Python here."
        else
            choice="$(ask_choice "(a)uto-install / (m)anual / (s)kip" "a" a m s)"
        fi
        case "$choice" in
            a)
                if install_python; then
                    echo "  ${C_GREEN}Python installed. Continuing.${C_RESET}"
                else
                    echo "  ${C_RED}Auto-install failed. Install manually and re-run install.sh.${C_RESET}"
                    exit 1
                fi
                ;;
            m)
                echo "  ${C_YELLOW}Install Python 3.10+ and re-run install.sh.${C_RESET}"
                exit 0
                ;;
            s)
                echo "  ${C_YELLOW}Skipping. Note: Charon hooks need Python to run.${C_RESET}"
                ;;
        esac
    fi
fi

# --- Step 2: Obsidian (optional) ---
echo
echo "${C_GREEN}Step 2 - Obsidian (optional but recommended)${C_RESET}"
if [ -n "$SKIP_OBSIDIAN" ]; then
    echo "  Skipped per SKIP_OBSIDIAN"
elif have_cmd obsidian || [ -d "/Applications/Obsidian.app" ]; then
    echo "  Found."
else
    echo "  ${C_YELLOW}Obsidian not detected.${C_RESET}"
    echo "  Install URL:  https://obsidian.md/download"
    echo
    if [ -n "$DRY_RUN" ]; then
        choice="dry"
        echo "  [dry-run] would offer to install Obsidian here."
    else
        choice="$(ask_choice "(a)uto-install / (m)anual / (s)kip - the harness works without Obsidian" "s" a m s)"
    fi
    case "$choice" in
        a) install_obsidian || true ;;
        m) echo "  ${C_YELLOW}Install Obsidian from the URL above and continue.${C_RESET}" ;;
        s) echo "  Skipping. You can edit the vault with any markdown tool." ;;
    esac
fi

# --- Step 3: Node.js (for capture-pipeline) ---
echo
echo "${C_GREEN}Step 3 - Node.js 18+ (required by the email capture pipeline)${C_RESET}"
if [ -n "$SKIP_NODE" ]; then
    echo "  Skipped per SKIP_NODE"
else
    NODE_MAJ="$(node_major)"
    if [ -n "$NODE_MAJ" ] && [ "$NODE_MAJ" -ge 18 ]; then
        echo "  Found: $(node --version)"
    else
        if [ -n "$NODE_MAJ" ]; then
            echo "  ${C_YELLOW}Found older Node v${NODE_MAJ}. Need 18+.${C_RESET}"
        else
            echo "  ${C_YELLOW}Node.js not found. The email capture pipeline needs Node 18+ to run.${C_RESET}"
        fi
        echo
        echo "  Install URL:  https://nodejs.org/"
        case "$OS_KIND" in
            mac)    echo "  brew:         brew install node" ;;
            debian) echo "  apt:          sudo apt-get install nodejs npm" ;;
            rhel)   echo "  dnf:          sudo dnf install nodejs npm" ;;
            arch)   echo "  pacman:       sudo pacman -S nodejs npm" ;;
        esac
        echo
        if [ -n "$DRY_RUN" ]; then
            choice="dry"
            echo "  [dry-run] would offer to auto-install Node.js here."
        else
            choice="$(ask_choice "(a)uto-install / (m)anual / (s)kip - you can install later" "a" a m s)"
        fi
        case "$choice" in
            a)
                if install_node; then
                    echo "  ${C_GREEN}Node.js installed. Continuing.${C_RESET}"
                else
                    echo "  ${C_YELLOW}Auto-install failed. Install manually if you want the capture pipeline.${C_RESET}"
                fi
                ;;
            m)
                echo "  ${C_YELLOW}Install Node.js 18+ from the URL above and re-run install.sh.${C_RESET}"
                exit 0
                ;;
            s)
                echo "  ${C_YELLOW}Skipping. Note: without Node, the capture pipeline cannot run.${C_RESET}"
                ;;
        esac
    fi
fi

# --- Step 4: Python dependencies ---
echo
echo "${C_GREEN}Step 4 - Python dependencies (PyYAML, anthropic, mcp)${C_RESET}"
# Never aborts under set -e: a pip that is missing, refuses (PEP 668), or fails
# is reported with its remedy, and the installer carries on to the wizard. The
# exit status at the end says whether the required packages made it.
loud() {
    echo "  ${C_RED}!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!${C_RESET}"
    local line
    for line in "$@"; do
        echo "  ${C_RED}!! ${line}${C_RESET}"
    done
    echo "  ${C_RED}!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!${C_RESET}"
}

REQS="${REPO_ROOT}/requirements.txt"
DEPS_PROBLEM=""
DRY_VENV=""   # dry run: the venv would have been made and used

setup_venv() {
    # Make ~/.charon-venv with the launcher's Python and install the
    # requirements into it. Sets VENV_PY only when both steps succeed; on any
    # failure the system Python stays in use and the remedy is printed.
    local vpy rc
    echo "  ${C_CYAN}Creating Charon's private virtual environment instead:${C_RESET}"
    echo "  ${C_CYAN}Running: $PY_LABEL -m venv \"$CHARON_VENV\"${C_RESET}"
    if run_py -m venv "$CHARON_VENV"; then rc=0; else rc=$?; fi
    if [ "$rc" -ne 0 ]; then
        loud "Could not create the virtual environment $CHARON_VENV (exit $rc)." \
             "Continuing to the wizard with $PY_LABEL. Required packages are checked again at the end."
        return 1
    fi
    if ! vpy="$(venv_python)"; then
        loud "The virtual environment $CHARON_VENV has no python in it." \
             "Continuing to the wizard with $PY_LABEL. Required packages are checked again at the end."
        return 1
    fi
    echo "  ${C_CYAN}Running: \"$vpy\" -m pip install -r requirements.txt${C_RESET}"
    if "$vpy" -m pip install -r "$REQS"; then rc=0; else rc=$?; fi
    if [ "$rc" -ne 0 ]; then
        loud "pip install into $CHARON_VENV failed (exit $rc). See the pip output above." \
             "Continuing to the wizard with $PY_LABEL. Required packages are checked again at the end."
        return 1
    fi
    VENV_PY="$vpy"
    echo "  ${C_GREEN}Installed into $CHARON_VENV. The wizard runs with its python.${C_RESET}"
    echo "  ${C_YELLOW}The hooks use the first python3 on PATH, so start Claude Code from a shell${C_RESET}"
    echo "  ${C_YELLOW}where this venv is active:  . \"$(venv_activate_expected)\"${C_RESET}"
    return 0
}

find_python || true
if [ -z "$PY" ]; then
    echo "  ${C_YELLOW}No Python 3 found - skipping deps. Re-run install.sh after installing Python.${C_RESET}"
elif ! python_new_enough; then
    echo "  ${C_YELLOW}Python $PY_VER via '$PY_LABEL' is older than 3.10 - skipping deps.${C_RESET}"
elif [ ! -f "$REQS" ]; then
    echo "  ${C_YELLOW}requirements.txt not found at $REQS - skipping.${C_RESET}"
else
    echo "  Interpreter: $PY_LABEL (Python $PY_VER)"
    HAVE_PIP=""
    if run_py -m pip --version >/dev/null 2>&1; then
        HAVE_PIP=1
    fi
    MANAGED=""
    PEP668="$(run_py -c "$PEP668_PROBE" 2>/dev/null | tr -d '\r' | head -n 1 || true)"
    if [ "$PEP668" = "1" ]; then
        MANAGED=1
    fi

    if [ -n "$MANAGED" ]; then
        # The distro owns this Python: never pip into it. A private venv
        # carries its own pip, so this holds with or without a system pip.
        DEPS_PROBLEM="externally-managed"
        loud "$PY_LABEL is externally managed (PEP 668): your distro owns its packages" \
             "and pip will refuse to install into it. pip install was NOT run against it."
        if [ -n "$DRY_RUN" ]; then
            DRY_VENV=1
            echo "  [dry-run] would run: $PY_LABEL -m venv \"$CHARON_VENV\""
            echo "  [dry-run] would run: \"$(venv_python_expected)\" -m pip install -r \"$REQS\""
            echo "  [dry-run] the wizard would then run with that venv's python."
        elif setup_venv; then
            DEPS_PROBLEM=""
        fi
    elif [ -z "$HAVE_PIP" ]; then
        DEPS_PROBLEM="no-pip"
        loud "pip is not available for $PY_LABEL, so nothing can be installed with it." \
             "Continuing to the wizard. Required packages are checked again at the end."
        case "$OS_KIND" in
            debian) echo "  To get pip:  sudo apt-get install python3-pip" ;;
            rhel)   echo "  To get pip:  sudo dnf install python3-pip" ;;
            arch)   echo "  To get pip:  sudo pacman -S python-pip" ;;
            *)      echo "  To get pip:  $PY_LABEL -m ensurepip --user" ;;
        esac
    elif [ -n "$DRY_RUN" ]; then
        echo "  [dry-run] would run: $PY_LABEL -m pip install --user -r \"$REQS\""
    else
        PIP_LOG="$(mktemp "${TMPDIR:-/tmp}/charon-pip.XXXXXX")"
        echo "  ${C_CYAN}Running: $PY_LABEL -m pip install --user -r requirements.txt${C_RESET}"
        if run_py -m pip install --user -r "$REQS" 2>&1 | tee "$PIP_LOG"; then
            PIP_RC=0
        else
            PIP_RC=$?
        fi
        if [ "$PIP_RC" -ne 0 ] && grep -qi 'externally.managed' "$PIP_LOG"; then
            DEPS_PROBLEM="externally-managed"
            loud "pip refused: $PY_LABEL is externally managed (PEP 668)." \
                 "It is never forced: Charon's private virtual environment is used instead."
            if setup_venv; then
                DEPS_PROBLEM=""
            fi
        elif [ "$PIP_RC" -ne 0 ]; then
            # --user is refused inside a virtual environment; retry without it.
            echo "  ${C_CYAN}Retrying: $PY_LABEL -m pip install -r requirements.txt${C_RESET}"
            if run_py -m pip install -r "$REQS" 2>&1 | tee "$PIP_LOG"; then
                PIP_RC=0
            else
                PIP_RC=$?
            fi
            if [ "$PIP_RC" -ne 0 ]; then
                if grep -qi 'externally.managed' "$PIP_LOG"; then
                    DEPS_PROBLEM="externally-managed"
                else
                    DEPS_PROBLEM="pip-failed"
                fi
                loud "pip install failed (exit $PIP_RC). See the pip output above." \
                     "Continuing to the wizard. Required packages are checked again at the end."
            fi
        fi
        rm -f "$PIP_LOG"
    fi

    # From here on the venv (when it was set up) is the interpreter in use.
    use_python || true
    STEP4_MISSING="$(missing_modules $REQUIRED_MODULES)"
    STEP4_OPTIONAL="$(missing_modules $OPTIONAL_MODULES)"
    if [ -n "$DEPS_PROBLEM" ] || [ -n "$STEP4_MISSING" ]; then
        if [ -n "$STEP4_MISSING" ]; then
            pkgs=""
            for m in $STEP4_MISSING; do pkgs="$pkgs $(module_to_package "$m")"; done
            loud "Required Python packages missing for $PY_LABEL:$pkgs" \
                 "The hooks and the wizard need them. install.sh will exit with status 3."
        fi
        echo
        print_dep_remedy
    else
        echo "  ${C_GREEN}Required packages import cleanly (PyYAML, mcp).${C_RESET}"
    fi
    if [ -n "$STEP4_OPTIONAL" ]; then
        echo "  ${C_YELLOW}Optional package not installed: $STEP4_OPTIONAL (the hook that uses it no-ops without it).${C_RESET}"
    fi
fi

# --- Step 5: Secrets directory ---
echo
echo "${C_GREEN}Step 5 - Secrets directory${C_RESET}"
SECRETS_DEFAULT="${HOME}/.secrets"
if [ -n "$DRY_RUN" ]; then
    echo "  [dry-run] would create $SECRETS_DEFAULT (or the folder you name) with mode 700"
else
    SECRETS="$(ask "Where should credentials live?" "$SECRETS_DEFAULT")"
    [ -n "$SECRETS" ] || SECRETS="$SECRETS_DEFAULT"
    # A typed answer is not shell-expanded: a leading ~ means the home folder,
    # never a folder literally named "~" in the current folder.
    case "$SECRETS" in
        "~")   SECRETS="$HOME" ;;
        "~/"*) SECRETS="$HOME/${SECRETS#"~/"}" ;;
        "~"*)
            echo "  ${C_RED}'$SECRETS': ~user paths are not supported. Give a full path, or ~/folder.${C_RESET}"
            exit 1
            ;;
    esac
    mkdir -p "$SECRETS"
    chmod 700 "$SECRETS"
    echo "  Created $SECRETS with mode 700"
fi

# --- Step 6: Restore from a previous machine? ---
# Offered BEFORE the wizard on purpose. A migrating user's answers already exist in
# the backup; asking them again is the wrong first experience. Restore first, and
# first-run only has to fill genuine gaps.
echo
echo "${C_GREEN}Step 6 - Moving from another computer?${C_RESET}"
BACKUP_TOOL="${REPO_ROOT}/scripts/backup-brain.py"
FOUND_BACKUP=""   # the backup folder itself: <volume>/Charon-Backup
use_python || true
if [ -n "$PY" ] && [ -f "$BACKUP_TOOL" ]; then
    # Probe the usual mount points for the backup marker; the backup folder
    # sits beside it, as backup-brain.py writes it.
    if [ -n "${BACKUP_SEARCH_DIR:-}" ]; then
        BACKUP_BASES=("$BACKUP_SEARCH_DIR")
    else
        BACKUP_BASES=(/Volumes /media "/media/${USER:-}" /mnt /run/media)
    fi
    for base in "${BACKUP_BASES[@]}"; do
        [ -d "$base" ] || continue
        for vol in "$base"/*; do
            [ -d "$vol" ] || continue
            if [ -e "${vol}/.charon-backup-target" ] && [ -d "${vol}/Charon-Backup" ]; then
                FOUND_BACKUP="${vol}/Charon-Backup"; break 2
            fi
            for sub in "$vol"/*; do
                [ -d "$sub" ] || continue
                if [ -e "${sub}/.charon-backup-target" ] && [ -d "${sub}/Charon-Backup" ]; then
                    FOUND_BACKUP="${sub}/Charon-Backup"; break 3
                fi
            done
        done
    done
    if [ -n "$FOUND_BACKUP" ]; then
        echo "  A Charon backup is on a plugged-in drive: $FOUND_BACKUP"
        echo "  Restoring brings across your memory, session history and pipeline state."
        echo "  Credentials are never restored - you re-authenticate afterwards."
        if [ -n "$DRY_RUN" ] || [ -n "$NON_INTERACTIVE" ]; then
            # A restore overwrites memory; it always needs a person to say yes.
            echo "  Not restoring without a person to confirm. To restore, run:"
            echo "    $PY_LABEL \"$BACKUP_TOOL\" --restore --from \"$FOUND_BACKUP\""
        else
            DO_RESTORE="$(ask_choice "  Restore from that backup now?" "y" "y" "n")"
            if [ "$DO_RESTORE" = "y" ]; then
                if run_py "$BACKUP_TOOL" --restore --from "$FOUND_BACKUP"; then
                    RESTORE_RC=0
                else
                    RESTORE_RC=$?
                fi
                if [ "$RESTORE_RC" -ne 0 ]; then
                    echo "  ${C_YELLOW}Restore reported a problem (exit $RESTORE_RC) - continuing to the wizard.${C_RESET}"
                fi
                echo
                echo "  ${C_GREEN}Restore finished. The wizard will only fill what's missing.${C_RESET}"
            fi
        fi
    else
        echo "  No backup drive detected - continuing with a fresh setup."
        echo "  (Have one? Plug it in, then: $PY_LABEL \"$BACKUP_TOOL\" --restore)"
    fi
else
    echo "  Skipped (needs Python + scripts/backup-brain.py)."
fi

# --- Finish: exit status reflects whether the required packages made it ---
finish() {
    # finish <status>: a non-zero status wins; otherwise exit 3 when a required
    # Python package is still missing for the interpreter in use.
    local rc="$1"
    if [ "$rc" -ne 0 ]; then
        exit "$rc"
    fi
    use_python || true
    local still
    still="$(missing_modules $REQUIRED_MODULES)"
    if [ -n "$still" ]; then
        local pkgs="" m
        for m in $still; do pkgs="$pkgs $(module_to_package "$m")"; done
        echo
        loud "Install finished, but required Python packages are still missing:$pkgs" \
             "Fix them with the remedy printed in Step 4, then re-run install.sh." \
             "Exiting with status 3."
        exit 3
    fi
    if [ -n "$VENV_PY" ]; then
        echo
        echo "  ${C_YELLOW}Reminder: start Claude Code from a shell where Charon's venv is active:${C_RESET}"
        echo "    . \"$(venv_activate_expected)\""
    fi
    exit 0
}

# --- Step 7: First-run wizard ---
use_python || true
WIZARD="${REPO_ROOT}/scripts/first-run.py"
WIZARD_ARGS=()
if [ -n "$NON_INTERACTIVE" ]; then WIZARD_ARGS+=(--non-interactive); fi
if [ -n "$ANSWERS" ]; then WIZARD_ARGS+=(--answers "$ANSWERS"); fi
WIZARD_FLAGS_SHOWN=""
if [ -n "$NON_INTERACTIVE" ]; then WIZARD_FLAGS_SHOWN="$WIZARD_FLAGS_SHOWN --non-interactive"; fi
if [ -n "$ANSWERS" ]; then WIZARD_FLAGS_SHOWN="$WIZARD_FLAGS_SHOWN --answers \"$ANSWERS\""; fi

if [ -n "$SKIP_FIRST_RUN" ]; then
    echo
    echo "${C_YELLOW}Skipping first-run wizard per SKIP_FIRST_RUN. Run later with:${C_RESET}"
    echo "    ${PY_LABEL:-python3} \"$WIZARD\"$WIZARD_FLAGS_SHOWN"
    finish 0
fi
echo
echo "${C_GREEN}Step 7 - Hand off to first-run wizard${C_RESET}"
if [ -z "$PY" ]; then
    echo "  ${C_RED}No Python 3 found - can't run the wizard. Install Python and re-run install.sh.${C_RESET}"
    exit 1
fi
if ! python_new_enough; then
    echo "  ${C_RED}Python $PY_VER via '$PY_LABEL' is older than 3.10 - can't run the wizard. Install Python 3.10+ and re-run install.sh.${C_RESET}"
    exit 1
fi
if [ ! -f "$WIZARD" ]; then
    echo "  ${C_RED}Wizard not found at $WIZARD${C_RESET}"
    exit 1
fi
echo
if [ -n "$DRY_RUN" ]; then
    if [ -n "$DRY_VENV" ]; then
        echo "  [dry-run] would run: \"$(venv_python_expected)\" \"$WIZARD\"$WIZARD_FLAGS_SHOWN"
    else
        echo "  [dry-run] would run: $PY_LABEL \"$WIZARD\"$WIZARD_FLAGS_SHOWN"
    fi
    finish 0
fi
# Run as a child (not exec) so the required-package check below still runs.
if run_py "$WIZARD" ${WIZARD_ARGS[@]+"${WIZARD_ARGS[@]}"}; then WIZARD_RC=0; else WIZARD_RC=$?; fi
if [ "$WIZARD_RC" -ne 0 ]; then
    if [ -n "$NON_INTERACTIVE" ]; then
        loud "The first-run wizard stopped (exit $WIZARD_RC): your profile is not set." \
             "Non-interactive, it cannot ask, so a required answer was missing or invalid." \
             "Give the answers in a file:  bash install.sh --non-interactive --answers FILE" \
             "or run the wizard yourself:  $PY_LABEL \"$WIZARD\""
    else
        echo "  ${C_YELLOW}The first-run wizard stopped (exit $WIZARD_RC). Run it again with:${C_RESET}"
        echo "    $PY_LABEL \"$WIZARD\""
    fi
fi
finish "$WIZARD_RC"
