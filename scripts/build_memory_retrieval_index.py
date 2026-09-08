"""build_memory_retrieval_index.py — compact prompt-matching index over the
memory layer (memory-graph phase 5A).

WHY THIS EXISTS
---------------
`MEMORY.md` is the only always-loaded surface over 330+ memory files, so every
"must not forget this" competes to live there and the index fattens. Measured
2026-08-10: 19 of 64 bullets were pure navigation — 151 pointers, 9,282 bytes,
carrying 277 bytes of actual prose. They exist because without retrieval, a
memory that is not listed cannot be found.

The knowledge graph already holds the relationships (4,350 nodes / 7,378 edges),
but nothing puts it in the prompt path, and `knowledge-graph.json` is 2.5 MB —
far too heavy to load on every UserPromptSubmit. This emits a small derived
index (descriptions + 1-hop neighbours + match tokens) that a hook can load in
milliseconds.

Token derivation lives HERE, not in the hook: the hook stays dumb and fast, and
there is one source of truth for how a slug becomes matchable words.

Output: <vault>/state/memory-retrieval-index.json
Run:    python scripts/build_memory_retrieval_index.py [--stats]
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

# Paths are env-var-first via the shared helper — never hardcoded. Set
# HARNESS_MEMORY_ROOT if your Claude Code project memory dir is non-standard.
sys.path.insert(0, str(Path(__file__).resolve().parent / "lib"))
from harness_paths import memory_root, vault_root  # noqa: E402

MEMORY_DIR = memory_root()
GRAPH_PATH = vault_root() / ".charon" / "knowledge-graph.json"

# --- authored vault notes (added 2026-08-10) --------------------------------
# The memory layer is 331 files; the authored vault is the other half of the
# brain. Retrieval that cannot reach 08-Projects / 06-Decisions / 07-References
# misses the doc a question is usually actually about.
VAULT_ZONES = ("01-Daily", "02-BUs", "03-Domains", "04-People", "05-Meetings",
               "06-Decisions", "07-References", "08-Projects")

# Directory-level exclusions. 00-Inbox is absent DELIBERATELY — all of it,
# not just _captured: 00-Inbox/_uncertain holds `source: m365-calendar` items.
EXCLUDED_DIRS = ("09-Archive", "_Templates", "templates", "_templates",
                 ".obsidian", ".archive", "captured", "_captured",
                 "voice-examples", "published")

# PROVENANCE exclusion — the load-bearing one.
#
# CLAUDE.md says captured content lives under 00-Inbox/_captured and that
# "authored content elsewhere in the vault is trusted". Measured 2026-08-10 that
# is NOT true as a path rule: 166 m365-calendar files sit in 05-Meetings, 98 in
# 03-Domains, 26 in 08-Projects — 320 capture-sourced notes inside the
# "authored" zones. A path-only filter would feed every one of them into every
# prompt, which is a prompt-injection surface, so provenance is read from the
# frontmatter of each file rather than inferred from where it lives.
#
# NOTE: scripts/hooks/_provenance.py::trust_zone() was path-only and missed this
# class entirely. Surfaced separately rather than changed as a side effect of
# this build, then FIXED on the user's decision the same day — it now reads
# frontmatter provenance too (one-way: it can only downgrade to
# "untrusted-capture", never grant trust).
#
# This filter is kept INDEPENDENT of trust_zone on purpose. The index feeds
# every prompt, so it should not silently inherit a change in a shared
# primitive's semantics; two filters agreeing is a check, one filter is a
# single point of failure. They are cross-verified in
# scripts/test_retrieval_trust.py.
CAPTURE_PROVENANCE = re.compile(
    r'^(?:source|trust):\s*"?\s*(m365|m365-calendar|plaud|outlook|teams|'
    r'graph-api|untrusted|captured)',
    re.M | re.I,
)

FRONTMATTER_SCAN_BYTES = 1200   # enough for frontmatter; avoids reading bodies
LEADING_DATE = re.compile(r"^\d{4}[-_]\d{2}[-_]\d{2}[-_]?")

# Type prefixes carry no matching signal — every memory has one.
TYPE_PREFIXES = ("project_", "feedback_", "reference_", "bugs_", "bug_",
                 "user_", "install_", "meta_")

# Words that describe HOW something is discussed rather than WHAT it is about.
#
# Document frequency alone cannot catch these. `before` appears in just 3 memory
# slugs, so rarity scores it 24 — yet "review the SOW *before* Ben signs it"
# says nothing about topic. Rarity is measured inside this corpus; these words
# are rare HERE while being ubiquitous in English. Both filters are needed.
#
# Kept to function words and generic process nouns. Domain nouns — voice,
# finance, content, security, governance, gate — stay in, because
# over-stopwording destroys recall silently, which is far harder to notice
# than noise.
STOPWORDS = {
    # function words
    "the", "and", "for", "with", "not", "was", "are", "its", "into", "onto",
    "from", "that", "this", "have", "has", "but", "all", "any", "our", "your",
    "per", "via", "vs", "new", "old", "one", "two", "how", "why", "what",
    "when", "where", "who", "run", "use", "get", "set", "out", "off", "on",
    "in", "is", "it", "to", "of", "a", "an", "or", "no", "my", "me", "we",
    # pronouns. `you` was MISSING until 2026-08-10 while `your` was present —
    # it appears in nearly every conversational prompt, so "can you fix this
    # typo" matched two training modules on `you` alone. Found by debugging an
    # eval result that could not otherwise be explained.
    "you", "i", "he", "she", "they", "them", "him", "her", "us", "who",
    "their", "his", "hers", "ours", "yours", "mine",
    "before", "after", "during", "again", "still", "just", "only", "also",
    "more", "most", "less", "than", "then", "over", "under", "above", "below",
    "about", "upon", "each", "every", "some", "many", "much", "both", "few",
    "own", "such", "very", "too", "if", "as", "at", "by", "be", "been",
    "being", "do", "does", "did", "done", "can", "will", "would", "should",
    "could", "may", "might", "must", "shall",
    # generic process nouns — present in slugs, meaningless as a topic signal
    "person", "note", "notes", "file", "files", "index", "memory", "state",
    "process", "plan", "review", "check", "list", "data", "test", "tests",
    "work", "works", "working", "phase", "phases", "draft", "drafts", "date",
    "dates", "write", "writes", "writing", "written", "read", "reads",
    "thing", "things", "way", "ways", "time", "times", "day", "days", "week",
    "weeks", "month", "months", "year", "years", "name", "names", "line",
    "lines", "item", "items", "step", "steps", "level", "levels", "type",
    "types", "kind", "kinds", "form", "forms", "part", "parts", "whole",
    "same", "other", "others", "first", "last", "next", "status", "good",
    "bad", "best", "real", "true", "false", "full", "half",
    # structural words from VAULT filenames (added with the vault corpus).
    # Only words that describe a document's FORM, never its subject — df alone
    # already handles frequent topic words like `security` or `finance`.
    "overview", "readme", "template", "untitled", "copy", "final", "version",
    "page", "pages", "doc", "docs", "misc", "summary", "guide",
    # generic action verbs. These describe what the user wants DONE, never what the
    # note is about — "can you fix this typo" matched `fix-plan.md` on `fix`.
    # Same class as `write`, found the same way.
    "fix", "fixes", "fixed", "typo", "add", "adds", "added", "update",
    "updates", "updated", "change", "changes", "changed", "make", "makes",
    "made", "help", "need", "needs", "want", "wants", "show", "shows",
    "find", "finds", "look", "looks", "see", "take", "give", "put", "keep",
    "move", "start", "stop", "open", "close",
    # generic SUBFOLDER names. note_tokens() adds the parent folder because a
    # project folder (e.g. `Knowledge-Graph`, `Service-Bot`) is strong signal — but a
    # generic container is not, and it tags every file beneath it identically.
    "modules", "module", "handoffs", "drafts", "archive", "assets", "images",
    "attachments", "exports", "output", "outputs", "tmp", "temp", "src",
}

MIN_TOKEN_LEN = 3
MAX_DESC_BYTES = 240
MAX_NEIGHBOURS = 12


MAX_BODY_TOKENS = 40      # per entry. Caps index growth; see body_tokens().


def body_tokens(path, exclude):
    """Distinctive words from the note's BODY, for situational matching.

    WHY (2026-09-08): `k` held slug tokens ONLY, so the live hook effectively
    matched on FILENAMES. Measured against a 28-question goldset:
    memory-retrieve.py recall@10 0.54 vs BM25-over-bodies 0.92 on the same
    questions. Every miss was a situational prompt -- "does the build server
    server have antivirus or EDR" cannot reach
    bugs_buildserver_host_no_endpoint_protection, whose slug tokens are
    {buildserver, host, endpoint, protection}: zero overlap, score 0.

    Kept SEPARATE from `k` on purpose. A filename match is stronger evidence
    than a body mention, and merging them would also inflate the `coverage`
    denominator in score_entry(). The hook weights `b` below `k`.

    Ranked by in-document frequency so the cap keeps a note's own vocabulary
    rather than an arbitrary prefix of it.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    body = re.sub(r"^---.*?---", "", text, count=1, flags=re.S)
    body = re.sub(r"```.*?```", " ", body, flags=re.S)       # code blocks are not prose
    body = re.sub(r"\[\[([^\]]+)\]\]", r"\1", body)   # keep wikilink targets as words
    freq = {}
    for w in re.findall(r"[a-z0-9]+", body.lower()):
        if len(w) < MIN_TOKEN_LEN or w in STOPWORDS or w.isdigit():
            continue
        if w in exclude:                                      # already in `k`
            continue
        freq[w] = freq.get(w, 0) + 1
    ranked = sorted(freq.items(), key=lambda kv: (-kv[1], kv[0]))
    return sorted(w for w, _ in ranked[:MAX_BODY_TOKENS])


def slug_tokens(slug: str):
    """Matchable words for a memory slug. `reference_person_jane_doe` ->
    {jane, doe}. Order-insensitive; used for scoring in the hook."""
    name = slug
    for pre in TYPE_PREFIXES:
        if name.startswith(pre):
            name = name[len(pre):]
            break
    parts = re.split(r"[_\-\s]+", name.lower())
    return sorted({p for p in parts
                   if len(p) >= MIN_TOKEN_LEN and p not in STOPWORDS and not p.isdigit()})


def read_description(path: Path) -> str:
    """The frontmatter `description:` line, else the first non-empty body line."""
    try:
        text = io.open(path, encoding="utf-8", errors="replace").read()
    except Exception:
        return ""
    m = re.search(r"^description:\s*(.+?)\s*$", text, re.M)
    desc = ""
    if m:
        desc = m.group(1).strip().strip('"').strip("'")
    if not desc:
        body = re.sub(r"^---.*?---", "", text, count=1, flags=re.S)
        for line in body.splitlines():
            line = line.strip()
            if line and not line.startswith(("#", "-", "|", ">", "Tags:")):
                desc = line
                break
    raw = desc.encode("utf-8")[:MAX_DESC_BYTES]
    return raw.decode("utf-8", "ignore").strip()


def vault_root() -> Path:
    return Path(__file__).resolve().parent.parent


def note_tokens(rel_path: str):
    """Match tokens for a vault note: filename stem (leading date stripped)
    plus its parent folder, which usually names the project or BU."""
    p = Path(rel_path)
    stem = LEADING_DATE.sub("", p.stem)
    parent = p.parent.name if p.parent.name not in VAULT_ZONES else ""
    parts = re.split(r"[_\-\s.]+", (stem + " " + parent).lower())
    return sorted({x for x in parts
                   if len(x) >= MIN_TOKEN_LEN and x not in STOPWORDS
                   and not x.isdigit()})


def note_description(path: Path) -> str:
    """description: → title: → first heading → first body line."""
    try:
        text = io.open(path, encoding="utf-8", errors="replace").read(4000)
    except Exception:
        return ""
    for pat in (r"^description:\s*(.+?)\s*$", r"^title:\s*(.+?)\s*$"):
        m = re.search(pat, text, re.M)
        if m:
            d = m.group(1).strip().strip('"').strip("'")
            if d:
                return d.encode("utf-8")[:MAX_DESC_BYTES].decode("utf-8", "ignore").strip()
    body = re.sub(r"^---.*?---", "", text, count=1, flags=re.S)
    heading = re.search(r"^#{1,3}\s+(.+?)\s*$", body, re.M)
    if heading:
        return heading.group(1).encode("utf-8")[:MAX_DESC_BYTES].decode("utf-8", "ignore").strip()
    for line in body.splitlines():
        line = line.strip()
        if line and not line.startswith(("#", "-", "|", ">", "```", "Tags:")):
            return line.encode("utf-8")[:MAX_DESC_BYTES].decode("utf-8", "ignore").strip()
    return ""


def is_capture_sourced(path: Path) -> bool:
    """True when frontmatter shows capture provenance. Errors → True (exclude).

    Fail CLOSED: a file we cannot read is a file we cannot vouch for, and the
    cost of wrongly excluding one note is far lower than the cost of feeding
    untrusted captured text into every prompt.
    """
    try:
        head = io.open(path, encoding="utf-8", errors="replace").read(FRONTMATTER_SCAN_BYTES)
    except Exception:
        return True
    return bool(CAPTURE_PROVENANCE.search(head))


def collect_vault_notes():
    """[(rel_path, Path)] for authored, trusted notes. Excluded by dir AND by
    frontmatter provenance."""
    root = vault_root()
    out, skipped_prov = [], 0
    for zone in VAULT_ZONES:
        base = root / zone
        if not base.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in EXCLUDED_DIRS]
            for fn in filenames:
                if not fn.endswith(".md"):
                    continue
                full = Path(dirpath) / fn
                rel = full.relative_to(root).as_posix()
                if is_capture_sourced(full):
                    skipped_prov += 1
                    continue
                out.append((rel, full))
    return out, skipped_prov


def load_neighbours():
    """Two views of the graph, because memory files and vault notes attach to it
    differently:

      adj       node name -> connected node names. A MEMORY file IS a node
                (its stem), so this is its neighbourhood directly.
      by_file   source_file -> entities named in that file. A vault NOTE is not
                a node — it is the provenance recorded on edges extracted from
                it — so its connectivity is the entity set it discusses.

    Returns ({}, {}, 0) when the graph is absent.
    """
    if not GRAPH_PATH.exists():
        return {}, {}, 0
    try:
        data = json.loads(io.open(GRAPH_PATH, encoding="utf-8").read())
    except Exception:
        return {}, {}, 0
    adj, by_file = {}, {}
    edges = data.get("edges") or []
    for e in edges:
        a, b = e.get("from"), e.get("to")
        if a and b:
            adj.setdefault(a, set()).add(b)
            adj.setdefault(b, set()).add(a)
        sf = e.get("source_file")
        if sf:
            key = sf.replace("\\", "/")
            if a:
                by_file.setdefault(key, set()).add(a)
            if b:
                by_file.setdefault(key, set()).add(b)
    return adj, by_file, len(edges)


def build():
    if not MEMORY_DIR.exists():
        print("memory dir not found: %s" % MEMORY_DIR, file=sys.stderr)
        return None
    adj, by_file, n_edges = load_neighbours()
    entries = {}

    # --- memory layer: the file IS a graph node -----------------------------
    for path in sorted(MEMORY_DIR.glob("*.md")):
        slug = path.stem
        if slug == "MEMORY":          # the index itself is not a memory
            continue
        toks = slug_tokens(slug)
        if not toks:
            continue
        neigh = sorted(adj.get(slug, ()))[:MAX_NEIGHBOURS]
        entries[slug] = {"d": read_description(path), "n": neigh,
                         "k": toks, "b": body_tokens(path, set(toks)),
                         "kind": "memory"}

    # --- authored vault notes: connectivity comes from edge provenance ------
    notes, skipped_prov = collect_vault_notes()
    for rel, full in sorted(notes):
        toks = note_tokens(rel)
        if not toks:
            continue
        if rel in entries:            # never let a note shadow a memory slug
            continue
        neigh = sorted(by_file.get(rel, ()))[:MAX_NEIGHBOURS]
        entries[rel] = {"d": note_description(full), "n": neigh,
                        "k": toks, "b": body_tokens(full, set(toks)),
                        "kind": "vault"}
    build.skipped_prov = skipped_prov
    # Document frequency per token. Rarity — not token length — is what makes a
    # word identify a memory. a 4-character project code can appear in exactly one
    # file; `harness` is 7 and appears in dozens. A length heuristic gets this
    # exactly backwards, and did: a short, decisive project code scored below a
# long, common word until rarity replaced length.
    df = {}
    for entry in entries.values():
        for tok in entry["k"]:
            df[tok] = df.get(tok, 0) + 1

    # SEPARATE df for body tokens (2026-09-08). Two reasons, both measured:
    #
    # 1. They cannot be LEFT OUT. token_weight() falls back to df.get(tok, 1),
    #    so an unseen token reads as maximally rare and scores 30 — the top
    #    weight — purely by being unknown. That is backwards for common prose.
    #
    # 2. They cannot be MERGED INTO `df` either. A word's rarity as a FILENAME
    #    token is a different statistic from its rarity as a BODY word, and
    #    merging dilutes slug IDF. Measured: merging lifted recall@10 from
    #    0.536 to 0.643 but pushed one previously-correct query below
    #    SCORE_FLOOR, because its decisive slug token now appeared in dozens of
    #    bodies. Two maps keep the gain without the regression.
    dfb = {}
    for entry in entries.values():
        for tok in set(entry.get("b") or ()):
            dfb[tok] = dfb.get(tok, 0) + 1

    return {
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "graph_edges": n_edges,
        "graph_present": GRAPH_PATH.exists(),
        "df": df,
        "dfb": dfb,
        "entries": entries,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stats", action="store_true", help="print coverage detail")
    ap.add_argument("--out", default=None, help="override output path")
    args = ap.parse_args(argv)

    payload = build()
    if payload is None:
        return 1
    out = Path(args.out) if args.out else vault_root() / ".charon" / "memory-retrieval-index.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(out)

    entries = payload["entries"]
    isolated = sum(1 for v in entries.values() if not v["n"])
    no_desc = sum(1 for v in entries.values() if not v["d"])
    n_mem = sum(1 for v in entries.values() if v.get("kind") == "memory")
    n_vault = sum(1 for v in entries.values() if v.get("kind") == "vault")
    size = out.stat().st_size
    print("retrieval-index: %d entries (%d memory + %d vault) · %d KB · "
          "%d isolated (no graph edge) · %d without description"
          % (len(entries), n_mem, n_vault, size // 1024, isolated, no_desc))
    print("  excluded %d capture-sourced notes by frontmatter provenance"
          % getattr(build, "skipped_prov", 0))
    if not payload["graph_present"]:
        print("  WARNING: knowledge-graph.json absent — neighbours are empty", file=sys.stderr)

    if args.stats:
        counts = {}
        for v in entries.values():
            for t in v["k"]:
                counts[t] = counts.get(t, 0) + 1
        common = sorted(counts.items(), key=lambda kv: -kv[1])[:15]
        print("  most-shared tokens (over-match risk):")
        for t, c in common:
            print("    %-22s %d entries" % (t, c))
    return 0


if __name__ == "__main__":
    sys.exit(main())
