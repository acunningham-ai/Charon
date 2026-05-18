#!/usr/bin/env python3
"""semantic_index.py — build/refresh the local semantic search index.

Walks the vault per the include/exclude globs configured in
`scripts/lib/semantic.py`, embeds each file's chunks via sentence-transformers
(`bge-micro-v2`, ~80MB, CPU-only), and stores in sqlite-vec at
`<HARNESS_VAULT_ROOT>/.charon/semantic-index.db`.

Usage:
    python scripts/semantic_index.py                 # incremental: only changed files
    python scripts/semantic_index.py --rebuild       # full rebuild (drops the index first)
    python scripts/semantic_index.py --stats         # print index stats; don't index
    python scripts/semantic_index.py --paths a.md b.md  # index specific files only

The index is build-once / refresh-on-demand. Recommended cadence: run
nightly via your scheduler, or after a significant burst of writes. The
PostToolUse hook does NOT auto-index on every write — embedding takes
~50ms per chunk + ~5s for first-load model warm-up, too slow for the
synchronous hook chain.

Without the optional `sentence-transformers`/`sqlite-vec`/`numpy` deps
installed, the script prints a pointer to `requirements-semantic.txt` and
exits.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import semantic  # noqa: E402
from lib.harness_paths import vault_root  # noqa: E402


SEMANTIC_DEPS_HINT = (
    "Semantic search needs extra dependencies. Install with:\n"
    "    pip install -r requirements-semantic.txt\n"
    "Or via the first-run wizard ('Enable semantic search?').\n"
)


def gather_files(vault: Path, includes: list[str], excludes: list[str]) -> list[Path]:
    """Walk vault per glob patterns; return de-duped sorted list of files to index."""
    import fnmatch

    candidates: set[Path] = set()
    for pattern in includes:
        for p in vault.glob(pattern):
            if p.is_file() and p.suffix.lower() == ".md":
                candidates.add(p.resolve())

    def excluded(p: Path) -> bool:
        rel = p.relative_to(vault).as_posix()
        for pat in excludes:
            # Normalise glob: ** → match any path segment(s)
            pat_norm = pat.replace("**/", "*/").replace("/**", "/*")
            if fnmatch.fnmatch(rel, pat) or fnmatch.fnmatch(rel, pat_norm):
                return True
        return False

    return sorted(p for p in candidates if not excluded(p))


def cmd_stats() -> int:
    ok, reason = semantic.is_available()
    if not ok:
        print(f"Semantic search NOT available ({reason}).")
        print(SEMANTIC_DEPS_HINT)
        return 1
    s = semantic.stats()
    print(f"Semantic index — stats")
    print(f"  Available: {s['available']}")
    print(f"  Indexed:   {s['indexed']}")
    if s["indexed"]:
        print(f"  Files:     {s['files']}")
        print(f"  Chunks:    {s['chunks']}")
        print(f"  Path:      {semantic.index_path()}")
    return 0


def cmd_index(rebuild: bool, specific_paths: list[str] | None) -> int:
    ok, reason = semantic.is_available()
    if not ok:
        sys.stderr.write(f"Semantic search dependencies missing: {reason}\n")
        sys.stderr.write(SEMANTIC_DEPS_HINT)
        return 1

    vault = vault_root()
    if rebuild:
        idx = semantic.index_path()
        if idx.exists():
            idx.unlink()
            print(f"  Removed existing index: {idx}")

    conn = semantic.open_index(create_if_missing=True)

    if specific_paths:
        files = [Path(p).resolve() for p in specific_paths if Path(p).exists()]
    else:
        files = gather_files(
            vault,
            semantic.DEFAULT_INCLUDE_GLOBS,
            semantic.DEFAULT_EXCLUDE_GLOBS,
        )

    print(f"  Vault: {vault}")
    print(f"  Index: {semantic.index_path()}")
    print(f"  Files to consider: {len(files)}")

    print("  Loading embedding model (first run may download ~80MB)...")
    semantic.get_model()  # warm up
    print("  Model ready.")

    start = time.time()
    indexed_chunks = 0
    skipped = 0
    for i, f in enumerate(files, 1):
        n = semantic.index_file(conn, f, vault)
        if n > 0:
            indexed_chunks += n
            print(f"  [{i}/{len(files)}] {f.relative_to(vault).as_posix()} ({n} chunks)")
        else:
            skipped += 1
        if i % 50 == 0:
            elapsed = time.time() - start
            print(f"  ... {i}/{len(files)} files, {indexed_chunks} chunks, {elapsed:.1f}s")

    elapsed = time.time() - start
    print()
    print(f"Done. {indexed_chunks} chunks indexed, {skipped} files unchanged. Total: {elapsed:.1f}s")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Build/refresh the Charon semantic index")
    parser.add_argument("--rebuild", action="store_true",
                        help="drop the existing index and re-embed everything")
    parser.add_argument("--stats", action="store_true",
                        help="print index stats; don't index")
    parser.add_argument("--paths", nargs="+",
                        help="index only these specific files")
    args = parser.parse_args()

    if args.stats:
        return cmd_stats()
    return cmd_index(args.rebuild, args.paths)


if __name__ == "__main__":
    sys.exit(main())
