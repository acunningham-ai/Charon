"""semantic.py — local semantic-search core.

Shared library for:
- `scripts/semantic_index.py` (CLI indexer)
- `scripts/mcp/vault-readonly-server.py` (the semantic_search MCP tool)

Local-first design:
- Embedding model: `bge-micro-v2` via sentence-transformers (~80MB,
  pure-Python, runs on CPU, no GPU required)
- Vector store: sqlite-vec extension (single SQLite file)
- No network calls at index or query time

Graceful degradation: if `sentence-transformers`, `sqlite-vec`, or `numpy`
aren't installed, `is_available()` returns False and callers should
no-op + surface a helpful "install with requirements-semantic.txt" pointer.

The index file lives at <HARNESS_VAULT_ROOT>/.charon/semantic-index.db.
"""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Iterable

from .harness_paths import vault_root


MODEL_NAME = "BAAI/bge-micro-v2"
EMBED_DIM = 384  # bge-micro-v2 produces 384-d vectors
INDEX_REL_PATH = ".charon/semantic-index.db"


def is_available() -> tuple[bool, str]:
    """Returns (available, reason). reason is empty on success."""
    try:
        import sentence_transformers  # noqa: F401
    except ImportError:
        return False, "sentence-transformers not installed"
    try:
        import sqlite_vec  # noqa: F401
    except ImportError:
        return False, "sqlite-vec not installed"
    try:
        import numpy  # noqa: F401
    except ImportError:
        return False, "numpy not installed"
    return True, ""


def index_path() -> Path:
    return vault_root() / INDEX_REL_PATH


# ---------- Model loading (cached at module level) ----------

_model = None


def get_model():
    """Load the embedding model. Cached per process."""
    global _model
    if _model is not None:
        return _model
    from sentence_transformers import SentenceTransformer
    _model = SentenceTransformer(MODEL_NAME, device="cpu")
    return _model


def embed(texts: list[str]) -> list[list[float]]:
    """Embed a list of texts. Returns a list of lists (not numpy) for SQLite compatibility."""
    model = get_model()
    vectors = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return [vec.tolist() for vec in vectors]


# ---------- SQLite + sqlite-vec setup ----------

def open_index(create_if_missing: bool = True) -> sqlite3.Connection:
    """Open the sqlite-vec-enabled index. Creates schema on first use."""
    import sqlite_vec

    path = index_path()
    if not path.exists():
        if not create_if_missing:
            raise FileNotFoundError(f"Semantic index not found at {path}. Run scripts/semantic_index.py first.")
        path.parent.mkdir(parents=True, exist_ok=True)

    conn = sqlite3.connect(str(path))
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)

    # Schema:
    #   documents — one row per file chunk (file_path + chunk_idx → text + hash)
    #   embeddings — sqlite-vec virtual table linking chunk → vector
    conn.executescript(f"""
        CREATE TABLE IF NOT EXISTS documents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT NOT NULL,
            chunk_idx INTEGER NOT NULL,
            chunk_text TEXT NOT NULL,
            file_hash TEXT NOT NULL,
            mtime REAL NOT NULL,
            UNIQUE(file_path, chunk_idx)
        );
        CREATE INDEX IF NOT EXISTS idx_documents_path ON documents(file_path);

        CREATE VIRTUAL TABLE IF NOT EXISTS embeddings USING vec0(
            embedding float[{EMBED_DIM}]
        );
    """)
    return conn


def file_content_hash(path: Path) -> str:
    """SHA-256 of file contents — for change detection during incremental indexing."""
    h = hashlib.sha256()
    try:
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
    except Exception:
        return ""
    return h.hexdigest()


# ---------- Chunking ----------

def chunk_markdown(text: str, max_chars: int = 1500, overlap: int = 200) -> list[str]:
    """Naive paragraph-aware chunking. Splits on blank lines; merges small
    paragraphs up to max_chars; adds overlap from prior chunk for context."""
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: list[str] = []
    current = ""
    for para in paragraphs:
        if len(current) + len(para) + 2 > max_chars and current:
            chunks.append(current.strip())
            tail = current[-overlap:] if overlap and len(current) > overlap else ""
            current = (tail + "\n\n" + para) if tail else para
        else:
            current = (current + "\n\n" + para) if current else para
    if current.strip():
        chunks.append(current.strip())
    return chunks or [text.strip()] if text.strip() else []


# ---------- Indexing operations ----------

def index_file(conn: sqlite3.Connection, file_path: Path, vault: Path) -> int:
    """Index a single file. Returns the number of chunks indexed (0 if unchanged or skipped)."""
    import json

    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception:
        return 0
    if not content.strip():
        return 0

    rel = file_path.relative_to(vault).as_posix()
    file_hash = file_content_hash(file_path)
    mtime = file_path.stat().st_mtime

    # Check if file unchanged
    existing = conn.execute(
        "SELECT file_hash FROM documents WHERE file_path = ? LIMIT 1",
        (rel,),
    ).fetchone()
    if existing and existing[0] == file_hash:
        return 0

    # Remove old entries for this file
    old_ids = [
        row[0]
        for row in conn.execute(
            "SELECT id FROM documents WHERE file_path = ?", (rel,)
        ).fetchall()
    ]
    if old_ids:
        placeholders = ",".join("?" * len(old_ids))
        conn.execute(f"DELETE FROM embeddings WHERE rowid IN ({placeholders})", old_ids)
        conn.execute("DELETE FROM documents WHERE file_path = ?", (rel,))

    chunks = chunk_markdown(content)
    if not chunks:
        conn.commit()
        return 0

    vectors = embed(chunks)
    for idx, (chunk, vec) in enumerate(zip(chunks, vectors)):
        cur = conn.execute(
            "INSERT INTO documents (file_path, chunk_idx, chunk_text, file_hash, mtime) "
            "VALUES (?, ?, ?, ?, ?)",
            (rel, idx, chunk, file_hash, mtime),
        )
        doc_id = cur.lastrowid
        conn.execute(
            "INSERT INTO embeddings(rowid, embedding) VALUES (?, ?)",
            (doc_id, json.dumps(vec)),
        )
    conn.commit()
    return len(chunks)


def remove_file(conn: sqlite3.Connection, file_path_rel: str) -> None:
    """Remove all chunks for a deleted file."""
    old_ids = [
        row[0]
        for row in conn.execute(
            "SELECT id FROM documents WHERE file_path = ?", (file_path_rel,)
        ).fetchall()
    ]
    if old_ids:
        placeholders = ",".join("?" * len(old_ids))
        conn.execute(f"DELETE FROM embeddings WHERE rowid IN ({placeholders})", old_ids)
        conn.execute("DELETE FROM documents WHERE file_path = ?", (file_path_rel,))
        conn.commit()


# ---------- Search ----------

def search(query: str, k: int = 10, scope_prefix: str | None = None) -> list[dict]:
    """Run a semantic search. Returns list of dicts: {file_path, chunk_text, distance}."""
    import json

    conn = open_index(create_if_missing=False)
    qvec = embed([query])[0]

    base_sql = """
        SELECT
            d.file_path,
            d.chunk_idx,
            d.chunk_text,
            e.distance
        FROM embeddings e
        JOIN documents d ON d.id = e.rowid
        WHERE e.embedding MATCH ?
    """
    params: list = [json.dumps(qvec)]

    if scope_prefix:
        base_sql += " AND d.file_path LIKE ?"
        params.append(scope_prefix.rstrip("/") + "%")

    base_sql += " ORDER BY e.distance ASC LIMIT ?"
    params.append(k)

    results = []
    for row in conn.execute(base_sql, params).fetchall():
        results.append({
            "file_path": row[0],
            "chunk_idx": row[1],
            "chunk_text": row[2],
            "distance": float(row[3]),
        })
    return results


# ---------- Stats ----------

def stats() -> dict:
    """Return index stats — file count, chunk count, last index time."""
    try:
        conn = open_index(create_if_missing=False)
    except FileNotFoundError:
        return {"available": True, "indexed": False, "files": 0, "chunks": 0}

    files = conn.execute("SELECT COUNT(DISTINCT file_path) FROM documents").fetchone()[0]
    chunks = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    return {"available": True, "indexed": True, "files": files, "chunks": chunks}


# ---------- Default paths to index ----------

DEFAULT_INCLUDE_GLOBS = [
    "02-BUs/**/*.md",
    "03-Domains/**/*.md",
    "04-People/**/*.md",
    "06-Decisions/**/*.md",
    "07-References/**/*.md",
    "08-Projects/**/*.md",
    "CLAUDE.md",
    "TODO.md",
]

DEFAULT_EXCLUDE_GLOBS = [
    "**/00-Inbox/_captured/**",         # untrusted — don't index
    "**/09-Archive/**",                 # cold storage
    "**/_pickup*.md",                   # ephemeral
    "**/.charon/**",                    # the index itself
    "**/voice-examples/**",             # input files for voice
]
