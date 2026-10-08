#!/usr/bin/env python3
"""
PreToolUse(write) hook: just-in-time memory — surface the rule that governs a
path BEFORE the write lands, not after.

WHY IT EXISTS. On the reference deployment, a memory review found the memory
system was not failing at storage or at retrieval. A rule saying "public docs
must change with the code" existed, was indexed in MEMORY.md, and was
well-written — and it still did not fire, because a rule only fires if the agent
thinks to consult it at the moment of acting.

The asymmetry that makes this fixable: the four always-fire rules are NEVER
missed, because `load-rules.py` injects them into every prompt. Everything else
is recall-dependent, and recall fails exactly when you do not know you need it.

`load-rules.py` already solves this at PROMPT time, matching the prompt text
against a rule's `paths:`/`keywords:` frontmatter. But the misses that day
happened MID-TURN, twenty tool calls deep, with no new prompt — the decision to
edit a public doc was never in a prompt at all. So this hook moves the same idea
from prompt-time to ACTION-time: the trigger is the file you are about to write.

SHARED SOURCE OF TRUTH with `enforce-cochange.py`: both read
`cochange-couplings.json`. Same knowledge, two enforcement points —
this one is PREVENTIVE (before the write), that one is DETECTIVE (end of turn,
catching the omission). Neither can drift from the other, because there is only
one file to edit.

ONCE PER RULE PER SESSION. A reminder that fires on every write becomes
wallpaper, and wallpaper is worse than nothing because it trains the agent to
skim past the mechanism. State lives in `state/jit-memory/<session>.json`.

FAIL-OPEN BY DESIGN: a discipline control, not a security boundary. Any error
exits 0. Contrast `validate-write-path.py`, which fails closed.

MODE:
  SHADOW = True  -> observe: log what it WOULD have surfaced, exit 0, block
                    nothing. Read state/verdict/*.jsonl to judge the noise.
  SHADOW = False -> ask: exit 2 once per (rule, session) with the reminder, so
                    the rule is in context before the write is re-issued.

⚠️ MECHANISM NOTE. Enforcing mode uses exit 2 + stderr, which is the ONLY
PreToolUse channel verified to reach the model in this harness. Whether exit-0
stdout also reaches it is unverified, so this deliberately does not rely on it.
The cost of that choice: enforcing mode interrupts. The once-per-session-per-rule
cap is what keeps that affordable — a handful of interruptions per session, each
carrying a rule that would otherwise have been missed silently.

Input (stdin JSON, PreToolUse): {tool_name, tool_input:{file_path}, session_id}
Exit codes: 0 = proceed; 2 = surface the rule and let the write be re-issued.
"""
import json
import os
import re
import sys
from pathlib import Path

try:
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# Ships ENFORCING. On the reference deployment it ran three weeks in shadow
# (~0.7 fires/day across 5 couplings, no fixture noise) before promotion.
# Enforcing dedups per (rule, session), so the worst case is one interruption
# per coupling per session, not one per write.
# ROLLBACK: set this back to True. One line, nothing else to undo.
# If a coupling proves noisy the fix is to NARROW ITS GLOBS in
# cochange-couplings.json, never to switch the hook off. Broad globs such as
# `**/scripts/*.py` are the first to watch.
SHADOW = False

HOOK_NAME = "jit-memory"
WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
CONFIG_PATH = Path(__file__).resolve().parent / "cochange-couplings.json"

try:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _verdict import emit_fell_open, emit_verdict  # noqa: E402
except Exception:
    def emit_verdict(*_args, **kwargs):  # type: ignore
        return kwargs.get("verdict", "allow")

    def emit_fell_open(*_args, **_kwargs):  # type: ignore
        return "allow"


def _glob_to_regex(glob: str) -> str:
    g = glob.replace("\\", "/")
    out, i = [], 0
    while i < len(g):
        if g[i:i + 3] == "**/":
            out.append("(?:.*/)?"); i += 3
        elif g[i:i + 3] == "/**":
            out.append("(?:/.*)?"); i += 3
        elif g[i:i + 2] == "**":
            out.append(".*"); i += 2
        elif g[i] == "*":
            out.append("[^/]*"); i += 1
        elif g[i] == "?":
            out.append("[^/]"); i += 1
        else:
            out.append(re.escape(g[i])); i += 1
    return "^" + "".join(out) + "$"


def _matches_any(path: str, globs) -> str:
    p = path.replace("\\", "/").lower()
    for g in globs:
        try:
            if re.fullmatch(_glob_to_regex(str(g).lower()), p):
                return str(g)
        except Exception:
            continue
    return ""


def applicable(path: str, couplings: list) -> list:
    """Pure. Couplings whose `when_touched` matches this path.

    Separated from I/O and from the dedup state so it can be tested directly.
    """
    out = []
    for c in couplings:
        try:
            hit = _matches_any(path, c.get("when_touched") or [])
            if hit:
                out.append({"id": c.get("id", "?"), "matched_glob": hit,
                            "reason": c.get("reason", ""),
                            "rule": c.get("rule", ""),
                            "requires_one_of": c.get("requires_one_of") or []})
        except Exception:
            continue
    return out


def _state_path(session_id: str) -> Path:
    root = os.environ.get("CLAUDE_PROJECT_DIR") or str(Path(__file__).resolve().parents[2])
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id or "nosession")[:64]
    return Path(root) / "state" / "jit-memory" / f"{safe}.json"


def already_fired(session_id: str) -> set:
    try:
        p = _state_path(session_id)
        if not p.is_file():
            return set()
        return set(json.loads(p.read_text(encoding="utf-8")).get("fired") or [])
    except Exception:
        return set()  # unreadable -> treat as not-yet-fired (surface again)


def record_fired(session_id: str, ids) -> None:
    try:
        p = _state_path(session_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        current = already_fired(session_id) | set(ids)
        p.write_text(json.dumps({"fired": sorted(current)}), encoding="utf-8")
    except Exception:
        pass  # bookkeeping failure must never block a write


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    if data.get("tool_name") not in WRITE_TOOLS:
        return 0
    tool_input = data.get("tool_input") or {}
    target = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
    if not target:
        return 0

    try:
        couplings = (json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("couplings")) or []
    except Exception:
        return 0
    if not couplings:
        return 0

    hits = applicable(str(target), couplings)
    if not hits:
        return 0

    session_id = data.get("session_id", "") or ""
    fired = already_fired(session_id)
    fresh = [h for h in hits if h["id"] not in fired]
    if not fresh:
        return 0  # already surfaced this session — do not become wallpaper

    for h in fresh:
        emit_verdict(
            hook=HOOK_NAME,
            rule=f"jit:{h['id']}",
            verdict="observe" if SHADOW else "ask",
            reason=("[shadow] " if SHADOW else "") +
                   f"about to write `{target}` — {h['reason']}",
            context={"coupling": h["id"], "target": str(target).replace("\\", "/"),
                     "matched_glob": h["matched_glob"], "rule_pointer": h["rule"],
                     "shadow": SHADOW, "tool_name": data.get("tool_name", "")},
            session_id=session_id,
        )

    record_fired(session_id, [h["id"] for h in fresh])

    if SHADOW:
        return 0

    lines = []
    for h in fresh:
        lines.append(
            f"- **{h['id']}** (`{h['rule']}`)\n  {h['reason']}\n"
            f"  Also expected this turn: "
            + ", ".join(f"`{g}`" for g in h["requires_one_of"][:4])
            + (" …" if len(h["requires_one_of"]) > 4 else "")
        )
    sys.stderr.write(
        f"RULE APPLIES to `{target}` — surfaced once per session:\n\n"
        + "\n".join(lines)
        + "\n\nThis is not a block. Re-issue the write; account for the "
          "co-change in the same change, or say why it does not apply.\n"
    )
    return 2


def _selftest() -> int:
    couplings = [
        {"id": "a", "when_touched": ["**/Charon/scripts/hooks/*.py"],
         "requires_one_of": ["**/Charon/CAPABILITIES.md"], "reason": "r", "rule": "x"},
        {"id": "b", "when_touched": ["**/docs/*.html"],
         "requires_one_of": ["**/site/pages/**"], "reason": "r2", "rule": "y"},
    ]
    checks = [
        (len(applicable("/a/Charon/scripts/hooks/h.py", couplings)) == 1, "matching path -> 1 rule"),
        (applicable("/a/unrelated/x.md", couplings) == [], "unrelated -> none"),
        (len(applicable("/a/docs/page.html", couplings)) == 1, "second coupling matches"),
        (applicable("\\a\\Charon\\scripts\\hooks\\h.py", couplings) != [], "backslash -> matches"),
        (applicable("/A/CHARON/SCRIPTS/HOOKS/H.PY", couplings) != [], "case-insensitive"),
        (applicable("/a/x.py", [{"id": "bad"}]) == [], "malformed coupling -> skipped"),
        (applicable("", couplings) == [], "empty path -> none"),
    ]
    # dedup behaviour
    import tempfile
    os.environ["CLAUDE_PROJECT_DIR"] = tempfile.mkdtemp()
    checks.append((already_fired("s1") == set(), "fresh session -> nothing fired"))
    record_fired("s1", ["a"])
    checks.append((already_fired("s1") == {"a"}, "recorded id persists"))
    checks.append((already_fired("s2") == set(), "other session unaffected"))

    failed = [n for ok, n in checks if not ok]
    for ok, n in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {n}")
    print(f"\n{len(checks) - len(failed)}/{len(checks)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    try:
        sys.exit(main())
    except Exception as exc:
        # Fail-open: a bug here must never trap a turn.
        # Recorded as a FALL-OPEN so a silently broken gate is countable
        # rather than indistinguishable from a gate with nothing to say.
        try:
            emit_fell_open(hook=HOOK_NAME, rule="backstop",
                           reason="hook raised; allowing",
                           error=repr(exc))
        except Exception:
            pass
        sys.exit(0)
