#!/usr/bin/env python3
"""detect-recall-miss.py — instrument the FORGETTING, not the retrieval.

UserPromptSubmit hook. Detects the phrases the user uses when the harness has
forgotten something, and records the retrieval context that FAILED — so
forgetfulness becomes a measured dataset instead of a feeling.

WHY THIS EXISTS
---------------
`session-start-ritual.md` already names these as "skipped-ritual signals":
*"why have you forgotten X"*, *"didn't we have Y"*, *"we discussed this
before"*. Nothing counted them. So on 2026-09-08 we had:

  - `memory-retrieve.py` injecting on ~4 of 5 prompts
  - a memory corpus in the hundreds of files
  - and NO ground truth for whether any of it reduces forgetting

Optimising a system whose core failure mode is unobserved is guesswork. This
closes that loop. Companion to `scripts/eval/` (item 2 of the same fix): this
measures misses in the wild, the goldset measures retrieval in the lab.

THE CORRELATION THAT MAKES THE DATA USEFUL
------------------------------------------
A "you forgot X" prompt is about the PREVIOUS turn. The retrieval that failed
is the one that ran for prompt N-1, not for this prompt. So we capture the
*preceding* records from `state/memory-retrieval/`, skipping any record whose
prompt_preview matches this prompt. That pairing — the complaint plus the
context that was actually in play when the forgetting happened — is the whole
point of the log.

NOT SHADOWED, DELIBERATELY
--------------------------
This hook is observation plus a one-line nudge. It is not a gate: it cannot
block, cannot deny, and injects at most ~200 bytes. Shipping it "in shadow
pending review" is exactly how `memory-retrieve.py` sat inert for four weeks
while the problem it solved got worse. An observation hook with no blast
radius does not need a shadow window.

Output: <vault>/state/recall-miss/{YYYY-MM-DD}.jsonl (append-only, daily
rotation, matching the _telemetry.py / memory-retrieve.py convention).

Fail-silent, always exit 0. A detector that breaks a turn is worse than no
detector. Note the shape of a real failure this guards against: a hook whose
output path raised UnicodeEncodeError on a non-UTF-8 console, inside its own
broad `except`, stayed silent for three weeks. So stdout writes here sit OUTSIDE
the try that swallows, and the nudge text is ASCII-only.
"""
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# ---------------------------------------------------------------- patterns
# Tight on purpose. A false positive costs a spurious log line and a nudge;
# a pattern so loose it fires on ordinary questions would make the dataset
# useless. "did we" alone is too broad — "didn't we" is the complaint form.
MISS_PATTERNS = [
    (r"\b(?:why (?:have|did) you )?forgot(?:ten)?\b", "forgot"),
    (r"\bdon'?t you remember\b", "dont-you-remember"),
    (r"\bdidn'?t we\b|\bdid we not\b|\bhaven'?t we\b", "didnt-we"),
    (r"\bwe (?:already )?(?:discussed|talked about|agreed|went through) (?:this|that|it)\b",
     "we-discussed-this"),
    (r"\b(?:i|we)'?ve (?:already )?(?:told|said|mentioned) (?:you|this|that)\b", "already-told-you"),
    (r"\bi (?:already )?told you\b", "already-told-you"),
    (r"\b(?:as|like) i said (?:before|earlier|already)\b", "as-i-said-before"),
    (r"\byou (?:should|would) know this\b", "should-know"),
    (r"\b(?:it'?s|that'?s) in (?:your )?(?:memory|the memory|claude\.?md|memory\.?md)\b",
     "its-in-memory"),
    (r"\bcheck (?:your )?memory\b", "check-memory"),
    (r"\bwe'?ve been (?:through|over) this\b", "been-through-this"),
    (r"\b(?:this|that) was (?:in|on) (?:the )?(?:vault|memory|todo)\b", "was-in-vault"),
]

MAX_PRIOR_RETRIEVALS = 3
MAX_PROMPT_CHARS = 400


def _vault_root() -> Path:
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env)
    here = Path(__file__).resolve().parent
    for cand in [here, *here.parents]:
        if (cand / ".claude").is_dir():
            return cand
    return here


def _match(prompt: str):
    low = prompt.lower()
    hits = []
    for pat, label in MISS_PATTERNS:
        if re.search(pat, low):
            hits.append(label)
    return hits


def _prior_retrievals(root: Path, session_id: str, this_prompt: str):
    """The retrieval records that were in play BEFORE this complaint.

    Newest-first, this prompt's own record excluded. Only the fields that say
    whether retrieval had a fair shot — slugs, scores, budget pressure.
    """
    out = []
    d = root / "state" / "memory-retrieval"
    if not d.is_dir():
        return out
    head = (this_prompt or "")[:60].strip().lower()
    for f in sorted(d.glob("*.jsonl"), reverse=True)[:3]:
        try:
            lines = f.read_text(encoding="utf-8", errors="replace").splitlines()
        except Exception:
            continue
        for line in reversed(lines):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                continue
            if session_id and r.get("session_id") != session_id:
                continue
            prev = (r.get("prompt_preview") or "").strip().lower()
            if head and prev[:60] == head:
                continue  # this is the complaint's own retrieval, not the failure
            out.append({
                "ts": r.get("ts"),
                "mode": r.get("mode"),
                "prompt_preview": (r.get("prompt_preview") or "")[:120],
                "matched": [m.get("slug") for m in (r.get("matched") or [])][:8],
                "top_score": r.get("top_score"),
                "cutoff_score": r.get("cutoff_score"),
                "would_inject_bytes": r.get("would_inject_bytes"),
                "dropped_for_space": r.get("dropped_for_space"),
                "cut_by_relevance": r.get("cut_by_relevance"),
                "near_misses": (r.get("near_misses") or [])[:5],
            })
            if len(out) >= MAX_PRIOR_RETRIEVALS:
                return out
    return out


def _index_state(root: Path):
    """MEMORY.md size vs the 24.4KB read limit that silently truncates it."""
    # Env-var-first via the shared helper — never a hardcoded per-machine path.
    candidates = []
    mem_dir = os.environ.get("CLAUDE_MEMORY_DIR") or os.environ.get("HARNESS_MEMORY_ROOT")
    if mem_dir:
        candidates.append(Path(mem_dir) / "MEMORY.md")
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
        from harness_paths import memory_root  # noqa: E402
        candidates.append(memory_root() / "MEMORY.md")
    except Exception:
        pass
    for p in candidates:
        try:
            if p.is_file():
                size = p.stat().st_size
                n = len(list(p.parent.glob("*.md")))
                return {"memory_md_bytes": size, "over_read_limit": size > 24400,
                        "memory_files": n}
        except Exception:
            pass
    return {"memory_md_bytes": None, "over_read_limit": None, "memory_files": None}


def main() -> int:
    try:
        raw = sys.stdin.read()
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:
        return 0

    prompt = payload.get("prompt") or payload.get("user_prompt") or ""
    if not isinstance(prompt, str) or not prompt.strip():
        return 0

    labels = _match(prompt)
    if not labels:
        return 0

    root = _vault_root()
    session_id = payload.get("session_id") or ""

    record = {
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "session_id": session_id,
        "signals": labels,
        "prompt": prompt[:MAX_PROMPT_CHARS],
        "prompt_chars": len(prompt),
        "prior_retrievals": _prior_retrievals(root, session_id, prompt),
        "index": _index_state(root),
    }

    # Write the record. Failure here must not cost the nudge, so the nudge is
    # emitted outside this try.
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from _jsonl_append import safe_append_line  # noqa: E402
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        out = root / "state" / "recall-miss" / f"{day}.jsonl"
        safe_append_line(out, json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        try:
            day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            out = root / "state" / "recall-miss" / f"{day}.jsonl"
            out.parent.mkdir(parents=True, exist_ok=True)
            with out.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except Exception:
            pass

    # One-line nudge. stdout on UserPromptSubmit is injected as context, so keep
    # it short and actionable — the behaviour it asks for is already mandated by
    # session-start-ritual.md; this just makes sure the signal is not glossed.
    n = len(record["prior_retrievals"])
    try:
        sys.stdout.write(
            # ASCII ONLY on this path. A non-ASCII character here raises
            # UnicodeEncodeError on cp1252 stdout, and the except below would
            # swallow it -- the exact failure that left the commitments hook
            # silent for three weeks (bugs_commitments_hook_silent_on_cp1252).
            # Caught during this hook's own first test, which printed a mojibake
            # em-dash. Do not reintroduce smart punctuation.
            "RECALL-MISS DETECTED (%s). the user is signalling the harness forgot something. "
            "Per session-start-ritual.md: apologise briefly, LOAD the relevant memory "
            "content now (search_memory / recall / vault-graph -- do not answer from the "
            "index alone), then continue. Logged with %d prior retrieval record(s) to "
            "state/recall-miss/.\n" % (",".join(labels), n)
        )
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
