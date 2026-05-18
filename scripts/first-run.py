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


QUESTIONS_FILE = Path(__file__).resolve().parent / "first-run-questions.yaml"
STATE_FILE = Path.home() / ".charon-first-run-state.json"

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

def env_var_hints(env_vars: list[dict], answers: dict[str, str]) -> list[str]:
    """Return shell-snippet lines the user should add to their profile."""
    lines = []
    is_windows = sys.platform.startswith("win")
    for ev in env_vars:
        name = ev["name"]
        value = answers.get(ev.get("value_from", ""), "")
        if not value.strip():
            continue
        if is_windows:
            lines.append(f'$env:{name} = "{value}"')
        else:
            lines.append(f'export {name}="{value}"')
    return lines


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


def run_phase(phase: dict, questions: list[dict], answers: dict[str, str]) -> None:
    qs_in_phase = [q for q in questions if q["phase"] == phase["id"]]
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
        save_state(answers)


def confirm_and_write(plans, vault, mem, answers, env_lines, anthropic_target, dry_run):
    heading("Summary — what's about to happen")
    if plans:
        print("Files to create / update:")
        for target, tid, _body in plans:
            print(f"  - {target}  ({tid})")
    else:
        print("(no files to write — all template requirements unmet)")
    if anthropic_target:
        print(f"  - {anthropic_target}  (Anthropic API key, 0600)")
    if env_lines:
        print("\nEnvironment variables — add to your shell profile:")
        for line in env_lines:
            print(f"  {line}")

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

    clear_state()
    print("\nDone. State file cleared.")
    print("Re-run any time with `python scripts/first-run.py` to update individual sections.")


def main():
    parser = argparse.ArgumentParser(description="Charon first-run setup wizard")
    parser.add_argument("--logo", choices=["full", "small", "auto"], default="auto")
    parser.add_argument("--no-logo", action="store_true")
    parser.add_argument("--phase", help="run a single phase only")
    parser.add_argument("--dry-run", action="store_true")
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
    print("This wizard captures the user-specific layer the harness can't ship.")
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

    for phase in phases:
        run_phase(phase, questions, answers)

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

    confirm_and_write(plans, vault, mem, answers, env_lines, anthropic_target, args.dry_run)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nInterrupted. State saved.")
        sys.exit(130)
