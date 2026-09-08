"""memory-retrieve.py — prompt-conditioned retrieval (memory-graph phase 5B).

UserPromptSubmit hook. Resolves entities named in the user's prompt against BOTH the
memory layer and the authored vault notes, expands one hop through the knowledge
graph, and surfaces the matching descriptions.

Vault coverage was added 2026-08-10. Memory-only retrieval missed the document a
question is usually actually about: "the memory-graph scope doc" returned nothing
because that content is a vault note, not a memory file.

LIVE since 2026-09-08 (`SHADOW = False`, see the switch block below for why).
This docstring said "CURRENTLY IN SHADOW" for the whole of that day while the
code said otherwise — corrected 2026-09-08. A comment that misdescribes the
state of the thing deciding what gets remembered is the worst place for exactly
that defect, so: if you flip the switch, fix this paragraph in the same edit.

MEASURED (28-question goldset, `scripts/eval/eval_live_retrieval.py`):
  recall@injected  0.643 -> 0.929   after body tokens were added to the index
  recall@10        0.536 -> 0.607
  MRR              0.393 -> 0.425
The gap between recall@10 and recall@injected is real and load-bearing: coverage
is preserved even when ranking is mediocre, so the right note usually REACHES
context without being ranked first. Ranking is the next thing to improve; see
BODY FALLBACK in score_entry() and the residual misses in the eval output.

WHY
---
`MEMORY.md` is the only always-loaded surface over 330+ memory files. Measured
2026-08-10: 19 of 64 bullets were pure navigation — 151 pointers, 9,282 bytes,
holding 277 bytes of prose. They exist because without retrieval, a memory that
is not listed cannot be found. This is the retrieval that makes them unnecessary.

Modelled on load-rules.py, which already does prompt-conditioned injection for
path rules — same shape, different corpus.

TRUST — the load-bearing property, since this feeds every prompt:
Only authored content is indexed. Captured/untrusted material is excluded by the
index builder on TWO independent filters, path AND frontmatter provenance.
Path alone is not sufficient and CLAUDE.md's "authored content elsewhere in the
vault is trusted" does not hold as a rule: measured 2026-08-10, 320 capture-
sourced notes (`source: m365-calendar`, `plaud`) sit inside 05-Meetings,
03-Domains and 08-Projects. A path-only filter would have fed all of them into
every prompt. See build_memory_retrieval_index.py::CAPTURE_PROVENANCE, which
fails CLOSED — an unreadable file is excluded, not included.

LOGGING: the shadow log stores a short prompt preview so a miss can be judged,
not just a hit. the user's prompts are already persisted verbatim in
~/.claude/history.jsonl, so this adds no new exposure class. No memory BODY text
is logged — descriptions only.
"""
from __future__ import annotations

import io
import json
import math
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# --- shadow switch: one line to promote -------------------------------------
# PROMOTED 2026-09-08 (C022). Two defects fixed first, both verified on the real
# 381-prompt shadow corpus:
#   1. dropped_for_space went 12 -> 0 (names tier given its own ceiling).
#   2. the log now records what was NOT shown, so hit/miss is answerable at all.
#
# Promoted despite the code having just changed — the discipline that says a
# behavioural change resets the shadow window applies to gates that can BLOCK.
# This hook has no deny path: it can only add context. The cost of leaving it off
# was the larger risk, because only 198 of 406 memory files are indexed in
# MEMORY.md and retrieval is the sole access path to the other 208.
#
# Revert is this one line. Watch `detail_tier` and `would_inject_bytes` in the
# live log: a corpus-wide drift toward the `names` tier means RELATIVE_FLOOR is
# too generous and relevance, not budget, is the next thing to tune.
SHADOW = False

# --- how much is surfaced ---------------------------------------------------
# There is deliberately NO cap on the NUMBER of matches. A fixed top-K drops
# correct results for an arbitrary reason: on 2026-08-10 `feedback_content_voice`
# lost its slot to higher-scoring siblings on a content prompt. That is a
# capability reduction dressed as a limit — [[feedback_no_capability_reduction]].
#
# What IS bounded is BYTES, because context is a real resource. When the budget
# binds, detail degrades before coverage does: full descriptions -> short
# descriptions -> bare names. A pointer costs ~40 bytes and is what makes a note
# findable at all, so coverage is the last thing to go — the same lesson as the
# MEMORY.md compaction, where 19 pointer rows held 151 pointers in 277B of prose.
MAX_INJECT_BYTES = 4000
DESC_FULL = 200           # per-entry description budget when matches are few
DESC_SHORT = 90           # degraded tier before dropping to bare names
MAX_NEIGHBOURS_SHOWN = 5  # 1-hop expansion off the top match

# The names tier gets its OWN, higher ceiling (C022 fix, 2026-09-08).
#
# THE DEFECT: all three tiers shared MAX_INJECT_BYTES. A bare pointer costs ~40
# bytes, so 4000 bytes capped the names tier at ~100 pointers — and on 12 of 345
# shadow prompts the match set was larger than that, so the code fell through to
# its last resort and DROPPED entries. Worst case dropped 71. The module's own
# comment says coverage is the last thing to go and `dropped_for_space` "must stay
# 0"; it was non-zero on 3.5% of prompts. That is the exact shape of
# [[feedback_no_capability_reduction]] — a cap that discards correct results.
#
# THE FIX: bound each tier by what it actually costs. MAX_INJECT_BYTES bounds
# PROSE, which is the expensive part; a pointer list is not prose.
#
# SIZED AGAINST REAL TRAFFIC, not a guess. Replaying all 381 non-envelope shadow
# prompts: match sets run median 8, p90 36, p99 58, max 75. At ~71 bytes per
# rendered pointer (vault notes carry a path, not just a slug), 12000 bytes holds
# ~169 — a 2.3x margin over the largest set ever actually seen. Result: 0 drops
# across all 381, against 12 drops in the same data before the fix.
#
# The drop path REMAINS as a backstop and is correct to remain: a synthetic
# prompt built from the 120 commonest corpus tokens still matches 237 and still
# trims. That is a shape no one types, and a backstop that never fires on real
# input while staying transparent when it does is the right trade — raising the
# ceiling further would spend context on every prompt to serve a case that does
# not occur. When it fires it says so in-line AND records it in the log.
NAMES_MAX_BYTES = 12000

# Retrieval runs on UserPromptSubmit, but not everything arriving there is a
# person typing. A task-notification or tool-return envelope is thousands of
# words of machine text that matches half the corpus on incidental vocabulary —
# it produced the largest match sets in the shadow window (one 3,667-word
# "prompt" matched at score 110) and none of it was a question anyone asked.
# Same provenance insight as poisoning-scan.py: judge the input by where it came
# from, not by what it contains.
ENVELOPE_MARKERS = (
    "<task-notification>", "<tool-use-id>", "<output-file>",
    "<function_results>", "<system-reminder>", "tool_result",
)
ENVELOPE_WORD_CAP = 600   # a genuine prompt is not this long

BODY_MIN_HITS = 2         # body fallback needs >=2 shared words, not one
BODY_WEIGHT = 0.6         # a filename match must outrank a body mention
SCORE_FLOOR = 16          # absolute noise floor. Tuned against the eval set
                          # 2026-08-10; the shadow window is the real calibration.
# Relative relevance: a match far weaker than the best one is noise for THIS
# prompt. This is a relevance rule, not a headcount — it scales with how good
# the top match is instead of truncating at a magic number.
RELATIVE_FLOOR = 0.35

VAULT = Path(__file__).resolve().parent.parent.parent
INDEX_PATH = VAULT / ".charon" / "memory-retrieval-index.json"
LOG_DIR = VAULT / "state" / "memory-retrieval"

WORD = re.compile(r"[a-z0-9]+")


def load_index():
    try:
        return json.loads(io.open(INDEX_PATH, encoding="utf-8").read())
    except Exception:
        return None


def token_weight(tok, df, corpus):
    """How much a shared word says about relevance — driven by RARITY.

    A word in one file identifies it; a word in a fifth of the corpus identifies
    nothing. Token length is not a usable proxy: a 4-char project code (1 file) is
    decisive, `harness` (7 chars, dozens of files) is almost noise.

    Standard IDF rather than hand-set thresholds, because thresholds do not
    survive a corpus change. Fixed buckets tuned on 331 memory files broke the
    moment 559 vault notes joined: a common domain word went 10 -> 35 files, crossed a
    bucket edge, and "restart the build server" stopped matching. IDF is relative
    to corpus size, so it re-scales itself as the vault grows.
    """
    n = max(1, df.get(tok, 1))
    if corpus <= 1:
        return 30
    ratio = math.log(corpus / float(n)) / math.log(corpus)
    return max(2, int(round(30 * ratio)))


def score_entry(slug, entry, prompt_words, prompt_norm, df, corpus, dfb=None):
    """0 = no match. Higher = more confident this memory is on-topic."""
    toks = entry.get("k") or []
    if not toks:
        return 0
    # Whole slug named outright ("project_charon" / "project charon").
    if slug.replace("_", " ") in prompt_norm:
        return 100
    present = [t for t in toks if t in prompt_words]
    if not present:
        # BODY FALLBACK (2026-09-08). `k` is SLUG tokens only, so without this
        # the hook matches on FILENAMES. Measured on a 28-question goldset:
        # this scorer got recall@10 0.54 where BM25-over-bodies got 0.92, and
        # every miss was a situational prompt. "does the build server server
        # have antivirus or EDR" cannot reach
        # bugs_buildserver_host_no_endpoint_protection ({buildserver, host,
        # endpoint, protection}) -- zero overlap.
        #
        # Deliberately a FALLBACK, not a fusion: it runs only when no slug
        # token matched, so every previously-correct result is bit-identical.
        # Two guards keep it from becoming a noise source:
        #   BODY_MIN_HITS  - one shared common word is not evidence
        #   BODY_WEIGHT    - a filename match outranks a body mention
        btoks = entry.get("b") or []
        if not btoks:
            return 0
        bpresent = [t for t in btoks if t in prompt_words]
        if len(bpresent) < BODY_MIN_HITS:
            return 0
        bscore = sum(token_weight(t, dfb if dfb else df, corpus)
                     for t in bpresent) * BODY_WEIGHT
        return int(bscore)
    score = sum(token_weight(t, df, corpus) for t in present)
    coverage = len(present) / float(len(toks))
    # Coverage is ADDITIVE, never a multiplier. As a multiplier it dragged
    # decisive rare tokens under the floor — a rare project code (df=1, score 30) fell to
    # 22 purely because its slug carries two other words. Rarity sets the floor;
    # coverage only breaks ties, so "build server deploy" outranks
    # "build server log and 404" on a deploy question.
    score += 20 if len(present) == len(toks) else int(8 * coverage)
    return int(score)


def select(index, prompt):
    entries = index.get("entries") or {}
    df = index.get("df") or {}
    dfb = index.get("dfb") or {}
    prompt_l = prompt.lower()
    prompt_words = set(WORD.findall(prompt_l))

    # COMPOUND TOKENS (2026-09-08). Slugs compress multi-word names
    # inconsistently: `bugs_buildserver_host_no_endpoint_protection` has
    # `buildserver` while `project_build_server_deploy` has `build` + `server`.
    # A prompt saying "build server" matched the second and missed the first, so
    # "does the build server host have EDR" could not reach the note that answers
    # it. Join adjacent prompt words so both spellings are reachable. Ordered
    # pairs only — cheap, and a prompt is short.
    seq = WORD.findall(prompt_l)
    prompt_words |= {seq[i] + seq[i + 1] for i in range(len(seq) - 1)}
    prompt_norm = re.sub(r"[_\-]+", " ", prompt_l)

    scored = []
    for slug, entry in entries.items():
        s = score_entry(slug, entry, prompt_words, prompt_norm, df,
                        len(entries), dfb)
        if s >= SCORE_FLOOR:
            scored.append((s, slug, entry))
    scored.sort(key=lambda x: (-x[0], x[1]))
    # Relevance cutoff relative to the best match — never a fixed headcount.
    if scored:
        cutoff = scored[0][0] * RELATIVE_FLOOR
        top = [row for row in scored if row[0] >= cutoff]
    else:
        cutoff = 0
        top = []

    # MISS RECORD (C022 fix, 2026-09-08). The log previously recorded only what
    # was SHOWN, which made the commitment's question — "judge hit AND miss rate"
    # — unanswerable from its own data: a log of hits cannot tell you what was
    # withheld. True misses (a memory that should have matched and scored zero)
    # remain unmeasurable without ground truth, and that limit is real. But the
    # NEAR misses are measurable exactly: entries that cleared the absolute noise
    # floor and were then cut by the relative-relevance rule. If a review ever
    # finds the answer sitting in `near_misses`, RELATIVE_FLOOR is too aggressive
    # — and that is a calibration signal the hook could not previously produce.
    cut = [row for row in scored if row[0] < cutoff]
    stats = {
        "candidates": len(scored),          # cleared SCORE_FLOOR
        "shown": len(top),
        "cut_by_relevance": len(cut),
        "cutoff_score": int(cutoff),
        "top_score": scored[0][0] if scored else 0,
        # The strongest few that were withheld — enough to judge the cutoff,
        # bounded so the log line cannot grow without limit.
        "near_misses": [{"slug": s, "score": sc} for sc, s, _ in cut[:5]],
    }

    chosen = {s for _, s, _ in top}
    neighbours = []
    for _, _, entry in top[:2]:
        for n in entry.get("n") or []:
            if n in entries and n not in chosen and n not in neighbours:
                neighbours.append(n)
    neighbours = neighbours[:MAX_NEIGHBOURS_SHOWN]
    return top, neighbours, stats


def _clip(text, budget):
    raw = (text or "").strip().encode("utf-8")
    if len(raw) <= budget:
        return raw.decode("utf-8", "ignore")
    return raw[:budget].decode("utf-8", "ignore").rstrip() + "…"


def _compose(top, neighbours, desc_budget):
    """Render every match at the given per-description budget. desc_budget=0
    yields bare names — coverage with no detail."""
    mem = [(k, e) for _, k, e in top if e.get("kind") != "vault"]
    vault = [(k, e) for _, k, e in top if e.get("kind") == "vault"]
    lines = ["# Relevant context (retrieved by prompt match)", ""]
    for label, group in (("**Memory:**", mem), ("**Vault notes:**", vault)):
        if not group:
            continue
        if lines[-1] != "":
            lines.append("")
        lines.append(label)
        for key, entry in group:
            if desc_budget <= 0:
                lines.append("- `%s`" % key)
            else:
                lines.append("- `%s` — %s" % (key, _clip(entry.get("d"), desc_budget)))
    if neighbours:
        lines.append("")
        lines.append("Related via the graph: " + ", ".join(neighbours))
    return "\n".join(lines)


def render(top, neighbours, entries):
    """Fit within the byte budget by degrading DETAIL, never coverage.

    Tries full descriptions, then short, then bare names. Every match that
    cleared the relevance cutoff is named in all three tiers, because the
    pointer is what makes a note findable — dropping entries to save bytes
    would be a capability reduction. Returns (text, tier, dropped).
    """
    for tier, budget, ceiling in (("full", DESC_FULL, MAX_INJECT_BYTES),
                                  ("short", DESC_SHORT, MAX_INJECT_BYTES),
                                  ("names", 0, NAMES_MAX_BYTES)):
        text = _compose(top, neighbours, budget)
        if len(text.encode("utf-8")) <= ceiling:
            return text, tier, 0
    # Even bare names overflow — only possible with a very large match set.
    # Drop from the WEAKEST end and say so; never truncate mid-structure.
    kept = list(top)
    while kept:
        kept.pop()
        dropped = len(top) - len(kept)
        note = ("\n\n(%d further lower-scoring matches omitted for space — "
                "ask and I'll list them)" % dropped)
        text = _compose(kept, neighbours, 0)
        # Reserve room for the note itself, or the budget is breached by the
        # very line that reports the breach.
        if len((text + note).encode("utf-8")) <= NAMES_MAX_BYTES:
            return text + note, "names", dropped
    return "", "empty", len(top)


def log(record):
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        with io.open(LOG_DIR / ("%s.jsonl" % day), "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception:
        pass


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return 0

    # Not everything arriving on UserPromptSubmit is a person asking something.
    # A task-notification or tool-return envelope is machine text that matches
    # half the corpus on incidental vocabulary: it produced the largest match
    # sets in the shadow window — the single worst was a 3,667-word "prompt"
    # matching at score 110 — and every one of those matches was noise against a
    # question nobody asked. Skipping them removes the pathological match sets
    # (the ones that overflowed the names tier) AND stops them skewing the
    # hit-rate the shadow window exists to measure.
    low = prompt.lower()
    if any(m in low for m in ENVELOPE_MARKERS) or \
            len(WORD.findall(low)) > ENVELOPE_WORD_CAP:
        return 0

    # Skip unattended runs entirely. Two reasons, both found on the first
    # scheduled run 2026-08-11:
    #   1. The shadow log write landed outside morning-update's write-path
    #      allowlist and raised a post-run audit anomaly. Left alone it would
    #      recur every morning — exactly the false-positive erosion that gets a
    #      control switched off.
    #   2. Unattended prompts are a fixed template, not the user's questions.
    #      Logging them would skew the hit-rate the shadow window exists to
    #      measure. Retrieval is for a human asking something.
    # Same signal _policy.py uses to pick its profile.
    if os.environ.get("SECONDBRAIN_UNATTENDED_ALLOWLIST"):
        return 0

    index = load_index()
    if not index:
        log({"ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
             "error": "index-missing", "mode": "shadow" if SHADOW else "live"})
        return 0

    top, neighbours, stats = select(index, prompt)
    if top:
        body, tier, dropped = render(top, neighbours, index.get("entries") or {})
    else:
        body, tier, dropped = "", "none", 0

    log({
        "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": "shadow" if SHADOW else "live",
        "session_id": data.get("session_id", ""),
        "prompt_preview": prompt[:160],
        "prompt_words": len(WORD.findall(prompt.lower())),
        "matched": [{"slug": s, "score": sc} for sc, s, _ in top],
        "neighbours": neighbours,
        "would_inject_bytes": len(body.encode("utf-8")),
        "detail_tier": tier,          # full / short / names — how far detail degraded
        "dropped_for_space": dropped, # must stay 0; anything else is coverage loss
        # --- miss record (C022) — what was NOT shown, so the shadow review can
        # judge the cutoff instead of only admiring the hits.
        "candidates": stats["candidates"],
        "cut_by_relevance": stats["cut_by_relevance"],
        "cutoff_score": stats["cutoff_score"],
        "top_score": stats["top_score"],
        "near_misses": stats["near_misses"],
        "index_generated": index.get("generated", ""),
    })

    if SHADOW or not body:
        return 0
    sys.stdout.write(body + "\n")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Retrieval must never break a prompt. Fail silent, fail open.
        sys.exit(0)
