#!/usr/bin/env python3
"""extract_entities.py — extract entities + relationships from vault files.

Reads vault markdown, calls Haiku to extract structured entities + relationships,
writes them into the networkx knowledge graph at `.charon/knowledge-graph.json`.

Usage:
    python scripts/extract_entities.py                # incremental (only changed files)
    python scripts/extract_entities.py --rebuild      # wipe and re-extract everything
    python scripts/extract_entities.py --stats        # print graph stats; don't extract
    python scripts/extract_entities.py --paths a.md b.md

Dependencies (optional — installed via requirements-graph.txt):
    networkx

Anthropic API key required (read from <HARNESS_SECRETS_DIR>/anthropic.json).
Without it, the extractor errors with a clear pointer to FIRST-RUN.md.

Costs: ~$0.001-0.01 per file via Haiku (varies by content length). On a
500-file vault the full extraction is roughly $0.50-2. Incremental
extraction processes only changed files — typically a handful per run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import graph  # noqa: E402
from lib.harness_paths import secrets_dir, vault_root  # noqa: E402


HAIKU_MODEL = "claude-haiku-4-5-20251001"
HAIKU_TIMEOUT_S = 30
HAIKU_MAX_TOKENS = 8000            # 1500 truncated entity-rich files; Haiku 4.5's output ceiling is far higher
MAX_CHUNK_CHARS = 12000            # split larger files on heading boundaries (truncation-proofing)

EXTRACTION_PROMPT = """You extract structured entities and relationships from a markdown file for storage in a knowledge graph.

Entity types (closed set — only use these):
- person       — named individuals (people, by name)
- project      — named work initiatives, products, codebases
- org_unit     — business units, departments, customer accounts, portfolio companies
- tool         — software / vendors / platforms / services
- concept      — durable ideas, frameworks, methodologies (e.g. "OWASP LLM Top 10", "C-3 control")
- event        — meetings, incidents, decisions, releases (one-time happenings)
- document     — referenced reports, policies, specs, papers

Relationship types (closed set — only use these):
- WORKS_ON      — person → project
- OWNS          — person/org_unit → project/tool
- AFFECTS       — event/decision → project/org_unit
- REFERENCES    — document → entity
- DEPENDS_ON    — project → tool/project
- REPORTS_TO    — person → person
- PART_OF       — org_unit → org_unit
- INVOLVES      — event → person
- RECOMMENDED_BY — tool → person
- MENTIONS      — document → entity (use when nothing else fits)

Output STRICT JSON only. No prose, no markdown fencing.

Schema:
{
  "entities": [
    {"name": "<canonical display name>", "type": "<one of the types above>"}
  ],
  "relationships": [
    {"from": "<entity name>", "to": "<entity name>", "type": "<one of the rel types above>", "confidence": 0.9}
  ]
}

Rules:
- Extract entities and relationships ONLY from the file's authored content. Ignore frontmatter `type`/`name` fields — those are file metadata, not content claims.
- Use confidence 0.9 for explicit statements, 0.7 for clear implications, 0.5 for hedged claims.
- Do NOT extract every passing reference. Only entities that the file makes substantive claims about.
- If the file is short or has no substantive entity claims, return empty arrays.
- Never invent. If unsure, omit.
- Keep entity names as displayed in the source (preserve casing).
"""


def load_api_key() -> str | None:
    try:
        data = json.loads((secrets_dir() / "anthropic.json").read_text(encoding="utf-8"))
        return data.get("api_key") or data.get("anthropic_api_key")
    except Exception:
        return None


def call_haiku(file_content: str, api_key: str) -> dict:
    """One extraction call. Returns exactly one of:

      {entities: [...], relationships: [...]}  — success
      {"_truncated": True}                     — output hit max_tokens; caller should chunk
      {"_error": "<reason>"}                   — hard failure

    Truncation is reported rather than swallowed. Previously an over-long output
    produced cut-off JSON, which surfaced as the misleading "haiku returned
    non-JSON" — a fixable size problem disguised as a model fault.
    """
    # Chunking in extract_file keeps inputs bounded; this is only a final cap.
    if len(file_content) > 40000:
        file_content = file_content[:40000] + "\n\n[TRUNCATED]"
    body = json.dumps({
        "model": HAIKU_MODEL,
        "max_tokens": HAIKU_MAX_TOKENS,
        "system": EXTRACTION_PROMPT,
        "messages": [{"role": "user", "content": file_content}],
    }).encode("utf-8")
    req = urllib.request.Request(
        "https://api.anthropic.com/v1/messages",
        data=body,
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=HAIKU_TIMEOUT_S) as resp:
            payload = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"_error": f"{type(e).__name__}: {e}"}
    # Detect output truncation BEFORE parsing: cut-off JSON would otherwise be
    # reported as a model formatting fault instead of a size problem to chunk.
    if payload.get("stop_reason") == "max_tokens":
        return {"_truncated": True}
    blocks = payload.get("content") or []
    text = "".join(b.get("text", "") for b in blocks if b.get("type") == "text").strip()
    # Strip markdown fences if Haiku added them
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        text = text.strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return {"_error": "haiku returned non-JSON"}
    return parsed


def chunk_content(content: str) -> list[str]:
    """Split a file into <=MAX_CHUNK_CHARS chunks at markdown heading boundaries.

    Returns [content] unchanged when it already fits, so small files keep the
    single-call fast path. A headingless section that overruns the cap is
    hard-split, so one giant block cannot defeat chunking.

    Note the effective ceiling is a soft ~1.5x MAX_CHUNK_CHARS, not a hard cap: a
    chunk closes mid-section only once it passes that, which keeps related prose
    together at the cost of overshoot — and up to ~2x on the hard-split path,
    where whole cap-sized pieces are appended at once. `call_haiku`'s 40000-char
    cap is the real backstop, which is why it is set well above this."""
    if len(content) <= MAX_CHUNK_CHARS:
        return [content]
    chunks: list[str] = []
    cur: list[str] = []
    cur_len = 0
    # Split overlong single lines first. Splitting only on "\n" meant a file with
    # no newlines — a minified blob, an ingested one-paragraph transcript — came
    # back as ONE oversized chunk, and the guarantee above was false. extract_file
    # would still recover it via the truncation path, but only after spending a
    # wasted API call to discover the problem.
    lines: list[str] = []
    for raw_line in content.split("\n"):
        if len(raw_line) <= MAX_CHUNK_CHARS:
            lines.append(raw_line)
        else:
            lines.extend(raw_line[i:i + MAX_CHUNK_CHARS]
                         for i in range(0, len(raw_line), MAX_CHUNK_CHARS))
    for line in lines:
        is_heading = line.startswith("#")
        if cur and is_heading and cur_len >= MAX_CHUNK_CHARS:
            chunks.append("\n".join(cur))
            cur, cur_len = [], 0
        cur.append(line)
        cur_len += len(line) + 1
        if cur_len >= int(MAX_CHUNK_CHARS * 1.5) and not is_heading:
            chunks.append("\n".join(cur))
            cur, cur_len = [], 0
    if cur:
        chunks.append("\n".join(cur))
    return chunks or [content]


def extract_file(content: str, api_key: str) -> dict:
    """Extract from one file, chunking when a single pass truncates on output.

    Returns {entities, relationships} merged and deduped across chunks, or
    {"_error": ...}. Never returns {"_truncated"} — truncation is resolved here
    rather than passed to the caller.

    A large note previously lost every entity past the input cap with no warning.
    One bad chunk no longer fails the whole file; partial extraction beats none,
    and the failed chunks are reported."""
    chunks = chunk_content(content)
    if len(chunks) == 1:
        raw = call_haiku(chunks[0], api_key)
        if not raw.get("_truncated"):
            return raw  # success dict, or {"_error": ...}
        # A single chunk that still truncated on output → force a hard split.
        chunks = [content[i:i + MAX_CHUNK_CHARS]
                  for i in range(0, len(content), MAX_CHUNK_CHARS)]

    ents: list[dict] = []
    rels: list[dict] = []
    any_ok = False
    errs: list[str] = []
    for ch in chunks:
        r = call_haiku(ch, api_key)
        if r.get("_error") or r.get("_truncated"):
            errs.append(r.get("_error") or "truncated")
            continue  # skip the bad chunk; don't lose the whole file to one
        any_ok = True
        ents.extend(r.get("entities", []) or [])
        rels.extend(r.get("relationships", []) or [])
    if not any_ok:
        return {"_error": "; ".join(errs) or "all chunks failed"}

    # Dedup across chunks: the same entity legitimately appears in several.
    seen_e: set = set()
    uniq_e = []
    for e in ents:
        k = (e.get("name"), e.get("type"))
        if k not in seen_e:
            seen_e.add(k)
            uniq_e.append(e)
    seen_r: set = set()
    uniq_r = []
    for r in rels:
        k = (r.get("from"), r.get("to"), r.get("type"))
        if k not in seen_r:
            seen_r.add(k)
            uniq_r.append(r)
    result = {"entities": uniq_e, "relationships": uniq_r}
    if errs:
        # Surface partial success rather than reporting a clean run.
        result["_partial"] = f"{len(errs)} of {len(chunks)} chunk(s) failed: {'; '.join(errs[:3])}"
    return result


def sanitize_extraction(raw: dict) -> dict:
    """Filter to allowed entity types + relationship types; drop bad entries."""
    if not isinstance(raw, dict):
        return {"entities": [], "relationships": []}
    entities = []
    for e in raw.get("entities", []) or []:
        if not isinstance(e, dict):
            continue
        name = (e.get("name") or "").strip()
        etype = (e.get("type") or "").strip().lower()
        if name and etype in graph.ENTITY_TYPES:
            entities.append({"name": name, "type": etype})
    rels = []
    for r in raw.get("relationships", []) or []:
        if not isinstance(r, dict):
            continue
        rtype = (r.get("type") or "").strip().upper()
        if rtype not in graph.RELATIONSHIP_TYPES:
            continue
        from_ = (r.get("from") or "").strip()
        to_ = (r.get("to") or "").strip()
        if not (from_ and to_):
            continue
        conf = r.get("confidence")
        try:
            conf = float(conf) if conf is not None else 0.7
            conf = max(0.0, min(1.0, conf))
        except Exception:
            conf = 0.7
        rels.append({"from": from_, "to": to_, "type": rtype, "confidence": conf})
    return {"entities": entities, "relationships": rels}


def gather_files(vault: Path) -> list[Path]:
    """Vault files to extract from — mirrors the semantic-index include set."""
    import fnmatch
    includes = [
        "02-BUs/**/*.md",
        "03-Domains/**/*.md",
        "04-People/**/*.md",
        "06-Decisions/**/*.md",
        "07-References/**/*.md",
        "08-Projects/**/*.md",
        "CLAUDE.md",
    ]
    excludes = [
        "**/00-Inbox/_captured/**",
        "**/09-Archive/**",
        "**/_pickup*.md",
        "**/.charon/**",
        "**/voice-examples/**",
    ]
    candidates: set[Path] = set()
    for pattern in includes:
        for p in vault.glob(pattern):
            if p.is_file() and p.suffix.lower() == ".md":
                candidates.add(p.resolve())

    def excluded(p: Path) -> bool:
        rel = p.relative_to(vault).as_posix()
        for pat in excludes:
            if fnmatch.fnmatch(rel, pat):
                return True
        return False

    return sorted(p for p in candidates if not excluded(p))


def cmd_stats() -> int:
    available, reason = graph.is_available()
    if not available:
        print(f"Knowledge graph NOT available ({reason}).")
        print("Install with: pip install -r requirements-graph.txt")
        return 1
    try:
        _, conn = graph.open_graph(create_if_missing=False)
    except FileNotFoundError:
        print("Graph not initialised. Run extract_entities.py to build it.")
        return 0
    s = graph.stats(conn)
    print(f"Knowledge graph — stats")
    print(f"  Path:   {graph.graph_path()}")
    print(f"  Nodes:  {s['nodes']}")
    print(f"  Edges:  {s['edges']}")
    return 0


def cmd_extract(rebuild: bool, specific_paths: list[str] | None) -> int:
    available, reason = graph.is_available()
    if not available:
        sys.stderr.write(f"Knowledge graph deps missing: {reason}\n")
        sys.stderr.write("Install with: pip install -r requirements-graph.txt\n")
        return 1
    api_key = load_api_key()
    if not api_key:
        sys.stderr.write(
            f"No Anthropic API key found at {secrets_dir() / 'anthropic.json'}.\n"
            f"Extraction uses Haiku — set up the key via the first-run wizard.\n"
        )
        return 1

    vault = vault_root()
    if rebuild:
        gp = graph.graph_path()
        if gp.exists():
            import shutil
            shutil.rmtree(gp, ignore_errors=True) if gp.is_dir() else gp.unlink()
            print(f"  Removed existing graph: {gp}")

    db, conn = graph.open_graph(create_if_missing=True)

    if specific_paths:
        files = [Path(p).resolve() for p in specific_paths if Path(p).exists()]
    else:
        files = gather_files(vault)

    print(f"  Vault: {vault}")
    print(f"  Graph: {graph.graph_path()}")
    print(f"  Files to process: {len(files)}")

    start = time.time()
    extracted_n = 0
    failed = 0
    for i, f in enumerate(files, 1):
        try:
            content = f.read_text(encoding="utf-8")
        except Exception:
            failed += 1
            continue
        if not content.strip() or len(content) < 100:
            continue

        raw = extract_file(content, api_key)  # chunk-aware: resolves output truncation by splitting
        if raw.get("_partial"):
            # Report rather than silently bank a partial result as a clean one.
            print(f"  [{i}/{len(files)}] {f.relative_to(vault).as_posix()} — PARTIAL: {raw['_partial']}")
        if raw.get("_error"):
            print(f"  [{i}/{len(files)}] {f.relative_to(vault).as_posix()} — extraction error: {raw['_error']}")
            failed += 1
            continue
        clean = sanitize_extraction(raw)

        rel_path = f.relative_to(vault).as_posix()
        for ent in clean["entities"]:
            try:
                graph.upsert_entity(conn, ent["name"], ent["name"], ent["type"])
            except Exception as e:
                print(f"    upsert error on {ent['name']}: {e}")
        for r in clean["relationships"]:
            try:
                graph.add_relationship(
                    conn,
                    r["from"], r["to"], r["type"],
                    source_file=rel_path,
                    confidence=r["confidence"],
                )
            except Exception as e:
                print(f"    relationship error {r['from']} -[{r['type']}]-> {r['to']}: {e}")

        n_ent = len(clean["entities"])
        n_rel = len(clean["relationships"])
        extracted_n += n_ent + n_rel
        if n_ent + n_rel:
            print(f"  [{i}/{len(files)}] {rel_path} — {n_ent} entities, {n_rel} relationships")

    conn.save()  # networkx store is in-memory until persisted; write once after the batch

    elapsed = time.time() - start
    print()
    print(f"Done. {extracted_n} total inserts, {failed} files failed. {elapsed:.1f}s")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Extract entities + relationships into the Charon knowledge graph")
    parser.add_argument("--rebuild", action="store_true",
                        help="wipe the graph and re-extract everything")
    parser.add_argument("--stats", action="store_true",
                        help="print graph stats; don't extract")
    parser.add_argument("--paths", nargs="+",
                        help="extract only from these specific files")
    args = parser.parse_args()
    if args.stats:
        return cmd_stats()
    return cmd_extract(args.rebuild, args.paths)


if __name__ == "__main__":
    sys.exit(main())
