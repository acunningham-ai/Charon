#!/usr/bin/env python3
"""
Stop hook: enforce co-change couplings — "you touched X, you should also have
touched one of Y".

WHY IT EXISTS. On the reference deployment, a memory review found the memory
system was not failing at storage or retrieval: a rule saying "public docs must
change with the code" existed, was indexed in MEMORY.md, was well-written — and
still did not fire, because a rule only fires if the agent thinks to consult it
at the moment of acting. Three hooks shipped and the entire documentation change
was editing "13 hooks" to "16 hooks".

The four always-fire rules never get missed, because `load-rules.py` INJECTS them.
Everything else is recall-dependent, and recall fails precisely when you do not
know you need it. This hook closes one class of that gap structurally: it catches
ERRORS OF OMISSION at end of turn, while they are still cheap to fix.

GENERALISES `enforce-memory-index-cochange.py`, which enforces exactly one
built-in check (a memory you save must be findable) and was proven in enforce
mode first. Same event, same transcript-parsing approach, same
loop-guard, same fail-open posture — the coupling set is data
(`cochange-couplings.json`) instead of hardcoded.

Deliberately NOT merged into that hook: it is promoted and proven, and folding a
brand-new rule set into a live enforcing control would put an unproven check
behind a trusted one's reputation.

SIGNAL: deterministic (filesystem paths from the transcript). No model judgement.

FAIL-OPEN BY DESIGN: this is a discipline/hygiene control, NOT a security
boundary. Any internal error exits 0, so a bug here can never trap a turn.

MODE:
  SHADOW = True  -> observe: log the verdict, print to stderr, exit 0.
  SHADOW = False -> enforce: exit 2, feeding the reminder back so the co-change
                    happens before the turn ends.

Loop guard: honours `stop_hook_active` — if we already blocked once this turn we
never block again, so a coupling that cannot be satisfied cannot trap the session.

Input (stdin JSON, Stop event): {session_id, transcript_path, stop_hook_active}
Exit codes: 0 = allow stop; 2 = block stop (enforce mode, positive detection only).
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

# Shadow phase: log and surface, never block. Flip to False after reviewing
# state/verdict/*.jsonl for false positives — a coupling that fires on a turn
# where the omission was legitimate is a false positive and must be fixed in the
# DATA (narrow the globs), not by switching the hook off.
#
# Ships ENFORCING. On the reference deployment the shadow window (restarted when
# the per-session dedup below was added, because that changed behaviour) ran
# three weeks: 25 observe fires, no fixture noise in the production log. Enforcing blocks the Stop once, then the loop guard
# (stop_hook_active) lets the turn end — it cannot trap a session.
# ROLLBACK: set this back to True. One line.
# A coupling that fires where the omission was legitimate is a false positive
# and gets fixed in the DATA (narrow the globs in cochange-couplings.json),
# never by switching the hook off.
SHADOW = False

HOOK_NAME = "enforce-cochange"
AUTHORING_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
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


def matches_any(path: str, globs) -> str:
    """The first glob matching `path`, or ''. Case-insensitive, forward-slashed."""
    p = path.replace("\\", "/").lower()
    for g in globs:
        try:
            if re.fullmatch(_glob_to_regex(str(g).lower()), p):
                return str(g)
        except Exception:
            continue
    return ""


def paths_written(transcript_path: str) -> list:
    """Every file path this session wrote or edited, from the Stop transcript.

    Best-effort: unparseable lines are skipped, never fatal.
    """
    seen = []
    try:
        tp = Path(transcript_path)
        if not tp.exists():
            return seen
        with tp.open(encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                msg = obj.get("message")
                content = msg.get("content") if isinstance(msg, dict) else None
                if not isinstance(content, list):
                    continue
                for block in content:
                    if not isinstance(block, dict) or block.get("type") != "tool_use":
                        continue
                    if block.get("name") not in AUTHORING_TOOLS:
                        continue
                    fp = (block.get("input") or {}).get("file_path") \
                        or (block.get("input") or {}).get("notebook_path") or ""
                    if fp:
                        seen.append(str(fp).replace("\\", "/"))
    except Exception:
        return seen
    return seen


def judge(written: list, couplings: list) -> list:
    """Pure. Returns the couplings that fired: touched X, did none of Y.

    Separated from I/O so it can be tested directly — the selftest below drives
    this function, not the hook.
    """
    fired = []
    for c in couplings:
        try:
            when = c.get("when_touched") or []
            need = c.get("requires_one_of") or []
            if not when or not need:
                continue
            trigger = ""
            for w in written:
                hit = matches_any(w, when)
                if hit:
                    trigger = w
                    break
            if not trigger:
                continue
            if any(matches_any(w, need) for w in written):
                continue  # coupling satisfied
            fired.append({
                "id": c.get("id", "?"),
                "trigger": trigger,
                "reason": c.get("reason", ""),
                "rule": c.get("rule", ""),
                "requires_one_of": need,
            })
        except Exception:
            continue
    return fired


def _state_path(session_id: str) -> Path:
    root = os.environ.get("CLAUDE_PROJECT_DIR") or str(Path(__file__).resolve().parents[2])
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session_id or "nosession")[:64]
    return Path(root) / "state" / "enforce-cochange" / f"{safe}.json"


def already_reported(session_id: str) -> set:
    """Couplings already surfaced this session.

    WHY THIS EXISTS. `paths_written()` reads the WHOLE session transcript, not
    the last turn. Without this, one unsatisfied coupling re-fires at the end of
    EVERY subsequent turn until the co-change lands — including turns that
    touched nothing relevant. The 2026-09-09 shadow review measured the cost:
    9 real fires carried only 2 distinct omissions, and a single session was
    re-reported 7 times over 1h41m for one unsatisfied coupling. In enforce mode
    that is seven interruptions for one piece of news.

    `stop_hook_active` only guards a loop WITHIN a turn; it resets between them.
    This is the across-turn half, and it mirrors `jit-memory.py`, whose
    equivalent dedup showed zero duplicates across five real fires in the same
    window.

    ACCEPTED TRADE, stated not hidden: surfacing once per session means an
    omission that is ignored is not raised again that session. That is the same
    trade `jit-memory` already makes — a reminder that repeats becomes wallpaper,
    and this is a discipline control, not a security boundary.
    """
    try:
        p = _state_path(session_id)
        if not p.is_file():
            return set()
        return set(json.loads(p.read_text(encoding="utf-8")).get("reported") or [])
    except Exception:
        return set()  # unreadable -> treat as not-yet-reported (surface again)


def record_reported(session_id: str, entries) -> None:
    """Persist surfaced coupling ids. Bookkeeping failure must never trap a turn."""
    try:
        p = _state_path(session_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        current = already_reported(session_id) | {e["id"] for e in entries}
        p.write_text(
            json.dumps({
                "reported": sorted(current),
                # diagnostics only — never read back for control flow
                "last": {e["id"]: e.get("trigger", "") for e in entries},
            }),
            encoding="utf-8",
        )
    except Exception:
        pass


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0

    # Loop guard FIRST: if we already blocked this turn, never block again.
    if data.get("stop_hook_active"):
        return 0

    transcript = data.get("transcript_path") or ""
    if not transcript:
        return 0

    try:
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        couplings = cfg.get("couplings") or []
    except Exception:
        return 0  # no config -> nothing to enforce (fail-open)
    if not couplings:
        return 0

    written = paths_written(transcript)
    if not written:
        return 0

    fired = judge(written, couplings)
    if not fired:
        return 0

    session_id = data.get("session_id", "") or ""

    # Across-turn dedup: an omission is news once per session, not once per turn.
    reported = already_reported(session_id)
    fired = [f for f in fired if f["id"] not in reported]
    if not fired:
        return 0  # already surfaced this session — do not become wallpaper

    lines = []
    for f in fired:
        emit_verdict(
            hook=HOOK_NAME,
            rule=f"cochange:{f['id']}",
            verdict="observe" if SHADOW else "ask",
            reason=("[shadow] " if SHADOW else "") + f["reason"],
            context={"coupling": f["id"], "trigger": f["trigger"],
                     "rule_pointer": f["rule"], "shadow": SHADOW,
                     "would_be": "ask" if SHADOW else None},
            session_id=session_id,
        )
        lines.append(
            f"- **{f['id']}** — you edited `{f['trigger']}`\n"
            f"  {f['reason']}\n"
            f"  Rule: `{f['rule']}`. Expected one of: "
            + ", ".join(f"`{g}`" for g in f["requires_one_of"][:4])
            + (" …" if len(f["requires_one_of"]) > 4 else "")
        )

    record_reported(session_id, fired)

    prefix = "[shadow] " if SHADOW else ""
    sys.stderr.write(
        f"{prefix}CO-CHANGE not satisfied ({len(fired)}):\n\n"
        + "\n".join(lines)
        + "\n\nThese are couplings you have already written down as rules. "
          "Do the co-change now, or say explicitly why it does not apply.\n"
    )
    return 0 if SHADOW else 2


def _selftest() -> int:
    """Drives judge() directly — proves it fires AND stays quiet."""
    couplings = [{
        "id": "t", "when_touched": ["**/Charon/scripts/hooks/*.py"],
        "requires_one_of": ["**/Charon/CAPABILITIES.md"],
        "reason": "r", "rule": "x",
    }]
    checks = [
        (len(judge(["/a/Charon/scripts/hooks/h.py"], couplings)) == 1,
         "touched code, no docs -> fires"),
        (judge(["/a/Charon/scripts/hooks/h.py", "/a/Charon/CAPABILITIES.md"], couplings) == [],
         "touched code AND docs -> quiet"),
        (judge(["/a/Charon/CAPABILITIES.md"], couplings) == [],
         "docs only -> quiet (no trigger)"),
        (judge([], couplings) == [], "nothing written -> quiet"),
        (judge(["/other/repo/x.py"], couplings) == [], "unrelated path -> quiet"),
        (judge(["/a/charon/SCRIPTS/HOOKS/H.PY"], couplings) != [],
         "case-insensitive -> fires"),
        (judge(["\\a\\Charon\\scripts\\hooks\\h.py"], couplings) != [],
         "backslash path -> fires"),
        (judge(["/a/Charon/scripts/hooks/h.py"], [{"id": "bad"}]) == [],
         "malformed coupling -> skipped, not fatal"),
    ]

    # --- across-turn dedup (the 2026-09-09 fix) -------------------------------
    # Drives the real state functions against throwaway session ids, so the
    # persistence path is exercised, not just the in-memory filter.
    s1 = "_selftest_dedup_a"
    s2 = "_selftest_dedup_b"
    for s in (s1, s2):
        try:
            _state_path(s).unlink()
        except Exception:
            pass

    hit = judge(["/a/Charon/scripts/hooks/h.py"], couplings)
    checks.append((already_reported(s1) == set(), "fresh session -> nothing reported"))
    record_reported(s1, hit)
    checks.append((already_reported(s1) == {"t"}, "after surfacing -> recorded"))
    checks.append(([f for f in hit if f["id"] not in already_reported(s1)] == [],
                   "same coupling, later turn -> suppressed"))
    checks.append((already_reported(s2) == set(), "other session unaffected"))
    checks.append(([f for f in judge(["/a/Charon/scripts/hooks/h.py"], couplings)
                    if f["id"] not in already_reported(s2)] != [],
                   "same coupling, DIFFERENT session -> still fires"))
    other = [{"id": "t2", "when_touched": ["**/Charon/scripts/hooks/*.py"],
              "requires_one_of": ["**/Charon/README.md"], "reason": "r", "rule": "x"}]
    checks.append(([f for f in judge(["/a/Charon/scripts/hooks/h.py"], other)
                    if f["id"] not in already_reported(s1)] != [],
                   "different coupling, same session -> still fires"))
    for s in (s1, s2):
        try:
            _state_path(s).unlink()
        except Exception:
            pass

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
