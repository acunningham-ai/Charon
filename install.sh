#!/usr/bin/env bash
# Charon bootstrap installer — macOS / Linux
# -------------------------------------------
# Pre-Python bootstrap. Detects prerequisites, offers auto-install via the
# system package manager (brew on macOS, apt/dnf/pacman on Linux), or
# shows install instructions, then hands off to the first-run wizard.
#
# Usage:
#   bash install.sh
#
# Non-interactive mode (CI / unattended):
#   ACCEPT_DEFAULTS=1 bash install.sh
#
# Skip flags:
#   SKIP_PYTHON=1   skip Python detection / install
#   SKIP_OBSIDIAN=1 skip Obsidian detection / install
#   SKIP_NODE=1     skip Node detection / install
#   SKIP_FIRST_RUN=1 skip running the wizard
#
# This script will request sudo only when invoking a Linux package
# manager. On macOS, brew never needs sudo.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ACCEPT_DEFAULTS="${ACCEPT_DEFAULTS:-}"
SKIP_PYTHON="${SKIP_PYTHON:-}"
SKIP_OBSIDIAN="${SKIP_OBSIDIAN:-}"
SKIP_NODE="${SKIP_NODE:-}"
SKIP_FIRST_RUN="${SKIP_FIRST_RUN:-}"

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

py_cmd() {
    for c in python3 python; do
        if have_cmd "$c"; then
            local v
            v=$("$c" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>/dev/null || echo "")
            if [ -n "$v" ]; then
                local major minor
                major="${v%.*}"
                minor="${v##*.}"
                if [ "$major" -eq 3 ] && [ "$minor" -ge 10 ]; then
                    echo "$c"
                    return 0
                fi
            fi
        fi
    done
    return 1
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
            echo "  ${C_CYAN}Running: sudo apt-get update && sudo apt-get install -y python3 python3-pip${C_RESET}"
            sudo apt-get update && sudo apt-get install -y python3 python3-pip
            return $?
            ;;
        rhel)
            echo "  ${C_CYAN}Running: sudo dnf install -y python3 python3-pip${C_RESET}"
            sudo dnf install -y python3 python3-pip
            return $?
            ;;
        arch)
            echo "  ${C_CYAN}Running: sudo pacman -S --noconfirm python python-pip${C_RESET}"
            sudo pacman -S --noconfirm python python-pip
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
            echo "  ${C_CYAN}Running: sudo apt-get update && sudo apt-get install -y nodejs npm${C_RESET}"
            echo "  ${C_YELLOW}Note: distro nodejs may be older than 18. If so, see https://nodejs.org/ for nvm or the NodeSource setup script.${C_RESET}"
            sudo apt-get update && sudo apt-get install -y nodejs npm
            return $?
            ;;
        rhel)
            echo "  ${C_CYAN}Running: sudo dnf install -y nodejs npm${C_RESET}"
            sudo dnf install -y nodejs npm
            return $?
            ;;
        arch)
            echo "  ${C_CYAN}Running: sudo pacman -S --noconfirm nodejs npm${C_RESET}"
            sudo pacman -S --noconfirm nodejs npm
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
echo "${C_GREEN}Step 1 - Python 3.10+${C_RESET}"
if [ -n "$SKIP_PYTHON" ]; then
    echo "  Skipped per SKIP_PYTHON"
else
    if PY="$(py_cmd 2>/dev/null)"; then
        echo "  Found: $($PY --version 2>&1) via '$PY'"
    else
        echo "  ${C_YELLOW}Python 3.10+ not found.${C_RESET}"
        echo
        echo "  Install URL:  https://www.python.org/downloads/"
        case "$OS_KIND" in
            mac)    echo "  brew:         brew install python@3.12" ;;
            debian) echo "  apt:          sudo apt-get install python3 python3-pip" ;;
            rhel)   echo "  dnf:          sudo dnf install python3 python3-pip" ;;
            arch)   echo "  pacman:       sudo pacman -S python python-pip" ;;
        esac
        echo
        choice="$(ask_choice "(a)uto-install / (m)anual / (s)kip" "a" a m s)"
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
    choice="$(ask_choice "(a)uto-install / (m)anual / (s)kip - the harness works without Obsidian" "s" a m s)"
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
        choice="$(ask_choice "(a)uto-install / (m)anual / (s)kip - you can install later" "a" a m s)"
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
if PY="$(py_cmd 2>/dev/null)"; then
    REQS="${REPO_ROOT}/requirements.txt"
    if [ -f "$REQS" ]; then
        echo "  ${C_CYAN}Running: $PY -m pip install --user -r requirements.txt${C_RESET}"
        "$PY" -m pip install --user -r "$REQS" || \
            "$PY" -m pip install -r "$REQS"
    else
        echo "  ${C_YELLOW}requirements.txt not found at $REQS - skipping.${C_RESET}"
    fi
else
    echo "  ${C_YELLOW}No Python found - skipping deps. Re-run install.sh after installing Python.${C_RESET}"
fi

# --- Step 5: Secrets directory ---
echo
echo "${C_GREEN}Step 5 - Secrets directory${C_RESET}"
SECRETS_DEFAULT="${HOME}/.secrets"
SECRETS="$(ask "Where should credentials live?" "$SECRETS_DEFAULT")"
mkdir -p "$SECRETS"
chmod 700 "$SECRETS"
echo "  Created $SECRETS with mode 700"

# --- Step 6: First-run wizard ---
if [ -n "$SKIP_FIRST_RUN" ]; then
    echo
    echo "${C_YELLOW}Skipping first-run wizard per SKIP_FIRST_RUN. Run later with:${C_RESET}"
    echo "    python3 scripts/first-run.py"
    exit 0
fi
echo
echo "${C_GREEN}Step 6 - Hand off to first-run wizard${C_RESET}"
if PY="$(py_cmd 2>/dev/null)"; then
    WIZARD="${REPO_ROOT}/scripts/first-run.py"
    if [ -f "$WIZARD" ]; then
        echo
        exec "$PY" "$WIZARD"
    else
        echo "  ${C_RED}Wizard not found at $WIZARD${C_RESET}"
        exit 1
    fi
else
    echo "  ${C_RED}No Python found - can't run the wizard. Install Python and re-run install.sh.${C_RESET}"
    exit 1
fi
