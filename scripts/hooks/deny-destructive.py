#!/usr/bin/env python3
"""
PreToolUse hook: block writes/edits/deletes to immutable zones in the vault.

These zones are documented as read-only in the vault root `CLAUDE.md` under
"Self-Protection". This hook is belt-and-braces over that prose rule —
catches accidental writes the human-readable rule could miss.

Default protected zones (extend in your CLAUDE.md / by editing this script):
  - **/09-Archive/**                                  (cold storage)
  - **/voice-examples/**                              (voice anchors — input only; matches any project)
  - **/.claude/projects/**/memory/sessions/**         (past session journals are immutable)
  - **/published/*.md                                 (only if `posted:` field is set; matches any project)

Exit codes:
  0  = allow (default)
  2  = block; stderr is shown to Claude as the reason

Failures during the hook itself never block — exits 0 silently.
"""
import json
import os
import re
import sys
import time
from pathlib import Path

try:
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# Verdict layer — fail-silent if absent so the hook stays operable standalone.
try:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _verdict import emit_verdict  # noqa: E402
except Exception:
    def emit_verdict(*args, **kwargs):  # type: ignore
        return kwargs.get("verdict", "allow")


# --- the confirmation channel ----------------------------------------------
#
# WHY THIS EXISTS. This hook used to block a protected-zone write and tell you to
# "ask the user to confirm before proceeding" — while providing no way for the
# user to confirm. A gate that can only say no is not an `ask`, it is a `deny`
# wearing an ask's label, and the only routes past it were the two things the
# rule itself forbids: write somewhere else, or switch the hook off. That is
# precisely how a control gets switched off.
#
# The channel is a one-shot token file naming the rule it confirms. You create it
# yourself, out of band, in your own terminal:
#
#   python -c "import json,time,pathlib; pathlib.Path('state').mkdir(exist_ok=True); \
#   pathlib.Path('state/policy-confirm.json').write_text(json.dumps( \
#   {'rule_id':'protected-zone','issued_epoch':time.time(),'granted_by':'me'}))"
#
# then re-issue the write. The token is valid for CONFIRM_TTL_SECONDS.
#
# HONEST LIMIT: this is a deliberateness speed-bump with an audit trail, not an
# agent-proof barrier — anything that can write the token can pass the gate. Its
# value is that confirming becomes a separate, explicit, logged act instead of a
# silent one, and an unexplained token in the audit log is itself a finding.
CONFIRM_TTL_SECONDS = 300

# CONSUME-ON-SUCCESS, not consume-on-check.
#
# A PreToolUse hook cannot see whether the tool it allowed actually ran. Deleting
# the token the moment this gate passes means a *later* control can deny the same
# write and the one-shot confirmation is burned for nothing — the file is not
# written and the token is gone. From your side the confirmation looks like it
# silently did nothing, which trains re-confirming repeatedly until something
# happens, and it puts an approval in the audit log for a change that never
# occurred.
#
# So the token survives repeated checks for the SAME rule_id for a short grace
# window measured from FIRST use, then is deleted. A retry after a later-gate
# denial spends the same token; a token still cannot linger.
CONFIRM_GRACE_SECONDS = 120


def _confirm_token_path() -> Path:
    """`state/policy-confirm.json` under the project root.

    CLAUDE_PROJECT_DIR is preferred when present (it is how hooks are invoked);
    otherwise derived from this file: scripts/hooks/deny-destructive.py -> root.
    """
    root = os.environ.get("CLAUDE_PROJECT_DIR") or str(Path(__file__).resolve().parents[2])
    return Path(root) / "state" / "policy-confirm.json"


def _consume_policy_confirm(rule_id: str, session_id: str = "") -> bool:
    """True if a valid, unexpired, matching confirmation token exists.

    See CONFIRM_GRACE_SECONDS: the token is marked on first use and stays
    spendable for the same rule_id until the grace window closes, then dies.
    Any doubt at all returns False — the gate holds.
    """
    if not rule_id:
        return False
    try:
        p = _confirm_token_path()
        if not p.is_file():
            return False
        tok = json.loads(p.read_text(encoding="utf-8"))
        if tok.get("rule_id") != rule_id:
            return False
        now = time.time()
        age = now - float(tok.get("issued_epoch", 0))
        if age < 0 or age > CONFIRM_TTL_SECONDS:
            p.unlink(missing_ok=True)  # expired → clear it, don't honour it
            return False

        first_used = tok.get("first_used_epoch")
        if first_used is None:
            # First pass. Mark it used but LEAVE IT, so a denied-then-retried
            # write can still spend it. Written BEFORE allowing: if this write
            # fails we fall back to one-shot rather than leave an unmarked token
            # live for the whole TTL.
            reuse = 0
            tok["first_used_epoch"] = now
            try:
                p.write_text(json.dumps(tok), encoding="utf-8")
            except Exception:
                p.unlink(missing_ok=True)
        else:
            since_first = now - float(first_used)
            if since_first < 0 or since_first > CONFIRM_GRACE_SECONDS:
                p.unlink(missing_ok=True)  # grace spent → the token is done
                return False
            reuse = int(tok.get("reuse_count", 0)) + 1
            tok["reuse_count"] = reuse
            try:
                p.write_text(json.dumps(tok), encoding="utf-8")
            except Exception:
                pass  # already authorised; failed bookkeeping is not a deny

        emit_verdict(
            hook="deny-destructive",
            rule="policy-confirmed-bypass",
            verdict="observe",
            reason=(f"rule '{rule_id}' was satisfied by an operator confirmation "
                    f"token ({int(age)}s old); "
                    + (f"RE-USE #{reuse} inside the {CONFIRM_GRACE_SECONDS}s grace "
                       f"window — an earlier gate denied the write"
                       if reuse else
                       f"first use, held {CONFIRM_GRACE_SECONDS}s for retry")),
            context={"rule_id": rule_id, "token_age_s": int(age),
                     "reuse_count": reuse, "grace_s": CONFIRM_GRACE_SECONDS,
                     "granted_by": str(tok.get("granted_by", ""))[:64]},
            session_id=session_id,
        )
        return True
    except Exception:
        return False  # any doubt → do not honour


PROTECTED_GLOBS = [
    "**/09-Archive/**",
    "**/voice-examples/**",
    "**/.claude/projects/**/memory/sessions/**",
]
PUBLISHED_GLOB = "**/published/*.md"

# Top-level frontmatter keys allowed to change on a published post.
# /linkedin-metrics writes 48h and 7d snapshots plus a qualitative reaction.
PUBLISHED_METRICS_FIELDS = {"metrics_48h", "metrics_7d", "gut_reaction", "notes"}


def glob_to_regex(glob: str) -> str:
    """Convert a glob (with `**`, `*`, `?`) to a regex string.
    `**/` and `/**` collapse zero-or-more directory segments so leading-`**/`
    matches zero-prefix paths (`**/foo` matches `foo` AND `dir/foo`).
    """
    g = glob.replace("\\", "/")
    out = []
    i = 0
    while i < len(g):
        if g[i:i + 3] == "**/":
            out.append("(?:.*/)?")
            i += 3
        elif g[i:i + 3] == "/**":
            out.append("(?:/.*)?")
            i += 3
        elif g[i:i + 2] == "**":
            out.append(".*")
            i += 2
        elif g[i] == "*":
            out.append("[^/]*")
            i += 1
        elif g[i] == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(g[i]))
            i += 1
    return "^" + "".join(out) + "$"


def matches(glob: str, path: str) -> bool:
    return re.fullmatch(glob_to_regex(glob), path.replace("\\", "/")) is not None


def split_frontmatter_blocks(fm_text: str) -> dict:
    """Split a YAML frontmatter body into top-level key blocks."""
    blocks: dict = {}
    current_key = None
    current_lines: list = []
    for line in fm_text.split("\n"):
        is_top_level = bool(line) and not line[0].isspace() and ":" in line
        if is_top_level:
            if current_key is not None:
                blocks[current_key] = "\n".join(current_lines)
            current_key = line.split(":", 1)[0].strip()
            current_lines = [line]
        else:
            if current_key is not None:
                current_lines.append(line)
    if current_key is not None:
        blocks[current_key] = "\n".join(current_lines)
    return blocks


def is_metrics_only_edit(file_path: str, old_string: str, new_string: str) -> bool:
    """Allow Edit on a published post if it only touches metrics fields."""
    try:
        original = Path(file_path).read_text(encoding="utf-8")
    except Exception:
        return False
    if old_string not in original:
        return False
    hypothetical = original.replace(old_string, new_string, 1)

    m_old = re.match(r"^---\r?\n(.*?)\r?\n---", original, re.S)
    m_new = re.match(r"^---\r?\n(.*?)\r?\n---", hypothetical, re.S)
    if not m_old or not m_new:
        return False

    if original[m_old.end():] != hypothetical[m_new.end():]:
        return False  # body changed

    blocks_old = split_frontmatter_blocks(m_old.group(1))
    blocks_new = split_frontmatter_blocks(m_new.group(1))
    if set(blocks_old.keys()) != set(blocks_new.keys()):
        return False  # top-level keys added or removed

    differing = {k for k in blocks_old if blocks_old[k] != blocks_new[k]}
    return differing.issubset(PUBLISHED_METRICS_FIELDS)


def has_posted_set(path_str: str) -> bool:
    try:
        path = Path(path_str)
        if not path.exists():
            return False
        content = path.read_text(encoding="utf-8")
        m = re.match(r"^---\r?\n(.*?)\r?\n---", content, re.S)
        if not m:
            return False
        for line in m.group(1).split("\n"):
            line = line.strip()
            if line.startswith("posted:"):
                val = line.split(":", 1)[1].strip()
                if val and val.lower() not in ("null", "~", '""', "''"):
                    return True
        return False
    except Exception:
        return False


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    tool_input = data.get("tool_input", {}) or {}
    file_path = (
        tool_input.get("file_path")
        or tool_input.get("notebook_path")
        or ""
    )
    if not file_path:
        return 0

    session_id = data.get("session_id", "") or ""

    for glob in PROTECTED_GLOBS:
        if matches(glob, file_path):
            # The answer channel. Without this the "ask the user to confirm"
            # instruction below is unanswerable — see CONFIRM_TTL_SECONDS.
            if _consume_policy_confirm("protected-zone", session_id):
                return 0
            emit_verdict(
                hook="deny-destructive", rule="protected-zone", verdict="ask",
                reason=f"`{file_path}` is in a protected zone (matched `{glob}`)",
                context={"target": file_path, "matched_glob": glob,
                         "tool_name": data.get("tool_name", "")},
                session_id=session_id,
            )
            sys.stderr.write(
                f"BLOCKED by deny-destructive hook: `{file_path}` is in a "
                f"protected zone (matched `{glob}`).\n\n"
                f"This zone is marked read-only in the vault root `CLAUDE.md` "
                f"\"Self-Protection\".\n\n"
                f"If this edit IS intentional, the user can authorise it "
                f"out-of-band and you retry — do NOT route around this by "
                f"writing to a different path or editing this hook. To "
                f"authorise, the user runs this in their own terminal from the "
                f"project root, then asks you to retry within "
                f"{CONFIRM_TTL_SECONDS // 60} minutes:\n\n"
                f"  python -c \"import json,time,pathlib;"
                f"pathlib.Path('state').mkdir(exist_ok=True);"
                f"pathlib.Path('state/policy-confirm.json').write_text("
                f"json.dumps({{'rule_id':'protected-zone',"
                f"'issued_epoch':time.time(),'granted_by':'me'}}))\"\n"
            )
            return 2

    if matches(PUBLISHED_GLOB, file_path) and has_posted_set(file_path):
        tool_name = data.get("tool_name", "")
        if tool_name == "Edit":
            if is_metrics_only_edit(
                file_path,
                tool_input.get("old_string", ""),
                tool_input.get("new_string", ""),
            ):
                return 0  # metrics-only edit, allowed
        sys.stderr.write(
            f"BLOCKED by deny-destructive hook: `{file_path}` is a published "
            f"LinkedIn post (`posted:` is set in frontmatter). These are "
            f"read-only after publishing. Metrics updates are allowed via the Edit "
            f"tool when only these top-level fields change: "
            f"{', '.join(sorted(PUBLISHED_METRICS_FIELDS))}.\n"
        )
        return 2

    return 0


if __name__ == "__main__":
    sys.exit(main())
