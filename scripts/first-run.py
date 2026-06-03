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
                                 [--dry-run]

    --phase   Run a single phase only (re-run the voice exercise, etc.).
    --dry-run Show planned writes; don't touch the filesystem.

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
    "capture_pipeline_setup",
    "m365_tenant_id",
    "m365_client_id",
}

# Defaults applied silently in Quick mode for identity_paths questions
# we DON'T ask. Keys are question IDs; values are raw default strings that
# get passed through expand_default() (same path as YAML defaults).
QUICK_MODE_AUTO_DEFAULTS = {
    "vault_path": "$cwd",
    "secrets_path": "$home/.secrets",
    "anthropic_key_setup": "n",
}


QUESTIONS_FILE = Path(__file__).resolve().parent / "first-run-questions.yaml"
STATE_FILE = Path.home() / ".charon-first-run-state.json"


# ---------- Vault scaffolding ----------
# Folders + README.md scaffolded on every install. 02-BUs/ is NEVER scaffolded
# (user-defined org-unit layer — departments, business units, clients, etc.);
# 03-Domains/ is full-mode only (term lands once the framework / critical-
# controls questions have given it context).

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

Meeting notes — captured (via Plaud / calendar integration if you wire one)
and authored (live notes during a meeting).

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
}

VAULT_SCAFFOLD_FULL_ONLY = {
    "03-Domains": """# 03-Domains

Cross-cutting subject areas that span multiple org units / projects. Where
`02-BUs/` organises by *who*, and `08-Projects/` organises by *what's being
built*, `03-Domains/` organises by *subject*.

Common domains in a CISO-shaped harness: Security, Incident-Response,
Vendor-Management, Compliance, Privacy, AI-Governance. Adjust for your role.
""",
}

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


# ---------- Validators ----------

def validate_answer(answer: str, validators: str | None) -> tuple[bool, str]:
    """Return (ok, error_message)."""
    if not validators:
        return True, ""
    names = [v.strip() for v in validators.split(",") if v.strip()]
    for name in names:
        if name == "non_empty":
            if not answer.strip():
                return False, "Answer can't be blank."
        elif name == "writable_dir":
            try:
                p = expand_path(answer)
                if p.exists() and not p.is_dir():
                    return False, f"Path exists but is not a directory: {p}"
                if not p.exists():
                    p.mkdir(parents=True, exist_ok=True)
                test = p / ".charon-write-test"
                test.write_text("ok", encoding="utf-8")
                test.unlink()
            except Exception as e:
                return False, f"Can't write to {answer}: {e}"
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

    default = expand_default(q.get("default"))
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

    Always scaffolds: 00-Inbox, 01-Daily, 04-People, 05-Meetings, 06-Decisions,
    08-Projects, 09-Archive.
    Quick mode skips 03-Domains; Full mode includes it.
    NEVER scaffolds 02-BUs (user-defined org layer).

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

    if not shutil.which("node") or not shutil.which("npm"):
        print("  Node.js / npm not detected on PATH.")
        print("  Install Node 18+, then run:")
        print(f"       cd {cp_dir}")
        print("       npm install")
        print_capture_next_steps(cp_dir, answers)
        return

    try:
        subprocess.run(["npm", "install"], cwd=str(cp_dir), check=True)
        print("  npm install: ok")
    except subprocess.CalledProcessError as e:
        print(f"  npm install failed (exit {e.returncode}). Run it manually:")
        print(f"       cd {cp_dir}")
        print("       npm install")
        print_capture_next_steps(cp_dir, answers)
        return
    except FileNotFoundError:
        print("  npm not found on PATH (race with Node install?). Run manually:")
        print(f"       cd {cp_dir}")
        print("       npm install")
        print_capture_next_steps(cp_dir, answers)
        return

    print_capture_next_steps(cp_dir, answers)


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


def run_phase(phase: dict, questions: list[dict], answers: dict[str, str], mode: str = "full") -> None:
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
        try:
            ans = ask_question(q, prior)
        except KeyboardInterrupt:
            print("\n\nInterrupted. State saved — re-run with `python scripts/first-run.py` to resume.")
            save_state(answers)
            sys.exit(130)
        answers[q["id"]] = ans
        apply_implicit_propagations(answers, q["id"], mode)
        save_state(answers)


def confirm_and_write(plans, vault, mem, answers, env_lines, anthropic_target, dry_run, repo, mode):
    heading("Summary — what's about to happen")
    if plans:
        print("Files to create / update:")
        for target, tid, _body in plans:
            print(f"  - {target}  ({tid})")
    else:
        print("(no files to write — all template requirements unmet)")
    if anthropic_target:
        print(f"  - {anthropic_target}  (Anthropic API key, 0600)")

    scaffold_summary_folders = list(VAULT_SCAFFOLD_ALWAYS.keys())
    if mode == "full":
        scaffold_summary_folders += list(VAULT_SCAFFOLD_FULL_ONLY.keys())
    print(f"\nVault folders to scaffold under {vault} (skipped if they exist):")
    print("  " + ", ".join(sorted(scaffold_summary_folders)))
    print("  Each gets a README.md explaining its purpose. 02-BUs/ is your org-unit")
    print("  layer — you create it yourself with names that match your org.")

    if env_lines:
        print("\nEnvironment variables — add to your shell profile:")
        for line in env_lines:
            print(f"  {line}")
    if answers.get("capture_pipeline_setup") == "y":
        cp_dir = repo / "capture-pipeline"
        print(f"\nCapture pipeline: `npm install` will run in {cp_dir} after writes.")

    if dry_run:
        print("\n--dry-run: nothing written.")
        return

    print()
    ok = input("Write these files now? [Y/n]: ").strip().lower()
    if ok and ok not in ("y", "yes"):
        print("Aborted. State preserved — re-run any time.")
        return

    for target, _tid, body in plans:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        print(f"  wrote {target}")
    update_memory_index(mem, plans)
    print("  updated MEMORY.md")

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


def main():
    configure_stdio_for_unicode()
    parser = argparse.ArgumentParser(description="Charon first-run setup wizard")
    parser.add_argument("--logo", choices=["full", "small", "auto"], default="auto")
    parser.add_argument("--no-logo", action="store_true")
    parser.add_argument("--phase", help="run a single phase only")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--quick",
        action="store_true",
        help="Express install: 3 questions, sensible defaults for everything else. ~60 seconds.",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Full install: all 24 questions across 4 phases. ~20 minutes. (Default if --quick not set and not interactive.)",
    )
    args = parser.parse_args()

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

    data = load_questions()
    phases = filter_phases(data["phases"], args.phase)
    questions = data["questions"]
    templates = data.get("templates") or {}
    env_vars = data.get("env_vars") or []

    answers = load_state()
    if answers:
        print(f"\nResuming from saved state: {STATE_FILE}")
        print(f"  ({len(answers)} prior answers)")

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
    elif not answers:
        # Fresh start, no flag → interactive prompt
        print()
        print("How configured do you want to start?")
        print()
        print("  1. Quick — 3 questions, ~60 seconds. Sensible defaults for everything else.")
        print("            Get productive immediately; refine any phase later with --phase.")
        print()
        print("  2. Full  — 24 questions across 4 phases, ~20 minutes. Voice, org structure,")
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
            "Quick mode — three questions (name, role, organisation). "
            "Vault path defaults to current directory, secrets to ~/.secrets, "
            "Anthropic-key setup deferred, voice / framework / integrations skipped. "
            "You can refine any of those any time with `python scripts/first-run.py --phase <name>`."
        )
        # Pre-populate the auto-default answers so run_phase doesn't ask them
        # AND so downstream rendering / env-var hints have the right values.
        for qid, raw_default in QUICK_MODE_AUTO_DEFAULTS.items():
            if qid not in answers:
                answers[qid] = expand_default(raw_default)
        save_state(answers)

    for phase in phases:
        run_phase(phase, questions, answers, mode=mode)

    vault = expand_path(answers.get("vault_path") or str(Path.cwd()))
    if answers.get("vault_path"):
        os.environ["HARNESS_VAULT_ROOT"] = str(vault)
    secrets = expand_path(answers.get("secrets_path") or str(Path.home() / ".secrets"))
    if answers.get("secrets_path"):
        os.environ["HARNESS_SECRETS_DIR"] = str(secrets)
    mem = memory_root()

    types = {q["id"]: q["type"] for q in questions}
    repo = Path(__file__).resolve().parent.parent
    plans = plan_writes(templates, answers, types, vault, mem, repo)

    anthropic_target = None
    if answers.get("anthropic_key_setup") == "y" and answers.get("anthropic_key_value"):
        if not args.dry_run:
            anthropic_target = write_anthropic_secret(secrets, answers["anthropic_key_value"])
        else:
            anthropic_target = secrets / "anthropic.json"

    env_lines = env_var_hints(env_vars, answers)

    confirm_and_write(plans, vault, mem, answers, env_lines, anthropic_target, args.dry_run, repo, mode)

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
        print()
        print("Or run `python scripts/first-run.py` again to walk every phase in --full mode.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted. State saved.")
        sys.exit(130)
