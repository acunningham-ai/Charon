#!/usr/bin/env python3
"""
Stop hook: enforce the "new memory file -> MEMORY.md index entry" co-change.

WHY IT EXISTS: the co-change rule (a memory file created without an index line
becomes an orphan that drops out of recall) has only ever been a *behavioural*
discipline — it relied on the agent remembering. This is the STRUCTURAL guard
that closes that gap: at end of turn it checks every memory file the session
actually authored and, if any is on disk but not indexed in MEMORY.md (nor a
reachable sub-index) and not deprecated, it surfaces (shadow) or blocks the
stop (enforce) until the index line is added. It is the structural-prevention
half of the vault-hygiene self-improving cycle (proposal vh-2026-07-20-33dab9).

SINGLE SOURCE OF TRUTH: "is this file indexed?" is answered by
`score-vault.py::indexed_memory_names()` — imported here — so this real-time
enforcer and the periodic `/score-vault` detector can never drift.

SIGNAL: 100% deterministic (filesystem membership) — the clean-signal property
that made vault-hygiene the first self-improving loop.

FAIL-OPEN BY DESIGN: this is a hygiene/productivity control, NOT a security
boundary. Any internal error (bad transcript, missing sibling module, etc.)
exits 0 so a hook bug can never trap the user inside a turn. Contrast
validate-write-path.py, a security control that fails CLOSED.

MODE:
  SHADOW = True  -> observe: surface the reminder to stderr, exit 0 (turn ends).
  SHADOW = False -> enforce: exit 2, feed the reminder back to the model so it
                    must add the index line before the turn can end.

Loop guard: honours `stop_hook_active` — if we already blocked once this turn,
we never block again (prevents an infinite stop loop).

Input (stdin JSON, Stop event): {session_id, transcript_path, stop_hook_active, ...}
Exit codes: 0 = allow stop; 2 = block stop (enforce mode, positive detection only).
"""
import json
import sys
from pathlib import Path

try:
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

# --- Mode ------------------------------------------------------------------
# Shipped in SHADOW 2026-07-21 to prove zero false positives against real
# authoring before it could block a turn (shadow-before-enforce).
#
# FLIPPED TO ENFORCE 2026-08-03 after the FP review. Evidence:
#   - 3 total fires in state/verdict/*.jsonl, ALL on `zzz_cochange_probe.md`
#     (the build-time behaviour probes of 2026-07-21). ZERO production fires,
#     therefore ZERO false positives across 13 days of real authoring.
#   - Zero fires could equally mean "hook silently dead" (cf. the 2/5-dead
#     detectors in bugs_harness_watch_silent_rules), so fire-capability was
#     proven directly rather than inferred. Live controls, 2026-08-03:
#       positive (unindexed file authored) -> fires, exit 0, "[shadow]" prefix
#       negative (indexed file authored)   -> silent, exit 0
#       enforce (SHADOW=False)             -> exit 2, unprefixed block message
#       loop guard (stop_hook_active=True) -> exit 0, no block
#   - Still FAIL-OPEN on any internal error, so enforcing cannot trap a turn.
# Revert = set this back to True (one line).
SHADOW = False

HOOK_NAME = "enforce-memory-index-cochange"
HERE = Path(__file__).resolve().parent
SCRIPTS_DIR = HERE.parent
AUTHORING_TOOLS = {"Write", "Edit", "MultiEdit"}

# --- Verdict audit (fail-silent per verdict-vocabulary convention #5) -------
try:
    if str(HERE) not in sys.path:
        sys.path.insert(0, str(HERE))
    from _verdict import emit_verdict  # noqa: E402
except Exception:
    def emit_verdict(*args, **kwargs):  # type: ignore
        return kwargs.get("verdict", "allow")


def _load_score_vault():
    """Import score-vault.py by path (hyphen -> not import-able normally) so we
    reuse its exact indexed-set + deprecation logic. Returns the module or None
    (None => fail open, we can't judge)."""
    import importlib.util

    sv_path = SCRIPTS_DIR / "score-vault.py"
    if not sv_path.exists():
        return None
    # score-vault inserts SCRIPTS_DIR on sys.path itself (for `lib.harness_paths`).
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    # exec_module can raise (mid-edit SyntaxError in score-vault, transient
    # ImportError of lib.harness_paths, etc.). Honour the fail-open contract:
    # any failure to load the single-source module -> None -> hook exits 0.
    try:
        spec = importlib.util.spec_from_file_location("score_vault", sv_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    except Exception:
        return None


def _memory_files_authored(transcript_path):
    """Basenames of memory files (direct children of a `.../memory/` dir, *.md,
    not MEMORY.md, not under sessions/) that this session wrote or edited.
    Parses the Stop-event transcript (JSONL). Best-effort: unparseable lines
    are skipped, not fatal."""
    names = set()
    tp = Path(transcript_path)
    if not tp.exists():
        return names
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
                fp = (block.get("input") or {}).get("file_path") or ""
                if not fp:
                    continue
                norm = fp.replace("/", "\\")
                low = norm.lower()
                if not low.endswith(".md"):
                    continue
                base = norm.rsplit("\\", 1)[-1]
                parent = low.rsplit("\\", 1)[0] if "\\" in low else ""
                # Direct child of a "memory" dir; exclude the index + session logs.
                if not parent.endswith("\\memory"):
                    continue
                if base.lower() == "memory.md" or "\\sessions\\" in low:
                    continue
                names.add(base)
    return names


def _index_hint(memory_dir, name):
    """A one-line 'add this to MEMORY.md' hint pulled from the file's own
    frontmatter (name/description). Deterministic; no LLM."""
    try:
        # Cap the read: frontmatter never exceeds a few KB, and a Stop hook has
        # no timeout — never load a pathologically large authored file in full.
        with (memory_dir / name).open(encoding="utf-8", errors="replace") as fh:
            text = fh.read(4096)
    except Exception:
        return f"  - [{name}]({name}) — <one-line hook>"
    title, desc = name, ""
    for raw in text.splitlines()[:15]:
        s = raw.strip()
        if s.startswith("name:"):
            title = s.split("name:", 1)[1].strip().strip('"') or name
        elif s.startswith("description:"):
            desc = s.split("description:", 1)[1].strip().strip('"')
    hook = (desc[:80] + "…") if len(desc) > 80 else desc
    return f"  - [{title}]({name})" + (f" — {hook}" if hook else " — <one-line hook>")


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0  # no parseable input — nothing to judge, fail open

    # Loop guard: if we already blocked this turn, never block again.
    if data.get("stop_hook_active"):
        return 0

    transcript_path = data.get("transcript_path") or ""
    if not transcript_path:
        return 0

    sv = _load_score_vault()
    if sv is None:
        return 0  # can't reuse the single-source logic -> fail open

    try:
        memory_dir = sv.MEMORY_DIR
        authored = _memory_files_authored(transcript_path)
        if not authored:
            return 0
        # REACHABILITY, not linkage (changed 2026-09-29).
        #
        # This hook used to demand a MEMORY.md line for every new memory file.
        # That definition is why the index grew without bound — each file
        # mandated another line on the one always-loaded surface, until its tail
        # was silently truncated at the read limit.
        #
        # Measured the same day over 422 files: the linkage definition produced
        # 5 false orphans (files it called unindexed that BM25 finds at rank 1)
        # and caught 0 real ones — it missed the single genuinely unfindable
        # file, `feedback_qsr_baseline_is_last_review.md`, which had an empty
        # description and was invisible to retrieval while being dutifully
        # linked. Being linked is not being findable.
        #
        # So the question became "if I needed this, would I find it?" — which is
        # measurable and needs no index. A file that cannot retrieve itself by
        # its own description is the real orphan, and the fix is to write a
        # better description, not to add a pointer.
        from memory_reachability_check import unreachable_names  # noqa: E402
        missing = unreachable_names(
            memory_dir,
            [n for n in sorted(authored) if (memory_dir / n).exists()],
            is_deprecated=sv._is_deprecated,
        )
    except Exception:
        return 0  # any judgement error -> fail open (hygiene control, not security)

    if not missing:
        return 0

    effective = emit_verdict(
        hook=HOOK_NAME,
        rule="memory-file-not-retrievable",
        verdict="ask",
        reason=(
            f"{len(missing)} memory file(s) authored this session cannot retrieve "
            f"themselves by their own description — they will not be found when "
            f"the question is asked for real"
        ),
        context={
            "missing": missing,
            "mode": "shadow" if SHADOW else "enforce",
        },
        session_id=data.get("session_id", ""),
    )

    lines = [
        "MEMORY NOT RETRIEVABLE — you authored memory file(s) this turn that cannot "
        "retrieve themselves by their own description. They exist, but they will not "
        "come back when the question is asked:",
        "",
    ]
    for name in missing:
        lines.append(f"  - {name}")
    lines += [
        "",
        "Fix the FILE, not an index. For each one:",
        "  1. Give it a real `description:` — the question it exists to answer, "
        "written in the words a future question will carry, not the words that "
        "describe the fact.",
        "  2. Make sure the body repeats those words at least once.",
        "  3. Re-check: python scripts/memory_reachability.py",
        "",
        "Adding a MEMORY.md pointer will NOT fix this and is no longer what this "
        "hook asks for — measured 2026-09-29, linkage produced 5 false orphans and "
        "missed the one genuinely unfindable file. Mark `status: deprecated` if the "
        "file should not be retrievable at all.",
    ]
    message = "\n".join(lines) + "\n"

    if SHADOW or effective == "observe":
        # Observe: surface but do not block. Turn ends.
        sys.stderr.write("[shadow] " + message)
        return 0

    # Enforce: block the stop so the model adds the index line, then stops again
    # (with stop_hook_active=True -> allowed by the loop guard above).
    sys.stderr.write(message)
    return 2


if __name__ == "__main__":
    sys.exit(main())
