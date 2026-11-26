#!/usr/bin/env python3
"""first-run.py — Charon interactive setup wizard.

Reads `scripts/first-run-questions.yaml`, walks the user through the
question flow, renders templates with their answers, writes the result
into <memory-root> and <vault-root>.

Re-runnable. State persists at `<HOME>/.charon-first-run-state.json` so
an interrupted run picks up where it left off. After a complete run, the
state file is removed; a second run treats each populated question as
"already answered" and offers keep / update / wipe.

Usage:
    python scripts/first-run.py [--logo full|small] [--no-logo]
                                 [--phase identity_paths|org_framework|voice|workflow]
                                 [--dry-run] [--non-interactive] [--answers FILE]

    --phase           Run a single phase only (re-run the voice exercise, etc.).
    --dry-run         Show planned writes; don't touch the filesystem.
    --non-interactive Never prompt. Answers come from --answers FILE, then any saved
                      state, then each question's default. A required question with
                      none of those stops the run with a list of what is missing.
                      Also the behaviour whenever stdin is not a terminal.
                      Agent Org is on by default: with no answer it is switched on
                      (and the run says so, how to turn it off, and to restart
                      Claude Code). A recorded "no" is always kept.
    --answers FILE    JSON or YAML mapping of question id to answer.

After the files are written, the wizard runs scripts/post_install_wiring.py
--mode install (same interpreter) to wire the Agent Org pane and the status line
into Claude Code, and prints the result loudly. The Agent Org answer is recorded
in ~/.charon-agent-org.json so a later check can tell "answered yes but not
registered" apart from "answered no", and so a "no" (including one recorded by
`agent_org_setup.py --disable`) is used again by every later run instead of the
default.

No external runtime deps beyond PyYAML. PyYAML missing → clear error
message + exit, no crash.
"""
from __future__ import annotations

import argparse
import getpass
import json
import os
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Any

# Make `lib.*` importable when running from anywhere
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import banner  # noqa: E402
from lib.harness_paths import memory_root, secrets_dir, vault_root  # noqa: E402

try:
    import yaml  # type: ignore
except ImportError:
    sys.stderr.write(
        "PyYAML is required for the first-run wizard.\n"
        "Install it with:  pip install pyyaml\n"
        "(Or:  pip install -r requirements.txt)\n"
    )
    sys.exit(1)


# ---------- Quick-path constants (added v0.4.2-preview) ----------
# Quick mode = 3 questions, sensible defaults for everything else.
# Solves the tester feedback that the full wizard "expects tech understanding"
# and feels long. User gets productive in ~60 seconds; refines any phase later.

# Questions Quick mode asks. Three identity + one capture y/n + (conditionally)
# two M365 fields. Other capture questions (provider, sent items, schedule)
# get implicit defaults via apply_implicit_propagations() when the user opts in.
QUICK_MODE_ASK_IDS = {
    "identity_name",
    "identity_role",
    "identity_org",
    "agent_org_enable",  # offered at install; on by default, a recorded "no" is kept
    "capture_pipeline_setup",
    "m365_tenant_id",
    "m365_client_id",
}

# Defaults applied in Quick mode for identity_paths questions we DON'T ask. Keys
# are question IDs; values are raw default strings that get passed through
# expand_default() (same path as YAML defaults). vault_path is not here: Quick
# mode uses default_vault() (HARNESS_VAULT_ROOT, else the Charon folder), never
# the current folder, and prints the path it chose.
QUICK_MODE_AUTO_DEFAULTS = {
    "secrets_path": "$home/.secrets",
    "anthropic_key_setup": "n",
}

# Questions only an explicit answer may set: their YAML default is never used (not
# with no terminal, not in catch-up, not by pressing Enter). Empty since 2026-11-26:
# the 2026-11-25 "explicit yes only" rule for agent_org_enable was reversed (Agent
# Org should be on by default), so it now takes its YAML default "y" like any other
# question. A recorded "no" still wins: see seed_agent_org_from_record().
EXPLICIT_ANSWER_ONLY: set[str] = set()
AGENT_ORG_TURN_OFF = ("To turn it off: python scripts/agent_org_setup.py --disable "
                      "(that also records a \"no\", so later updates leave it off).")


QUESTIONS_FILE = Path(__file__).resolve().parent / "first-run-questions.yaml"
STATE_FILE = Path.home() / ".charon-first-run-state.json"
# Durable record of the agent_org_enable answer. The state file above is deleted at
# the end of a complete run, so without this a later check could not tell "you said
# yes but it never got registered" from "you said no". post_install_wiring.py reads
# it (RECORD_NAME there); keep the name and the key in step.
AGENT_ORG_RECORD = Path.home() / ".charon-agent-org.json"
WIRING_SCRIPT = Path(__file__).resolve().parent / "post_install_wiring.py"
ANSWERS_FILE_MAX_BYTES = 1_000_000
ANSWER_MAX_CHARS = 20_000
ANSWER_MAX_LINES = 2_000
REPO_ROOT = Path(__file__).resolve().parent.parent
# Seconds the post-install wiring may run before it is stopped. Unattended it never
# waits for a person; interactive it may ask about replacing a status line.
# HARNESS_WIRING_TIMEOUT overrides both (whole seconds, 1 to 3600).
WIRING_TIMEOUT_UNATTENDED = 300
WIRING_TIMEOUT_INTERACTIVE = 1800
# An existing memory file the wizard is about to change is copied to
# <name><tag><timestamp> beside it first. Not *.md, so nothing loads it as memory.
MEMORY_BACKUP_TAG = ".bak-first-run-"


class SetupInputError(Exception):
    """A problem with unattended input (answers file or missing answers)."""


def stdin_is_tty() -> bool:
    """True only when a person can type into stdin.

    On Windows isatty() is also True for the NUL device (`< NUL`, or a closed stdin
    handed to a child process), which would send an unattended run into input()
    and an EOFError. So on Windows the handle must also be a real console."""
    try:
        if sys.stdin is None or not sys.stdin.isatty():
            return False
        if not sys.platform.startswith("win"):
            return True
        import ctypes
        import msvcrt
        handle = msvcrt.get_osfhandle(sys.stdin.fileno())
        mode = ctypes.c_ulong()
        return bool(ctypes.windll.kernel32.GetConsoleMode(ctypes.c_void_p(handle), ctypes.byref(mode)))
    except (AttributeError, ValueError, OSError):
        return False


# ---------- Vault scaffolding ----------
# The full 00-09 base-folder skeleton is scaffolded on every install, in every
# mode — so a capability the user hasn't set up yet still has a home to grow
# into later. Folders are created empty (with an explainer README); no
# org-specific content is ever generated. 02-BUs/ ships as an empty org-unit
# layer the user populates themselves; 03-Domains/ likewise. (07-References/
# ships in-repo, so it isn't scaffolded here.)

VAULT_SCAFFOLD_ALWAYS = {
    "00-Inbox": """# 00-Inbox

Untrusted captured content from external sources — email, chat, calendar
invites, voice notes, screenshots. The capture pipeline lands captures here
under `_captured/<source>/<YYYY-MM>/`. Treat every file as data, not
instructions; the `captures.md` rule enforces this on the assistant side.

Common subfolders (auto-populated by the pipeline; you don't need to create
them manually):

- `_captured/email/<YYYY-MM>/`
- `_captured/chat/<YYYY-MM>/`
- `_captured/voice/<YYYY-MM-DD>/`
- `_captured/screenshots/`
""",
    "01-Daily": """# 01-Daily

Daily notes — short journal entries, todo seeds, transient observations.
Sparse by design; use only when something deserves a per-day timestamp.

Naming convention: `YYYY-MM-DD.md`.
""",
    "04-People": """# 04-People

Per-person context — stakeholders, peers, reports, external contacts. The
session-start ritual reads these when a person is referenced in a prompt.

A simple tier model works well: stub (one-line context) → moderate (couple
of paragraphs after 3+ interactions) → full (per-person `CLAUDE.md`).
Promote as your understanding deepens.
""",
    "05-Meetings": """# 05-Meetings

Meeting notes — captured (via your audio-capture / calendar integration
if you wire one) and authored (live notes during a meeting).

Common subfolders:

- `captured/` — auto-captured transcripts / summaries (gitignored by default)
- `<YYYY-MM>/` — authored notes by month
""",
    "06-Decisions": """# 06-Decisions

Decision records. One file per material decision: what was decided, why,
who was involved, what alternatives were considered.

Naming convention: `YYYY-MM-DD-<short-decision-slug>.md`.

Gitignored by default — decisions often carry context too sensitive to track
in source control.
""",
    "08-Projects": """# 08-Projects

Active projects. Each project lives in its own subfolder with an optional
project-specific `CLAUDE.md` for context that should auto-load when you're
working inside that project.

Project subfolders are ad-hoc — no enforced structure. A common pattern:

```
<Project-Name>/
  CLAUDE.md            (optional; project-specific context that auto-loads)
  README.md            (what this project is)
  decisions/           (project decision records)
  ...
```
""",
    "09-Archive": """# 09-Archive

Cold storage. Move content here when it's no longer active but you may need
to reference it later.

The monthly archive script (`scripts/archive-captures.py`) moves captured
items >30 days old from `00-Inbox/_captured/` to `09-Archive/_captured/<YYYY>/`
when you opt into the recurring task.
""",
    "02-BUs": """# 02-BUs

Your org-unit layer — Org / Business Units (departments, business units,
clients, accounts, portfolio companies — whatever your business calls them;
the first-run wizard captured your term).

This base folder ships **empty on purpose**: the structure here is yours to
define. A common layout the harness's folder-derivation understands:

    02-BUs/
      _Portfolio-<Group>/        (optional grouping tier)
        <Unit-Name>/
          CLAUDE.md              (optional; unit-specific context that auto-loads)
          ...

Populate it when you're ready to track per-unit context. `/vault-lint` and
`scripts/migrate-tags.py` read this layout to derive `unit/` and `portfolio/`
tags automatically.
""",
    "03-Domains": """# 03-Domains

Cross-cutting subject areas that span multiple org units / projects. Where
`02-BUs/` organises by *who*, and `08-Projects/` organises by *what's being
built*, `03-Domains/` organises by *subject*.

Common domains in a CISO-shaped harness: Security, Incident-Response,
Vendor-Management, Compliance, Privacy, AI-Governance. Adjust for your role.
""",
}

# Reserved: previously held full-mode-only folders. All base folders now
# scaffold in every mode (see VAULT_SCAFFOLD_ALWAYS), so this is empty.
VAULT_SCAFFOLD_FULL_ONLY: dict[str, str] = {}

PHASE_TITLES_FALLBACK = {
    "identity_paths": "Identity and paths",
    "org_framework": "Org structure and framework",
    "voice": "Voice profile",
    "workflow": "Workflow and integrations",
}


# ---------- I/O helpers ----------

def hr() -> str:
    return "-" * min(70, banner.terminal_width())


def heading(text: str) -> None:
    print()
    print(hr())
    print(text)
    print(hr())


def soft(text: str) -> None:
    """Indented dim-style text for descriptions / hints."""
    print(textwrap.indent(text.rstrip(), "    "))


# ---------- YAML schema validation ----------

REQUIRED_QUESTION_FIELDS = {"id", "phase", "prompt", "type"}
ALLOWED_TYPES = {"string", "multiline", "path-dir", "path-file", "yes-no", "choice", "secret"}


def load_questions() -> dict[str, Any]:
    if not QUESTIONS_FILE.exists():
        sys.stderr.write(f"Questions file not found: {QUESTIONS_FILE}\n")
        sys.exit(1)
    try:
        data = yaml.safe_load(QUESTIONS_FILE.read_text(encoding="utf-8"))
    except yaml.YAMLError as e:
        sys.stderr.write(f"YAML parse error in {QUESTIONS_FILE}:\n{e}\n")
        sys.exit(1)
    if not isinstance(data, dict):
        sys.stderr.write("Top-level YAML must be a mapping.\n")
        sys.exit(1)

    phases = data.get("phases") or []
    questions = data.get("questions") or []
    if not phases or not questions:
        sys.stderr.write("YAML must include 'phases' and 'questions'.\n")
        sys.exit(1)

    phase_ids = {p["id"] for p in phases if isinstance(p, dict) and "id" in p}
    seen_ids = set()
    for q in questions:
        if not isinstance(q, dict):
            sys.stderr.write("Each question must be a mapping.\n")
            sys.exit(1)
        missing = REQUIRED_QUESTION_FIELDS - q.keys()
        if missing:
            sys.stderr.write(f"Question {q.get('id', '?')} missing fields: {sorted(missing)}\n")
            sys.exit(1)
        if q["id"] in seen_ids:
            sys.stderr.write(f"Duplicate question id: {q['id']}\n")
            sys.exit(1)
        seen_ids.add(q["id"])
        if q["phase"] not in phase_ids:
            sys.stderr.write(f"Question {q['id']} references unknown phase: {q['phase']}\n")
            sys.exit(1)
        if q["type"] not in ALLOWED_TYPES:
            sys.stderr.write(f"Question {q['id']} has unknown type: {q['type']}\n")
            sys.exit(1)
    return data


# ---------- State ----------

def load_state() -> dict[str, Any]:
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state: dict[str, Any]) -> None:
    try:
        STATE_FILE.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        sys.stderr.write(f"Warning: could not save state to {STATE_FILE}: {e}\n")


def clear_state() -> None:
    try:
        if STATE_FILE.exists():
            STATE_FILE.unlink()
    except Exception:
        pass


# ---------- Default + path expansion ----------

def expand_default(raw: Any) -> str:
    if raw is None:
        return ""
    s = str(raw)
    s = s.replace("$home", str(Path.home()))
    s = s.replace("$cwd", str(Path.cwd()))
    return s


def expand_path(raw: str) -> Path:
    expanded = os.path.expanduser(os.path.expandvars(raw))
    return Path(expanded).resolve()


def default_vault() -> tuple[Path, str]:
    """The vault used when no vault_path answer was given: HARNESS_VAULT_ROOT if set,
    else the Charon folder this wizard lives in. Never the current folder, which
    depends on where the wizard happened to be started from."""
    explicit = os.environ.get("HARNESS_VAULT_ROOT")
    if explicit:
        return Path(explicit).resolve(), "HARNESS_VAULT_ROOT"
    return REPO_ROOT, "the Charon folder"


# ---------- Validators ----------

def check_writable_dir(answer: str) -> tuple[bool, str]:
    """Could this folder be used (created if missing, then written)? Read-only: it
    never creates the folder or writes a probe file, so parsing, --dry-run and a
    refused run leave the disk untouched. The folder is made when files are written."""
    try:
        p = expand_path(answer)
        if p.exists():
            if not p.is_dir():
                return False, f"Path exists but is not a directory: {p}"
            nearest = p
        else:
            nearest = p.parent
            while not nearest.exists():
                if nearest.parent == nearest:
                    return False, f"No existing folder above {p}"
                nearest = nearest.parent
            if not nearest.is_dir():
                return False, f"Can't create {p}: {nearest} is not a directory"
        if not os.access(nearest, os.W_OK | os.X_OK):
            return False, f"Can't write to {nearest}"
    except (OSError, ValueError, RuntimeError) as e:
        return False, f"Can't use {answer}: {type(e).__name__}"
    return True, ""


def validate_answer(answer: str, validators: str | None) -> tuple[bool, str]:
    """Return (ok, error_message). Never writes to disk."""
    if not validators:
        return True, ""
    names = [v.strip() for v in validators.split(",") if v.strip()]
    for name in names:
        if name == "non_empty":
            if not answer.strip():
                return False, "Answer can't be blank."
        elif name == "writable_dir":
            ok, err = check_writable_dir(answer)
            if not ok:
                return False, err
        elif name == "exists_path":
            if not expand_path(answer).exists():
                return False, f"Path doesn't exist: {answer}"
    return True, ""


# ---------- Question UI ----------

def apply_implicit_propagations(answers: dict[str, str], qid: str, mode: str) -> None:
    """Quick-mode shortcut: when the user opts in to the capture pipeline, fill in
    provider + sane capture defaults so we don't ask 8 more questions. Quick mode
    is M365-only by design; Gmail / IMAP users go via `--phase workflow`."""
    if mode != "quick":
        return
    if qid == "capture_pipeline_setup" and answers.get(qid) == "y":
        answers.setdefault("capture_pipeline_provider", "m365")
        answers.setdefault("capture_sent_items", "y")
        answers.setdefault("pipeline_schedule_frequency", "daily")
        answers.setdefault("pipeline_schedule_time", "07:00")


def depends_on_satisfied(q: dict, answers: dict[str, str]) -> bool:
    deps = q.get("depends_on") or {}
    for k, expected in deps.items():
        actual = answers.get(k, "")
        if expected == "*":
            if not actual.strip():
                return False
        else:
            if actual.strip().lower() != str(expected).strip().lower():
                return False
    return True


def ask_question(q: dict, prior: str | None) -> str:
    """Prompt the user. Returns the user's answer (or prior if they 'k'eep).

    The outer function shows the question once. Inner read paths use a
    plain `> ` continuation marker so the prompt isn't duplicated.
    """
    print()
    print(f"  Q. {q['prompt']}")
    if q.get("description"):
        soft(q["description"])

    if prior is not None and prior != "":
        display = prior if q["type"] != "secret" else "(stored)"
        if "\n" in display:
            display = display.splitlines()[0] + " ..."
        print(f"    Existing: {display}")
        while True:
            choice = input("    [k]eep / [u]pdate / [w]ipe: ").strip().lower() or "k"
            if choice in ("k", "keep"):
                return prior
            if choice in ("w", "wipe"):
                return ""
            if choice in ("u", "update"):
                break
            print("    Please answer k, u, or w.")

    # An explicit-answer-only question has no default: Enter asks again.
    default = "" if q["id"] in EXPLICIT_ANSWER_ONLY else expand_default(q.get("default"))
    qtype = q["type"]
    default_hint = f" [{default}]" if default and qtype not in ("secret", "multiline") else ""

    while True:
        if qtype == "multiline":
            print("    (one per line; blank line to finish)")
            lines: list[str] = []
            while True:
                try:
                    line = input("    > ").rstrip()
                except EOFError:
                    break
                if not line:
                    break
                lines.append(line)
            answer = "\n".join(lines)
        elif qtype == "yes-no":
            raw = input(f"    (y/n){default_hint}: ").strip().lower()
            if not raw and default:
                raw = default
            if raw in ("y", "yes", "1", "true"):
                answer = "y"
            elif raw in ("n", "no", "0", "false"):
                answer = "n"
            else:
                print("    Please answer y or n.")
                continue
        elif qtype == "secret":
            try:
                answer = getpass.getpass("    > ")
            except Exception:
                answer = input("    > ")
        else:
            raw = input(f"    >{default_hint} ").rstrip()
            answer = raw if raw else default

        if not answer.strip():
            if q.get("required") and not q.get("skippable", True):
                print("    This is required — please provide an answer.")
                continue
            return ""

        ok, err = validate_answer(answer, q.get("validate"))
        if not ok:
            print(f"    {err}  Try again.")
            continue
        return answer


# ---------- Unattended input (no terminal, or --non-interactive) ----------

def _no_terminal_hint() -> str:
    return ("Give the answers in a file with --answers FILE (JSON or YAML: question id -> answer), "
            "or run the wizard in a terminal. In Git Bash (mintty) Python sees no terminal: use "
            "PowerShell or cmd, or `winpty python scripts/first-run.py`.")


def _coerce_file_answer(q: dict, value: Any) -> str:
    """Turn one answers-file value into the string the wizard stores, or raise."""
    qid, qtype = q["id"], q["type"]
    if qtype == "secret":
        raise SetupInputError(
            f"{qid}: secrets are never read from an answers file. Leave it out and run "
            f"`python scripts/first-run.py --phase {q['phase']}` in a terminal to enter it.")
    if qtype == "yes-no":
        if isinstance(value, bool):
            return "y" if value else "n"
        text = str(value).strip().lower() if isinstance(value, str) else ""
        if text in ("y", "yes", "1", "true"):
            return "y"
        if text in ("n", "no", "0", "false"):
            return "n"
        raise SetupInputError(f"{qid}: expected y or n.")
    if qtype == "multiline" and isinstance(value, list):
        # Size is checked BEFORE joining: YAML aliases let a small file repeat one
        # long string many times, so a join first could build gigabytes in memory.
        if len(value) > ANSWER_MAX_LINES:
            raise SetupInputError(f"{qid}: list answer has more than {ANSWER_MAX_LINES} lines.")
        total = 0
        for v in value:
            if not isinstance(v, str):
                raise SetupInputError(f"{qid}: every line of a list answer must be text.")
            total += len(v) + 1
            if total > ANSWER_MAX_CHARS + 1:
                raise SetupInputError(f"{qid}: list answer is longer than {ANSWER_MAX_CHARS} characters.")
        value = "\n".join(v.rstrip() for v in value)
    if not isinstance(value, str):
        # YAML reads an unquoted 07:00 as the number 420; refuse rather than guess.
        raise SetupInputError(f"{qid}: expected text; put the value in quotes.")
    if "\x00" in value or len(value) > ANSWER_MAX_CHARS:
        raise SetupInputError(f"{qid}: value is too long or holds a NUL character.")
    if qtype == "choice":
        allowed = [str(c) for c in (q.get("choices") or [])]
        if allowed and value.strip().lower() not in [c.lower() for c in allowed]:
            raise SetupInputError(f"{qid}: must be one of {', '.join(allowed)}.")
        value = value.strip().lower()
    if value.strip():
        ok, err = validate_answer(value, q.get("validate"))
        if not ok:
            raise SetupInputError(f"{qid}: {err}")
    return value


def _key_label(key: Any) -> str:
    """A short, printable name for an answers-file key, for an error message. Never
    repr() of a container (aliases could make that huge) and never longer than 60."""
    if isinstance(key, (str, int, float, bool, bytes)) or key is None:
        text = "".join(ch for ch in str(key)[:200] if ch.isprintable())
        return repr(text if len(text) <= 60 else text[:57] + "...")
    return "(a key that is not text)"


def load_answers_file(path: Path, questions: list[dict]) -> dict[str, str]:
    """Read --answers FILE (JSON or YAML mapping of question id -> answer).

    Every problem is collected and reported together; nothing is half-applied."""
    try:
        if not path.is_file():
            raise SetupInputError(f"answers file not found: {path}")
        if path.stat().st_size > ANSWERS_FILE_MAX_BYTES:
            raise SetupInputError(f"answers file is larger than {ANSWERS_FILE_MAX_BYTES} bytes: {path}")
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except SetupInputError:
        raise
    except yaml.YAMLError as exc:
        # Location only. A parser message quotes the file's own text (a snippet of
        # the line, an unknown tag), and an answers file can hold private values.
        mark = getattr(exc, "problem_mark", None) or getattr(exc, "context_mark", None)
        where = f" near line {mark.line + 1}, column {mark.column + 1}" if mark is not None else ""
        raise SetupInputError(f"could not read answers file {path}: not valid YAML or JSON{where} "
                              f"({type(exc).__name__}; the file's text is not shown).")
    except (OSError, UnicodeDecodeError) as exc:
        raise SetupInputError(f"could not read answers file {path} ({type(exc).__name__}).")
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise SetupInputError(f"answers file {path} must hold a mapping of question id -> answer.")
    by_id = {q["id"]: q for q in questions}
    out: dict[str, str] = {}
    problems: list[str] = []
    for key, value in data.items():
        if not isinstance(key, str) or key not in by_id:
            problems.append(f"{_key_label(key)}: not a question id in first-run-questions.yaml")
            continue
        try:
            out[key] = _coerce_file_answer(by_id[key], value)
        except SetupInputError as exc:
            problems.append(str(exc))
    if problems:
        raise SetupInputError("answers file " + str(path) + " has problems:\n  - " + "\n  - ".join(problems))
    return out


def resolve_unattended(q: dict, prior: str | None) -> tuple[str, str | None]:
    """Answer one question without a person: saved/file answer, then default.

    Returns (answer, problem). A problem means a required question has nothing to
    use, or its default failed validation. Never calls input()."""
    if prior is not None and str(prior).strip():
        return prior, None
    if q["id"] in EXPLICIT_ANSWER_ONLY:
        # Never a default for these: left unanswered. (Empty set since 2026-11-26.)
        return "", None
    if q["id"] == "vault_path":
        default = str(default_vault()[0])  # never the current folder
    else:
        default = expand_default(q.get("default"))
    if default.strip():
        ok, err = validate_answer(default, q.get("validate"))
        if not ok:
            return "", f"{q['id']}: default {default!r} failed validation ({err})"
        return default, None
    if q.get("required") and not q.get("skippable", True):
        return "", f"{q['id']}: required, and has no default ({q['prompt']})"
    return "", None


# ---------- Template rendering ----------

def render_multiline(value: str, mode: str = "bullets") -> str:
    """Render a multi-line answer as a bulleted markdown list."""
    lines = [line for line in (value or "").splitlines() if line.strip()]
    if not lines:
        return ""
    if mode == "bullets":
        return "\n".join(f"- {line.strip()}" for line in lines)
    return value


def substitute(template: str, answers: dict[str, str], types: dict[str, str]) -> str:
    """{{question-id}} → answer (multiline answers become bulleted lists)."""
    out = template
    for qid, value in answers.items():
        token = "{{" + qid + "}}"
        if token not in out:
            continue
        if types.get(qid) == "multiline":
            rendered = render_multiline(value)
        else:
            rendered = (value or "").strip()
        out = out.replace(token, rendered)
    # Strip any remaining unfilled tokens
    while "{{" in out and "}}" in out:
        start = out.find("{{")
        end = out.find("}}", start)
        if end == -1:
            break
        out = out[:start] + "" + out[end + 2:]
    return out


def resolve_target(target_pattern: str, vault: Path, mem: Path, repo: Path | None = None) -> Path:
    """Replace <vault-root>, <memory-root>, and <repo-root> placeholders."""
    s = target_pattern.replace("<vault-root>", str(vault))
    s = s.replace("<memory-root>", str(mem))
    if repo is not None:
        s = s.replace("<repo-root>", str(repo))
    return Path(s)


def plan_writes(
    templates: dict[str, dict],
    answers: dict[str, str],
    types: dict[str, str],
    vault: Path,
    mem: Path,
    repo: Path | None = None,
) -> list[tuple[Path, str, str]]:
    """Return [(target_path, template_id, body)] for templates whose
    'require_any' is satisfied."""
    plans: list[tuple[Path, str, str]] = []
    for tid, tdef in templates.items():
        require_any = tdef.get("require_any") or []
        if require_any and not any(answers.get(r, "").strip() for r in require_any):
            continue
        target = resolve_target(tdef["target"], vault, mem, repo)
        body = substitute(tdef["body"], answers, types)
        plans.append((target, tid, body))
    return plans


# ---------- Backups before an overwrite ----------

def backup_before_overwrite(target: Path, body: str, mem: Path) -> Path | None:
    """Copy an existing memory file that is about to change to
    <name>.bak-first-run-<timestamp> beside it. Returns the backup, or None when
    there is nothing to keep (not a memory file, new file, or same text). Raises
    OSError if the copy fails, so the caller can leave the original alone."""
    try:
        target.relative_to(mem)
    except ValueError:
        return None
    if not target.is_file():
        return None
    try:
        if target.read_text(encoding="utf-8") == body:
            return None
    except (OSError, UnicodeDecodeError):
        pass  # unreadable as text: keep a copy all the same
    stamp = time.strftime("%Y%m%d-%H%M%S")
    backup = target.with_name(f"{target.name}{MEMORY_BACKUP_TAG}{stamp}")
    n = 1
    while backup.exists():
        n += 1
        backup = target.with_name(f"{target.name}{MEMORY_BACKUP_TAG}{stamp}-{n}")
    shutil.copy2(target, backup)
    return backup


# ---------- MEMORY.md index update ----------

def update_memory_index(mem: Path, plans: list[tuple[Path, str, str]]) -> None:
    """Append entries for any new memory files to MEMORY.md."""
    index = mem / "MEMORY.md"
    new_entries: list[str] = []
    for target, _tid, _body in plans:
        try:
            rel = target.relative_to(mem)
        except ValueError:
            continue
        title = target.stem.replace("_", " ").title()
        line = f"- [{title}]({rel.as_posix()}) - populated by first-run wizard"
        new_entries.append(line)
    if not new_entries:
        return

    if index.exists():
        existing = index.read_text(encoding="utf-8")
    else:
        existing = "# Memory index\n\n"
    appended = existing
    for line in new_entries:
        slug = line.split("(")[1].split(")")[0]
        if slug in existing:
            continue
        if not appended.endswith("\n"):
            appended += "\n"
        appended += line + "\n"
    if appended != existing:
        index.write_text(appended, encoding="utf-8")


# ---------- Secrets ----------

def write_anthropic_secret(secrets: Path, api_key: str) -> Path:
    """Write ~/.secrets/anthropic.json with restricted perms."""
    secrets.mkdir(parents=True, exist_ok=True)
    target = secrets / "anthropic.json"
    target.write_text(
        json.dumps({"api_key": api_key}, indent=2) + "\n",
        encoding="utf-8",
    )
    try:
        os.chmod(target, 0o600)
        os.chmod(secrets, 0o700)
    except Exception:
        pass  # Windows / restricted FS
    return target


# ---------- Env var hints ----------

PATH_TYPE_QIDS = {"vault_path", "secrets_path"}


def env_var_hints(env_vars: list[dict], answers: dict[str, str]) -> list[str]:
    """Return shell-snippet lines the user should add to their profile."""
    lines = []
    is_windows = sys.platform.startswith("win")
    for ev in env_vars:
        name = ev["name"]
        qid = ev.get("value_from", "")
        value = answers.get(qid, "")
        if not value.strip():
            continue
        # Normalise path-type values: `$home/.secrets` joins `/` after Path.home()
        # returns `\` on Windows, producing mixed slashes in the env-var output.
        if qid in PATH_TYPE_QIDS:
            value = str(Path(value))
        if is_windows:
            lines.append(f'$env:{name} = "{value}"')
        else:
            lines.append(f'export {name}="{value}"')
    return lines


def print_capture_next_steps(cp_dir: Path, answers: dict[str, str]) -> None:
    """Print manual next-steps after npm install: auth + scheduler. These stay
    manual on purpose — device-code OAuth is interactive (browser); scheduler
    registration is platform-specific."""
    provider = answers.get("capture_pipeline_provider", "m365")
    print()
    print("Next steps to activate the capture pipeline:")
    print()
    print("  1. Run the one-time auth flow:")
    print(f"       cd {cp_dir}")
    print("       node fetch-mail.mjs auth")
    if provider == "m365":
        print("     Device-code flow — copy the code into your browser; sign in with your M365 account.")
    print()
    print("  2. Test the pipeline end-to-end:")
    print("       node fetch-mail.mjs all")
    print("     Captures should land under <vault>/00-Inbox/_captured/email/")
    print()
    print("  3. Register the scheduled task (one-time, platform-specific):")
    print("       Windows:        schtasks /Create /TN \"Charon Capture\" /TR <full-path>\\scheduled-capture.bat /SC DAILY /ST <HH:MM>")
    print("       macOS / Linux:  crontab -e   (or a launchd plist on macOS)")
    print("     See EMAIL-PROVIDER-SETUP.md §Scheduling for the platform walk-through.")


def scaffold_vault_structure(vault: Path, mode: str) -> tuple[list[str], list[str]]:
    """Create the standard vault folder structure with per-folder README.md.

    Scaffolds the full 00-09 base skeleton in every mode: 00-Inbox, 01-Daily,
    02-BUs, 03-Domains, 04-People, 05-Meetings, 06-Decisions, 08-Projects,
    09-Archive. (07-References ships in-repo.) Folders are created empty with an
    explainer README; 02-BUs is the user's org-unit layer, never populated with
    org-specific content.

    Idempotent — skips any folder or README that already exists.
    Returns (created_folders, created_readmes) for the caller to log."""
    folders = dict(VAULT_SCAFFOLD_ALWAYS)
    if mode == "full":
        folders.update(VAULT_SCAFFOLD_FULL_ONLY)

    created_folders: list[str] = []
    created_readmes: list[str] = []

    for folder_name, readme_content in folders.items():
        folder = vault / folder_name
        if not folder.exists():
            folder.mkdir(parents=True, exist_ok=True)
            created_folders.append(folder_name)
        readme = folder / "README.md"
        if not readme.exists():
            readme.write_text(readme_content, encoding="utf-8")
            created_readmes.append(folder_name)

    return created_folders, created_readmes


def bootstrap_capture_pipeline(repo: Path, answers: dict[str, str]) -> None:
    """If user opted in to the capture pipeline, run `npm install` in
    capture-pipeline/ and print manual next-steps. Fail-soft: missing Node,
    missing capture-pipeline/, or install failure prints clear recovery —
    wizard does not abort."""
    if answers.get("capture_pipeline_setup") != "y":
        return

    cp_dir = repo / "capture-pipeline"
    if not cp_dir.exists():
        print(f"\n  WARN: capture-pipeline/ not found at {cp_dir} - skipping npm install.")
        return

    print("\nBootstrapping capture pipeline...")

    shadowed = programs_in_cwd(("node", "npm"))
    if shadowed:
        print(f"  Ignored {', '.join(shadowed)} in the current folder ({Path.cwd()}): only node and npm")
        print("  found on PATH outside the current folder are run.")
    npm = resolve_npm()
    if not find_program("node") or not npm:
        print("  Node.js / npm not detected on PATH.")
        print("  Install Node 18+, then run:")
        print(f"       cd {cp_dir}")
        print("       npm install")
        print_capture_next_steps(cp_dir, answers)
        return

    try:
        # The resolved path, never bare "npm": on Windows npm is npm.cmd, which a
        # bare name cannot start (CreateProcess does not apply PATHEXT).
        subprocess.run([npm, "install"], cwd=str(cp_dir), check=True)
        print("  npm install: ok")
    except subprocess.CalledProcessError as e:
        print(f"  npm install failed (exit {e.returncode}, using {npm}). Its output is above. Run it manually:")
        print(f"       cd {cp_dir}")
        print("       npm install")
        print_capture_next_steps(cp_dir, answers)
        return
    except OSError as e:
        print(f"  npm could not be started ({npm}): {type(e).__name__}: {e}")
        print("  Run it manually:")
        print(f"       cd {cp_dir}")
        print("       npm install")
        print_capture_next_steps(cp_dir, answers)
        return

    print_capture_next_steps(cp_dir, answers)


def _pathexts() -> list[str]:
    return [e.lower() for e in (os.environ.get("PATHEXT") or ".COM;.EXE;.BAT;.CMD").split(";") if e]


def _program_names(name: str) -> list[str]:
    """File names `name` may have on disk: as given, or with each PATHEXT on Windows."""
    if sys.platform.startswith("win") and not os.path.splitext(name)[1]:
        return [name + e for e in _pathexts()]
    return [name]


def _same_dir(a: str, b: str) -> bool:
    try:
        return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))
    except (OSError, ValueError):
        return False


def find_program(name: str) -> str | None:
    """Full path to a program on PATH, never one in the current folder.

    shutil.which() is not used: on Windows it can search the current folder before
    PATH (Python versions differ), and on every platform a relative PATH entry such
    as "." resolves against the current folder. Either way a node or npm.cmd dropped
    into the folder the wizard was started from would run as the user. So only
    absolute PATH entries that are not the current folder are searched."""
    here = os.getcwd()
    win = sys.platform.startswith("win")
    for entry in (os.environ.get("PATH") or "").split(os.pathsep):
        entry = entry.strip().strip('"')
        if not entry or not os.path.isabs(entry) or _same_dir(entry, here):
            continue
        for fname in _program_names(name):
            full = os.path.join(entry, fname)
            if os.path.isfile(full) and (win or os.access(full, os.X_OK)):
                return full
    return None


def programs_in_cwd(names: tuple[str, ...]) -> list[str]:
    """Which of these programs sit in the current folder (and so are ignored)."""
    found = []
    for name in names:
        for fname in _program_names(name):
            if os.path.isfile(os.path.join(os.getcwd(), fname)):
                found.append(fname)
    return found


def resolve_npm() -> str | None:
    """Full path to npm, or None. Never one in the current folder (find_program).
    On Windows only a PATHEXT launcher (npm.cmd) is accepted: the extensionless
    `npm` beside it is a POSIX shell script that Windows cannot run directly."""
    if not sys.platform.startswith("win"):
        return find_program("npm")
    exts = _pathexts()
    for name in ("npm.cmd", "npm"):
        found = find_program(name)
        if found and os.path.splitext(found)[1].lower() in exts:
            return found
    return None


# ---------- Main flow ----------

def filter_phases(all_phases: list[dict], only: str | None) -> list[dict]:
    if not only:
        return all_phases
    matching = [p for p in all_phases if p["id"] == only]
    if not matching:
        sys.stderr.write(f"Unknown phase: {only}\n")
        sys.stderr.write(f"Valid phases: {', '.join(p['id'] for p in all_phases)}\n")
        sys.exit(1)
    return matching


def run_phase(phase: dict, questions: list[dict], answers: dict[str, str], mode: str = "full",
              interactive: bool = True, problems: list[str] | None = None) -> None:
    """Ask a phase's questions. Unattended (interactive=False): never prompts and
    never saves state; each question is resolved by resolve_unattended() and any
    problem is appended to `problems` for main() to report in one go."""
    qs_in_phase = [q for q in questions if q["phase"] == phase["id"]]
    if mode == "quick":
        # Quick mode: only ask the three identity questions; auto-defaults
        # for everything else were pre-populated into `answers` in main().
        qs_in_phase = [q for q in qs_in_phase if q["id"] in QUICK_MODE_ASK_IDS]
    if not qs_in_phase:
        return
    heading(f"[{phase['id']}] {phase.get('title', PHASE_TITLES_FALLBACK.get(phase['id'], phase['id']))}")
    if phase.get("blurb"):
        soft(phase["blurb"])
    for q in qs_in_phase:
        if not depends_on_satisfied(q, answers):
            continue
        prior = answers.get(q["id"])
        if not interactive:
            ans, problem = resolve_unattended(q, prior)
            if problem and problems is not None:
                problems.append(problem)
            answers[q["id"]] = ans
            apply_implicit_propagations(answers, q["id"], mode)
            continue
        try:
            ans = ask_question(q, prior)
        except KeyboardInterrupt:
            print("\n\nInterrupted. State saved — re-run with `python scripts/first-run.py` to resume.")
            save_state(answers)
            sys.exit(130)
        answers[q["id"]] = ans
        apply_implicit_propagations(answers, q["id"], mode)
        save_state(answers)


def confirm_and_write(plans, vault, mem, answers, env_lines, anthropic_target, dry_run, repo, mode,
                      interactive: bool = True, anthropic_key: str | None = None,
                      secrets: Path | None = None) -> bool:
    """Show the plan, then write it. Returns False only when the person declined.

    Nothing touches the disk before the confirmation (or, unattended, before this
    point): not the API key, not the secrets folder, not the vault folders."""
    heading("Summary — what's about to happen")
    if plans:
        print("Files to create / update:")
        for target, tid, _body in plans:
            print(f"  - {target}  ({tid})")
        print("  (an existing memory file that changes is first copied to"
              f" <name>{MEMORY_BACKUP_TAG}<time> beside it)")
    else:
        print("(no files to write — all template requirements unmet)")
    if anthropic_target:
        print(f"  - {anthropic_target}  (Anthropic API key, 0600)")

    scaffold_summary_folders = list(VAULT_SCAFFOLD_ALWAYS.keys())
    if mode == "full":
        scaffold_summary_folders += list(VAULT_SCAFFOLD_FULL_ONLY.keys())
    print(f"\nVault folders to scaffold under {vault} (skipped if they exist):")
    print("  " + ", ".join(sorted(scaffold_summary_folders)))
    print("  Each gets a README.md explaining its purpose. 02-BUs/ ships as an empty")
    print("  org-unit layer with a README — populate it with names that match your org.")

    if env_lines:
        print("\nEnvironment variables — add to your shell profile:")
        for line in env_lines:
            print(f"  {line}")
    if answers.get("capture_pipeline_setup") == "y":
        cp_dir = repo / "capture-pipeline"
        print(f"\nCapture pipeline: `npm install` will run in {cp_dir} after writes.")

    if dry_run:
        print("\n--dry-run: nothing written.")
        return True

    print()
    if interactive:
        ok = input("Write these files now? [Y/n]: ").strip().lower()
        if ok and ok not in ("y", "yes"):
            print("Aborted. State preserved — re-run any time.")
            return False
    else:
        print("Non-interactive run: writing without asking.")

    for target, _tid, body in plans:
        try:
            backup = backup_before_overwrite(target, body, mem)
        except OSError as exc:
            print(f"  SKIPPED {target}: could not back up the existing file first "
                  f"({type(exc).__name__}), so it was left as it was.")
            continue
        if backup:
            print(f"  backed up {target.name} to {backup}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        print(f"  wrote {target}")
    update_memory_index(mem, plans)
    print("  updated MEMORY.md")

    if secrets is not None and not secrets.exists():
        try:
            secrets.mkdir(parents=True, exist_ok=True)
            os.chmod(secrets, 0o700)
        except OSError as exc:
            print(f"  could not create the secrets folder {secrets} ({type(exc).__name__})")
        else:
            print(f"  created secrets folder {secrets}")
    if anthropic_key:
        print(f"  wrote {write_anthropic_secret(secrets or secrets_dir(), anthropic_key)}")

    created_folders, created_readmes = scaffold_vault_structure(vault, mode)
    if created_folders:
        print(f"  scaffolded vault folders: {', '.join(sorted(created_folders))}")
    if created_readmes:
        print(f"  wrote README.md in: {', '.join(sorted(created_readmes))}")
    if not created_folders and not created_readmes:
        print("  vault folder structure: already scaffolded (no changes)")

    bootstrap_capture_pipeline(repo, answers)

    clear_state()
    print("\nDone. State file cleared.")
    print("Re-run any time with `python scripts/first-run.py` to update individual sections.")
    return True


def configure_stdio_for_unicode() -> None:
    """The YAML descriptions contain Unicode (arrows, em-dashes, bullets).
    Windows defaults stdout/stderr to cp1252 in piped or non-TTY contexts,
    which crashes on `→` and friends. Force UTF-8 on Windows. Python 3.7+."""
    if sys.platform.startswith("win"):
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass


def offer_restore_from_backup() -> bool:
    """Ask, before any wizard question, whether this is a migration.

    The bootstrap installers already offer restore, but only when a backup drive
    happens to be plugged in already, and only if the user came through the
    installer at all - INSTALL.md documents running this wizard directly, which
    bypasses that path entirely. Someone rebuilding a dead laptop should not have
    to already know the restore command exists.

    So: ASK, rather than react to detection. A user whose drive is still in a bag
    gets a chance to plug it in, instead of a passive one-line hint followed by
    39 questions whose answers are sitting on that drive.

    Detection is delegated to backup-brain.py rather than reimplemented, so the
    marker contract lives in exactly one place.

    Returns True if a restore actually ran.
    """
    tool = Path(__file__).resolve().parent / "backup-brain.py"
    if not tool.is_file():
        return False

    find_target = None
    marker = ".charon-backup-target"
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("_backup_brain", tool)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        find_target, marker = mod.find_target, mod.MARKER
    except Exception:
        pass

    print()
    print("Setting up fresh, or restoring from another computer?")
    print("  A restore brings back your memory, session history and pipeline state -")
    print("  the half no cloud sync covers. Credentials are never restored.")
    print()
    try:
        answer = input("  [f]resh setup or [r]estore from backup? [f]: ").strip().lower()
    except EOFError:
        return False
    if answer not in ("r", "restore"):
        return False

    while True:
        target = find_target() if find_target else None
        if target:
            print(f"\n  Backup drive found: {target}")
            return _run_restore(tool, [])
        print(f"\n  No attached drive carries '{marker}'.")
        print("  Plug in your backup drive now, or give the path to a backup folder.")
        try:
            again = input("  [Enter] to look again, a path, or 's' to skip: ").strip()
        except EOFError:
            return False
        if again.lower() == "s":
            return False
        if again:
            src = Path(again)
            if src.is_dir():
                return _run_restore(tool, ["--from", str(src)])
            print(f"  Not a directory: {src}")


def _run_restore(tool: Path, extra: list) -> bool:
    """Invoke the restore, surfacing its output. Never raises into the wizard."""
    try:
        rc = subprocess.run([sys.executable, str(tool), "--restore"] + extra).returncode
    except Exception as exc:  # noqa: BLE001
        print(f"  Restore could not run: {exc}")
        return False
    if rc == 0:
        print("\n  Restore complete. The wizard will only fill what is missing.\n")
        return True
    print("\n  Restore did not complete. Continuing with setup - nothing was lost.\n")
    return False


def _loud(lines: list[str]) -> None:
    bar = "=" * min(70, banner.terminal_width())
    print()
    print(bar)
    for line in lines:
        print(f"  {line}")
    print(bar)


def _python_cmd() -> str:
    return "python" if os.name == "nt" else "python3"


def recorded_agent_org_answer() -> str | None:
    """'y' or 'n' from AGENT_ORG_RECORD (written by this wizard, by the wiring, and by
    `agent_org_setup.py --disable`), else None. Never raises."""
    try:
        data = json.loads(AGENT_ORG_RECORD.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    raw = str(data.get("agent_org_enable") or "").strip().lower()
    return "y" if raw in ("y", "yes") else "n" if raw in ("n", "no") else None


def seed_agent_org_from_record(answers: dict[str, str]) -> bool:
    """Agent Org is on by default, so a recorded "no" must reach every later run as
    the answer, or the default would quietly switch it back on: the state file is
    deleted after a complete run, and catch-up reads only the state file. When this
    run holds no agent_org_enable answer (state or --answers file), the recorded one
    is used as the prior answer: unattended it is kept, interactive it is offered as
    'Existing' with keep as the default. Returns True when a recorded answer was used."""
    if (answers.get("agent_org_enable") or "").strip():
        return False
    rec = recorded_agent_org_answer()
    if rec is None:
        return False
    answers["agent_org_enable"] = rec
    print(f"\nAgent Org: using your recorded answer ({'yes' if rec == 'y' else 'no'}) from {AGENT_ORG_RECORD}.")
    return True


def record_agent_org_answer(answers: dict[str, str], dry_run: bool, defaulted: bool = False) -> None:
    """Write the agent_org_enable answer to AGENT_ORG_RECORD, so a later check
    (post_install_wiring.py --check, run by /harness-doctor) can flag "answered yes
    but not registered" after the wizard's state file is gone, and so a later run
    reuses a "no". `defaulted` marks a yes that came from the default (no answer
    given), recorded as source "default" so it is visible. A blank answer records
    nothing."""
    raw = (answers.get("agent_org_enable") or "").strip().lower()
    if raw in ("y", "yes"):
        value = "y"
    elif raw in ("n", "no"):
        value = "n"
    else:
        return
    source = "default" if defaulted and value == "y" else "answer"
    if dry_run:
        print(f"\n--dry-run: would record agent_org_enable={value} ({source}) in {AGENT_ORG_RECORD}")
        return
    payload = {
        "agent_org_enable": value,
        "source": source,
        "recorded": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "recorded_by": "first-run.py",
    }
    try:
        AGENT_ORG_RECORD.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        _loud([
            f"WARNING: could not record your Agent Org answer in {AGENT_ORG_RECORD}",
            f"({type(exc).__name__}). A later check cannot tell whether you said yes.",
        ])


def agent_org_explicit(answers: dict[str, str]) -> str | None:
    """'y' or 'n' when agent_org_enable holds an explicit answer, else None."""
    raw = (answers.get("agent_org_enable") or "").strip().lower()
    if raw in ("y", "yes"):
        return "y"
    if raw in ("n", "no"):
        return "n"
    return None


def print_agent_org_default_on(dry_run: bool) -> None:
    """Loud notice for a yes that came from the default, before the wiring runs."""
    if dry_run:
        print("\nAgent Org: no answer given, so a real run would switch it ON (on by default).")
        print(f"  {AGENT_ORG_TURN_OFF}")
        return
    _loud([
        "AGENT ORG IS BEING SWITCHED ON: no answer was given, and it is on by default.",
        "Recorded as a default yes in " + str(AGENT_ORG_RECORD) + ".",
        "RESTART CLAUDE CODE afterwards to show the Agent Org pane.",
        AGENT_ORG_TURN_OFF,
    ])


def _wiring_timeout(interactive: bool) -> int:
    raw = os.environ.get("HARNESS_WIRING_TIMEOUT", "").strip()
    if raw.isdigit():
        return max(1, min(int(raw), 3600))
    return WIRING_TIMEOUT_INTERACTIVE if interactive else WIRING_TIMEOUT_UNATTENDED


def report_wiring_outcome(rc: int | None, dry_run: bool, mode: str) -> None:
    """E1: a wiring run that did not complete is repeated as the LAST lines of the
    wizard's output and on stderr, so it cannot scroll away above later output or
    show only in an exit code. Silent when the wiring completed, or on a dry run."""
    if rc == 0 or dry_run:
        return
    why = "it could not run, or timed out" if rc is None else f"exit {rc}"
    fix = f"{_python_cmd()} scripts/post_install_wiring.py --mode {mode}"
    print()
    print(f"Claude Code wiring: NOT COMPLETE ({why}). The block above names what is not wired.")
    print(f"Fix, then check: {fix}   then   {fix} --check")
    sys.stdout.flush()
    sys.stderr.write(f"Claude Code wiring did not complete ({why}). Run: {fix}\n")
    sys.stderr.flush()


def apply_agent_org(answers: dict[str, str], dry_run: bool, interactive: bool = True,
                    mode: str = "install", defaulted: bool = False) -> int | None:
    """Record the agent_org_enable answer, then run post_install_wiring.py, which
    wires the Agent Org pane (unless the answer is no) and the status line into
    Claude Code and proves both by reading the settings back.

    Agent Org is on by default (decision 2026-11-26). `defaulted` means the yes came
    from the default because no answer was given: it is recorded as a default yes
    and announced loudly here, with how to turn it off and the restart line. With
    no answer at all (blank) nothing is recorded and the wiring decides from the
    durable record, switching it on when that holds no "no".

    Same interpreter as this wizard; --non-interactive and --dry-run pass through.
    The call is stopped after _wiring_timeout() seconds. The result is printed loudly
    either way. Returns the script's exit code, or None if it could not run or timed
    out. Never fails the wizard: the files are already written."""
    record_agent_org_answer(answers, dry_run, defaulted=defaulted)
    explicit = agent_org_explicit(answers)
    if defaulted and explicit == "y":
        print_agent_org_default_on(dry_run)
    fix = f"{_python_cmd()} scripts/post_install_wiring.py --mode {mode}"
    if not WIRING_SCRIPT.is_file():
        _loud([
            "CLAUDE CODE WIRING DID NOT RUN: scripts/post_install_wiring.py is missing.",
            "The Agent Org pane and the status line are NOT set up by this install.",
            "Restore the script (run /charon-update, or re-clone), then run:",
            f"    {fix}",
        ])
        return None
    cmd = [sys.executable, str(WIRING_SCRIPT), "--mode", mode]
    if not interactive:
        cmd.append("--non-interactive")
    if dry_run:
        cmd.append("--dry-run")
    timeout = _wiring_timeout(interactive)
    print()
    print(f"Wiring Claude Code (Agent Org pane and status line): {WIRING_SCRIPT.name} --mode {mode}")
    sys.stdout.flush()
    try:
        rc = subprocess.run(cmd, timeout=timeout).returncode
    except subprocess.TimeoutExpired:
        _loud([
            f"CLAUDE CODE WIRING TIMED OUT after {timeout} seconds and was stopped.",
            "The Agent Org pane and the status line may NOT be set up. Run:",
            f"    {fix}",
        ])
        return None
    except OSError as exc:
        _loud([
            f"CLAUDE CODE WIRING COULD NOT START: {type(exc).__name__}: {exc}",
            "The Agent Org pane and the status line may NOT be set up. Run:",
            f"    {fix}",
        ])
        return None
    if rc == 0 and explicit == "n":
        _loud(["CLAUDE CODE WIRING: OK. The status line is wired; Agent Org is off, as you answered no.",
               "To turn Agent Org on later: python scripts/agent_org_setup.py",
               "Restart Claude Code if it is already open."])
    elif rc == 0:
        _loud(["CLAUDE CODE WIRING: OK. The Agent Org pane and the status line are wired.",
               "RESTART CLAUDE CODE to show the Agent Org pane if it is already open.",
               AGENT_ORG_TURN_OFF])
    elif dry_run:
        _loud([f"CLAUDE CODE WIRING (dry run, exit {rc}): nothing was changed.",
               "The lines above say what a real run would do."])
    else:
        _loud([
            f"CLAUDE CODE WIRING: NOT COMPLETE (exit {rc}).",
            "Something is NOT wired; the lines above name it and print the fix.",
            "Re-run any time:",
            f"    {fix}",
            f"Check the state any time: {_python_cmd()} scripts/post_install_wiring.py --mode {mode} --check",
        ])
    return rc


def run_catch_up(dry_run: bool = False, interactive: bool = True,
                 answers_file: Path | None = None) -> int:
    """Ask only the questions that capability shipped AFTER you installed needs.

    The gap this closes: `charon-update` pulls new code and runs
    `first-run.py --scaffold-only`, which creates folders and asks nothing. A
    question added to the wizard after your install therefore never reached you --
    so an install-wiring capability (one whose port IS a configuration step) would
    land its config file and silently stay unconfigured. Three shipped that way in
    a single release.

    This is deliberately NOT `--full`. On a Quick install most questions are
    unanswered by design, and re-asking all of them would just be the wizard again.
    Catch-up asks exactly the questions a shipped capability declares it needs,
    minus the ones already answered -- and names the capability doing the asking,
    so a question out of nowhere arrives with its reason attached.
    """
    import whats_new

    notes = whats_new.load_notes()
    answered = whats_new.answered_question_ids()
    owed = whats_new.pending_questions(notes, answered)

    block = whats_new.render(whats_new.pending_notes(notes, whats_new.load_seen()), answered)
    if block:
        print(block)

    if not owed:
        print("  Nothing to catch up on - every capability that needs a setting has one.")
        return 0

    data = load_questions()
    by_id = {q["id"]: q for q in data["questions"]}
    missing = [q for q in owed if q not in by_id]
    if missing:
        # A capability naming a question the wizard does not define is a packaging
        # error, not a user problem. Say so loudly rather than skipping quietly.
        sys.stderr.write(
            f"Warning: capability notes reference unknown question(s): {', '.join(missing)}\n"
            f"         This release is inconsistent; please report it.\n")
    askable = [by_id[q] for q in owed if q in by_id]
    if not askable:
        return 1

    heading("Catch-up - settings new capability needs from you")
    soft("Only questions a newly shipped capability declares it needs. "
         "Everything is skippable; skipping leaves the safe default in place.")

    answers = load_state()
    if answers_file is not None:
        try:
            answers.update(load_answers_file(answers_file, data["questions"]))
        except SetupInputError as exc:
            sys.stderr.write(f"Error: {exc}\n")
            return 2
    # A recorded "no" (e.g. from agent_org_setup.py --disable) is kept, never defaulted over.
    seed_agent_org_from_record(answers)
    agent_org_had_answer = bool((answers.get("agent_org_enable") or "").strip())
    left_open: list[str] = []
    for q in askable:
        owners = whats_new.questions_owed_by(notes, q["id"])
        if owners:
            soft(f"needed by: {', '.join(owners)}")
        if not depends_on_satisfied(q, answers):
            continue
        if not interactive:
            # Catch-up questions are all skippable: a default is used, a file answer
            # wins, and anything with neither stays owed for a later run.
            ans, _problem = resolve_unattended({**q, "required": False}, answers.get(q["id"]))
            if ans.strip():
                answers[q["id"]] = ans
                print(f"  {q['id']}: {ans if q['type'] != 'secret' else '(stored)'}  (no terminal: default or file answer)")
            else:
                left_open.append(q["id"])
            continue
        try:
            answers[q["id"]] = ask_question(q, answers.get(q["id"]))
        except KeyboardInterrupt:
            print("\n\nInterrupted. Answers so far are saved; re-run --catch-up to finish.")
            save_state(answers)
            return 130
        save_state(answers)

    if not interactive:
        if not dry_run:
            save_state(answers)
        if left_open:
            print(f"\n  Left unanswered (no default and no terminal): {', '.join(left_open)}")
            print(f"  {_no_terminal_hint()}")

    # Render only the templates that actually consume a newly-answered question --
    # a catch-up must never rewrite files unrelated to what it just asked.
    fresh = {q["id"] for q in askable if answers.get(q["id"], "").strip()}
    wiring_ran, wiring_rc = False, None
    if "agent_org_enable" in fresh:
        # Catch-up is the /charon-update path, so the wiring runs in update mode.
        defaulted = not interactive and not agent_org_had_answer
        wiring_rc = apply_agent_org(answers, dry_run, interactive=interactive, mode="update",
                                    defaulted=defaulted)
        wiring_ran = True

    def finish(code: int) -> int:
        if wiring_ran:  # last, so a wiring failure is the final thing on screen (E1)
            report_wiring_outcome(wiring_rc, dry_run, "update")
        return code

    templates = data.get("templates") or {}
    touched = {tid: t for tid, t in templates.items()
               if any(f"{{{{{qid}}}}}" in (t.get("body") or "") for qid in fresh)}
    if not touched:
        print("\nAnswers saved. No files needed rewriting.")
        return finish(0)

    types = {q["id"]: q.get("type", "string") for q in data["questions"]}
    vault, mem = vault_root(), memory_root()
    plans = plan_writes(touched, answers, types, vault, mem, Path(__file__).resolve().parents[1])
    print("\nFiles to update:")
    for target, tid, _ in plans:
        print(f"  - {target}  ({tid})")
    if dry_run:
        print("\n--dry-run: nothing written")
        return finish(0)
    if interactive and (input("\nProceed? [Y/n]: ").strip().lower() or "y") not in ("y", "yes"):
        print("Nothing written. Answers are saved; re-run --catch-up when ready.")
        return finish(0)
    written = 0
    for target, _tid, body in plans:
        try:
            backup = backup_before_overwrite(target, body, mem)
        except OSError as exc:
            print(f"  SKIPPED {target}: could not back up the existing file first ({type(exc).__name__}).")
            continue
        if backup:
            print(f"  backed up {target.name} to {backup}")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        written += 1
    print(f"Wrote {written} file(s).")
    return finish(0)


def main():
    configure_stdio_for_unicode()
    parser = argparse.ArgumentParser(description="Charon first-run setup wizard")
    parser.add_argument("--logo", choices=["full", "small", "auto"], default="auto")
    parser.add_argument("--no-logo", action="store_true")
    parser.add_argument("--phase", help="run a single phase only")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--no-restore-prompt",
        action="store_true",
        help="Skip the 'fresh setup or restore from backup?' question. For automation, "
             "or when you know this is a fresh install.",
    )
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Express install: 3 questions, sensible defaults for everything else. ~60 seconds.",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Full install: all 27 questions across 5 phases. ~20 minutes. (In a terminal with neither "
             "--quick nor --full, the wizard asks which; without a terminal it uses --quick.)",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Never prompt (also automatic when stdin is not a terminal). Answers come from "
             "--answers, then saved state, then each question's default; a required question "
             "with none of those stops the run and lists what is missing, writing nothing.",
    )
    parser.add_argument(
        "--answers",
        type=Path,
        metavar="FILE",
        help="JSON or YAML file mapping question ids to answers, e.g. "
             '{"identity_name": "...", "identity_role": "...", "identity_org": "..."}. '
             "Secrets are never read from it.",
    )
    parser.add_argument(
        "--scaffold-only",
        action="store_true",
        help="Ensure the 00-09 base-folder skeleton exists under the configured vault "
             "root, then exit. Idempotent; asks no questions. Used by /charon-update "
             "after a self-update so newly-added base folders land one-touch.",
    )
    parser.add_argument(
        "--catch-up",
        action="store_true",
        help="Ask only the settings that capability shipped since your install needs, "
             "and show what those capabilities give you. Run by /charon-update; safe "
             "to run by hand any time. Not the full wizard.",
    )
    args = parser.parse_args()
    # One switch for every prompt in the wizard: no terminal means no input() call.
    interactive = stdin_is_tty() and not args.non_interactive

    if args.catch_up:
        sys.exit(run_catch_up(dry_run=args.dry_run, interactive=interactive, answers_file=args.answers))

    if args.scaffold_only:
        vault = vault_root()
        created_folders, created_readmes = scaffold_vault_structure(vault, mode="full")
        touched = sorted(set(created_folders) | set(created_readmes))
        if touched:
            print(f"Scaffolded base folders under {vault}: {', '.join(touched)}")
        else:
            print(f"Base folders already present under {vault} — nothing to do.")
        return

    if args.no_logo:
        banner.print_banner(no_logo=True)
    elif args.logo == "full":
        banner.print_banner(force_full=True)
    elif args.logo == "small":
        banner.print_banner(force_small=True)
    else:
        banner.print_banner()

    print("Welcome to Charon — second-brain harness for Claude Code.")
    print("Press Ctrl+C any time — your progress is saved and you can resume later.")

    # Offered BEFORE any question: a migrating user's answers already exist on the
    # backup drive. Skipped for --dry-run and non-interactive runs so automation and
    # CI are never blocked on a prompt.
    if not args.no_restore_prompt and not args.dry_run and interactive:
        offer_restore_from_backup()

    data = load_questions()
    phases = filter_phases(data["phases"], args.phase)
    questions = data["questions"]
    templates = data.get("templates") or {}
    env_vars = data.get("env_vars") or []

    answers = load_state()
    if answers:
        print(f"\nResuming from saved state: {STATE_FILE}")
        print(f"  ({len(answers)} prior answers)")
    fresh_start = not answers
    if args.answers is not None:
        try:
            from_file = load_answers_file(args.answers, questions)
        except SetupInputError as exc:
            sys.stderr.write(f"Error: {exc}\n")
            sys.exit(2)
        answers.update(from_file)
        print(f"\nUsing {len(from_file)} answer(s) from {args.answers}")
    # Agent Org is on by default, so a recorded "no" must count as this run's answer.
    seed_agent_org_from_record(answers)
    agent_org_had_answer = bool((answers.get("agent_org_enable") or "").strip())
    if not interactive:
        print("\nNon-interactive: no prompts. Answers come from --answers, saved state, then defaults.")

    # ---------- Mode selection (quick vs full) ----------
    # Mode is only relevant when starting fresh (no resume state) and not
    # already targeted with --phase. Otherwise we always run full breadth
    # within the requested scope.
    mode = "full"
    if args.phase:
        mode = "full"  # --phase always runs that phase's full question set
    elif args.quick and args.full:
        print(
            "\nBoth --quick and --full specified. They're mutually exclusive — defaulting to --full."
        )
        mode = "full"
    elif args.quick:
        mode = "quick"
    elif args.full:
        mode = "full"
    elif fresh_start and not interactive:
        mode = "quick"  # no terminal to ask which; quick needs the fewest answers
    elif fresh_start:
        # Fresh start, no flag → interactive prompt
        print()
        print("How configured do you want to start?")
        print()
        print("  1. Quick — 3 questions, ~60 seconds. Sensible defaults for everything else.")
        print("            Get productive immediately; refine any phase later with --phase.")
        print()
        print("  2. Full  — 27 questions across 5 phases, ~20 minutes. Voice, org structure,")
        print("            framework, integrations all captured up front.")
        print()
        while True:
            choice = input("  Choice [1/2, default 1]: ").strip() or "1"
            if choice in ("1", "q", "quick"):
                mode = "quick"
                break
            if choice in ("2", "f", "full"):
                mode = "full"
                break
            print("  Please answer 1 or 2.")
    # else: resuming a partial run, no flags → continue in full mode

    if mode == "quick":
        print()
        soft(
            "Quick mode — four questions (name, role, organisation, and whether to turn on Agent Org). "
            "Vault path defaults to HARNESS_VAULT_ROOT, else the Charon folder; secrets to ~/.secrets, "
            "Anthropic-key setup deferred, voice / framework / integrations skipped. "
            "You can refine any of those any time with `python scripts/first-run.py --phase <name>`."
        )
        # Pre-populate the auto-default answers so run_phase doesn't ask them
        # AND so downstream rendering / env-var hints have the right values.
        for qid, raw_default in QUICK_MODE_AUTO_DEFAULTS.items():
            if qid not in answers:
                answers[qid] = expand_default(raw_default)
        if not answers.get("vault_path"):
            answers["vault_path"] = str(default_vault()[0])  # never the current folder
        if interactive:
            save_state(answers)

    problems: list[str] = []
    for phase in phases:
        run_phase(phase, questions, answers, mode=mode, interactive=interactive, problems=problems)

    if problems:
        # Unattended and something required has no answer: stop before writing
        # anything (no state file either), and name every gap at once.
        sys.stderr.write(
            "\nError: setup cannot finish without a terminal. These answers are missing or invalid:\n"
            + "".join(f"  - {p}\n" for p in problems)
            + _no_terminal_hint() + "\nNothing was written.\n")
        sys.exit(2)

    default_vault_path, default_vault_source = default_vault()
    vault = expand_path(answers.get("vault_path") or str(default_vault_path))
    if vault == default_vault_path.resolve():
        print(f"\nVault: {vault}  ({default_vault_source}; set vault_path to choose another)")
    else:
        print(f"\nVault: {vault}")
    if answers.get("vault_path"):
        os.environ["HARNESS_VAULT_ROOT"] = str(vault)
    secrets = expand_path(answers.get("secrets_path") or str(Path.home() / ".secrets"))
    if answers.get("secrets_path"):
        os.environ["HARNESS_SECRETS_DIR"] = str(secrets)
    mem = memory_root()

    types = {q["id"]: q["type"] for q in questions}
    repo = Path(__file__).resolve().parent.parent
    plans = plan_writes(templates, answers, types, vault, mem, repo)

    # The key is written by confirm_and_write, after the confirmation: a declined or
    # dry run must not leave a secrets folder or key file behind.
    anthropic_target = None
    anthropic_key = None
    if answers.get("anthropic_key_setup") == "y" and answers.get("anthropic_key_value"):
        anthropic_target = secrets / "anthropic.json"
        anthropic_key = answers["anthropic_key_value"]

    env_lines = env_var_hints(env_vars, answers)

    written = confirm_and_write(plans, vault, mem, answers, env_lines, anthropic_target,
                                args.dry_run, repo, mode, interactive=interactive,
                                anthropic_key=anthropic_key, secrets=secrets)
    # Wire Claude Code after a whole-wizard run or a workflow re-run (where the Agent
    # Org question lives). Other single-phase refinements leave the wiring alone.
    wiring_ran, wiring_rc = False, None
    if not written:
        print("Claude Code wiring skipped because nothing was written. Run it on its own any time:")
        print(f"    {_python_cmd()} scripts/post_install_wiring.py --mode install")
    elif not args.phase or args.phase == "workflow":
        # A yes nobody typed: no terminal, and no answer in state, file or record.
        defaulted = not interactive and not agent_org_had_answer
        wiring_rc = apply_agent_org(answers, args.dry_run, interactive=interactive, mode="install",
                                    defaulted=defaulted)
        wiring_ran = True

    # Quick-mode tail: explicit refinement-commands print so the user knows
    # exactly what to run to deepen any phase later. No-op for full mode
    # since the existing "Re-run any time" line already covers it.
    if mode == "quick" and not args.dry_run:
        print()
        print("Quick install complete. To refine any phase later:")
        print()
        print("  python scripts/first-run.py --phase identity_paths   # vault path, secrets, Anthropic key")
        print("  python scripts/first-run.py --phase org_framework    # org-units, audience tiers, framework")
        print("  python scripts/first-run.py --phase voice            # your writing voice (6 short questions)")
        print("  python scripts/first-run.py --phase workflow         # standing rules + optional integrations")
        print("  python scripts/first-run.py --phase engines          # research beats / newsletter senders / forums")
        print()
        print("Or run `python scripts/first-run.py` again to walk every phase in --full mode.")

    # Last, so a wiring failure is the final thing on screen (E1).
    if wiring_ran:
        report_wiring_outcome(wiring_rc, args.dry_run, "install")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted. State saved.")
        sys.exit(130)
