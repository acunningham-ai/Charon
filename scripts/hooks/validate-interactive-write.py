#!/usr/bin/env python3
"""
PreToolUse hook: confine INTERACTIVE writes — the gap left by validate-write-path.

`validate-write-path.py` only engages when `HARNESS_UNATTENDED_ALLOWLIST` is set,
i.e. for scheduled `claude -p` runs. So an interactive command's write path was
governed by prose in its own definition and nothing else.

`/meeting-prep` made that concrete: it derives an output filename from a person's
name that **originated in a calendar event** — a string an attacker can influence
by sending an invite. Its stated rule (lower-case, strip to `[a-z0-9-]`, resolve
under `05-Meetings/`) is genuinely protective *if applied*. But that is model
adherence, not a control: nothing failed closed if the model got it wrong.

Two independent layers, because they fail differently:

  1. **protected-zone** — always on, needs no knowledge of which command is
     running. Refuses writes to secrets, hook/settings config, and anything that
     resolves outside the project root (the ..-traversal case).
  2. **command-scope** — when a command declares `write-scope:` in its
     frontmatter and `_active_command` recorded the invocation, the write must
     land inside that scope.

Verdict is **`ask`**, not `deny`, throughout. Every one of these targets is
something a person could legitimately mean to write; the failure being prevented
is a write the *model* got wrong, not one the user asked for. `ask` blocks and
explains so you can confirm and retry, which is the honest verdict for
"plausibly intentional, warrants a human".

Ships in **SHADOW** (`observe`) by default, per the shadow-before-enforce rule: a
brand-new confinement gate that blocks on day one turns every unanticipated
write into a broken command. Review the verdict log, then set `SHADOW = False`.

This hook fails **OPEN** (exit 0). That is the opposite of validate-write-path,
deliberately: that hook guards unattended runs where nobody is watching and a
crash is preferable to an unbounded write. This one runs in interactive sessions
where a bug in *it* would block a human's legitimate work with no way around it.
Availability wins for the interactive layer; the unattended layer keeps failing
closed.
"""
import fnmatch
import json
import os
import sys
from pathlib import Path

try:
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from _verdict import emit_verdict, verdict_to_exit_code, write_ask_stderr
except Exception:                                             # fail-silent per convention
    def emit_verdict(*_args, **kwargs):                       # type: ignore
        return kwargs.get("verdict", "allow")

    def verdict_to_exit_code(_v):                             # type: ignore
        return 0

    def write_ask_stderr(**_kwargs):                          # type: ignore
        pass

try:
    from _active_command import active as active_command, project_root
except Exception:
    def active_command(_session_id=""):                       # type: ignore
        return None

    def project_root():                                       # type: ignore
        return Path(__file__).resolve().parent.parent.parent

HOOK_NAME = "validate-interactive-write"
UNATTENDED_ENV = "HARNESS_UNATTENDED_ALLOWLIST"

# Shadow phase: log the verdict, never block. Flip to False after reviewing
# state/verdict/*.jsonl for false positives.
SHADOW = True

# Never writable by a command, whatever it declares. Matched against the
# project-relative POSIX path.
PROTECTED_GLOBS = (
    ".secrets/**",
    "**/.secrets/**",
    ".claude/settings.json",
    ".claude/settings.local.json",
    "scripts/hooks/**",          # a write here could disable the gates themselves
    ".git/**",
    ".gitattributes",            # pins eol=lf; losing it re-breaks the workflows (D30)
)


def _norm(p: str) -> str:
    return p.replace("\\", "/")


def _matches_any(path: str, globs) -> str:
    for g in globs:
        if fnmatch.fnmatch(path, g):
            return g
    return ""


def _decide(rule: str, reason: str, context: dict, session_id: str,
            ask_reason: str, retry_hint: str) -> int:
    """Emit the verdict and return the exit code, honouring SHADOW truthfully.

    During shadow the declared verdict is `observe`, not `ask`, with the verdict
    it *would* have been in `context.would_be`. Emitting `ask` while returning 0
    would put "effective: ask" in the audit log for a call that was never
    blocked — and an audit log that overstates enforcement is worse than no log,
    because the fortnight of review that decides whether to enforce would be
    reading fiction. `declared`/`effective` diverging is reserved for monitor
    mode, per the verdict vocabulary; this keeps that contract intact."""
    if SHADOW:
        emit_verdict(
            hook=HOOK_NAME, rule=rule, verdict="observe",
            reason=f"[shadow] {reason}",
            context={**context, "would_be": "ask", "shadow": True},
            session_id=session_id,
        )
        return 0

    effective = emit_verdict(
        hook=HOOK_NAME, rule=rule, verdict="ask", reason=reason,
        context={**context, "shadow": False}, session_id=session_id,
    )
    if effective in ("ask", "deny"):
        write_ask_stderr(rule=rule, reason=ask_reason, retry_hint=retry_hint)
    return verdict_to_exit_code(effective)


# A note written by an untrusted-reading command must carry BOTH: a machine-
# readable frontmatter key (so tools can filter) and a human/model-readable body
# line (so the warning is present at the point of reading, which is what actually
# changes behaviour — the same belt-and-braces the captured zone already uses).
PROVENANCE_KEY = "trust: derived-untrusted"
PROVENANCE_MARKER = "DERIVED FROM UNTRUSTED INPUT"

# Zones that are already governed as untrusted by the captures rule, so a note
# landing there needs no additional marker.
ALREADY_UNTRUSTED_PREFIXES = ("00-Inbox/_captured/", "00-Inbox/_harness/")


def _check_provenance(tool_input: dict, rel: str, command: str,
                      session_id: str, tool_name: str):
    """Require a provenance marker on durable notes from untrusted-reading commands.

    Returns an exit code to short-circuit on, or None to continue to layer 2.

    Only markdown notes are gated: a command may legitimately write a JSON state
    file or a log, and demanding prose markers in those would be noise that gets
    the whole gate switched off.
    """
    if not rel.lower().endswith(".md"):
        return None
    if any(rel.startswith(p) for p in ALREADY_UNTRUSTED_PREFIXES):
        return None

    content = tool_input.get("content")
    if content is None:
        # An Edit/MultiEdit carries a patch, not a whole document, so the marker
        # cannot be verified from the payload. Log the blind spot rather than
        # returning a clean pass — an unverifiable case recorded as verified is
        # how a control becomes a story about a control.
        emit_verdict(
            hook=HOOK_NAME, rule="provenance-unverifiable", verdict="observe",
            reason=(f"'{command}' reads untrusted input and wrote `{rel}` via "
                    f"{tool_name or 'a non-Write tool'}; full content not in the "
                    f"payload, so the provenance marker could not be checked"),
            context={"command": command, "target": rel, "tool_name": tool_name},
            session_id=session_id,
        )
        return None

    text = str(content)
    has_key = PROVENANCE_KEY in text
    has_marker = PROVENANCE_MARKER in text
    if has_key and has_marker:
        return None

    missing = []
    if not has_key:
        missing.append(f"frontmatter `{PROVENANCE_KEY}`")
    if not has_marker:
        missing.append(f"body marker `{PROVENANCE_MARKER}`")

    return _decide(
        rule="untrusted-provenance-missing",
        reason=(f"'{command}' reads untrusted input; note `{rel}` is missing "
                f"{' and '.join(missing)}"),
        context={"command": command, "target": rel, "missing": missing,
                 "tool_name": tool_name},
        session_id=session_id,
        ask_reason=(
            f"`/{command}` reads untrusted sources (captures, calendar events), and "
            f"`{rel}` is missing {' and '.join(missing)}.\n\n"
            f"Without it this note becomes ordinary authored content, and a later "
            f"session will treat anything quoted into it as trusted — which is how a "
            f"crafted calendar subject turns into an instruction."),
        retry_hint=(
            f"Add `{PROVENANCE_KEY}` to the frontmatter and a line containing "
            f"`{PROVENANCE_MARKER}` near the top of the body, then retry. Better "
            f"still, paraphrase the untrusted text instead of quoting it."),
    )


def main() -> int:
    # Unattended runs belong to validate-write-path.py. Double-gating would mean
    # two hooks reporting on one decision and an unclear audit trail.
    if os.environ.get(UNATTENDED_ENV):
        return 0

    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0

    tool_input = data.get("tool_input") or {}
    target = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if not target:
        return 0                                   # not a path-targeted call

    session_id = data.get("session_id", "") or ""
    root = project_root().resolve()

    # Resolve WITHOUT requiring existence: a not-yet-created file must still be
    # checked, and resolve() collapses ".." so traversal cannot hide here.
    try:
        resolved = Path(target)
        if not resolved.is_absolute():
            resolved = root / resolved
        resolved = resolved.resolve()
    except Exception:
        return 0

    try:
        rel = _norm(str(resolved.relative_to(root)))
        outside = False
    except ValueError:
        rel = _norm(str(resolved))
        outside = True

    # ---- Layer 1: protected zones + escape from the project root ----
    if outside:
        return _decide(
            rule="outside-project-root",
            reason=f"write resolves outside the project root: {rel}",
            context={"target": _norm(target), "resolved": rel,
                     "tool_name": data.get("tool_name", "")},
            session_id=session_id,
            ask_reason=(f"`{target}` resolves to `{rel}`, outside the project root "
                        f"`{root}`. Interactive commands write inside the vault."),
            retry_hint="If this is intentional, confirm and retry, or write inside "
                       "the project root.",
        )

    hit = _matches_any(rel, PROTECTED_GLOBS)
    if hit:
        return _decide(
            rule="protected-zone",
            reason=f"target `{rel}` is in a protected zone (matched `{hit}`)",
            context={"target": rel, "matched_glob": hit,
                     "tool_name": data.get("tool_name", "")},
            session_id=session_id,
            ask_reason=(f"`{rel}` is a protected path (matched `{hit}`) — secrets, "
                        f"hook code, git config and settings are not command-writable."),
            retry_hint="To change one of these, edit it directly outside a command, "
                       "or confirm and retry.",
        )

    rec = active_command(session_id)
    if not rec:
        return 0                                   # no command in flight; nothing to confine

    # ---- Layer 3: provenance on notes derived from untrusted input ----
    #
    # Checked BEFORE the scope verdict and independently of it: a note can be
    # perfectly in-scope and still launder untrusted text. Returning early on a
    # scope match would skip this entirely, which is the bug this ordering avoids.
    #
    # Captured content and calendar events are correctly untrusted IN FLIGHT: the
    # source carries `trust: untrusted` and three separate files tell the model to
    # paraphrase rather than quote. The residual is what happens when it is written
    # DOWN. A crafted calendar subject quoted verbatim into a note under
    # 05-Meetings/ becomes ordinary authored vault content, and later sessions
    # treat authored content as trusted — the hostile text crosses the trust
    # boundary by being saved, laundered from data into instruction.
    #
    # So a command that reads untrusted sources must mark what it writes, and the
    # marker is enforced here rather than requested in prose — because "remember to
    # add the marker" is the same class of instruction that already failed.
    if rec.get("reads_untrusted"):
        code = _check_provenance(
            tool_input=tool_input, rel=rel, command=rec.get("command", ""),
            session_id=session_id, tool_name=data.get("tool_name", ""),
        )
        if code is not None:
            return code

    # ---- Layer 2: the active command's declared scope ----
    scope = rec.get("write_scope")
    if not scope:
        # No declaration = unenforced, NOT permitted-by-default. Recorded as
        # `observe` so the coverage gap is visible in the audit log instead of
        # looking like a clean pass.
        emit_verdict(
            hook=HOOK_NAME, rule="no-scope-declared", verdict="observe",
            reason=(f"command '{rec.get('command')}' declares no write-scope; "
                    f"write to `{rel}` is unenforced"),
            context={"command": rec.get("command"), "target": rel},
            session_id=session_id,
        )
        return 0

    if _matches_any(rel, scope):
        return 0                                   # in scope; stay quiet

    return _decide(
        rule="out-of-command-scope",
        reason=(f"command '{rec.get('command')}' may write only within "
                f"{scope}; target `{rel}` is outside it"),
        context={"command": rec.get("command"), "target": rel,
                 "write_scope": scope, "tool_name": data.get("tool_name", "")},
        session_id=session_id,
        ask_reason=(f"`/{rec.get('command')}` declares `write-scope: {scope}` and "
                    f"`{rel}` is outside it. Either the path was derived wrongly — "
                    f"the case this gate exists for — or the command's declared scope "
                    f"is too narrow."),
        retry_hint=("Write inside the declared scope, or if the scope is genuinely "
                    "wrong, widen write-scope in the command's frontmatter deliberately "
                    "rather than to unblock a single write."),
    )


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Interactive layer fails OPEN: a bug in this hook must not block a
        # human's legitimate write with no route around it.
        sys.exit(0)
