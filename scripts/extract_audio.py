"""extract_audio.py — local audio/video transcription via faster-whisper.

Transcribes an audio or video file (faster-whisper handles a wide range
of formats via FFmpeg) into a text file alongside it. Local-only — no
cloud API. Designed for meeting captures (from any recorder), voice
notes, and one-off transcriptions.

Usage::

    python scripts/extract_audio.py path/to/audio.m4a
    python scripts/extract_audio.py path/to/dir --recursive
    python scripts/extract_audio.py path/to/audio.m4a --model small
    python scripts/extract_audio.py path/to/audio.m4a --language en

Models (passed via ``--model``, default ``base``):
  tiny    ~75MB    fastest, lowest accuracy
  base    ~150MB   default — good for clear English speech
  small   ~500MB   noticeably more accurate, slower
  medium  ~1.5GB   research-grade
  large   ~3GB     slowest, highest accuracy

Optional deps:
  - ``faster-whisper`` (Python 3.11+) via ``requirements-multimodal.txt``
  - FFmpeg available on PATH (system install — not a Python dep)

First-run model download: faster-whisper auto-downloads the model to
``~/.cache/huggingface/`` on first use of each model size.

Output: ``<input>.txt`` alongside the input file, with a small frontmatter
block recording the model, language, and duration. Append-only — never
overwrites existing transcripts unless ``--force``.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Iterable, Optional, Tuple


# Common audio / video extensions faster-whisper handles via FFmpeg
_AUDIO_EXTS = frozenset({
    ".mp3", ".m4a", ".wav", ".aac", ".ogg", ".flac", ".opus",
    ".mp4", ".mov", ".mkv", ".webm", ".avi",
})


def _configure_stdio_for_unicode() -> None:
    if sys.platform.startswith("win"):
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass


# ---------- Availability ----------

def faster_whisper_available() -> Tuple[bool, str]:
    try:
        import faster_whisper  # noqa: F401
        return True, ""
    except ImportError:
        return False, "faster-whisper not installed — `pip install -r requirements-multimodal.txt` (Python 3.11+ required)"


# ---------- Transcription ----------

def transcribe_file(
    path: Path,
    *,
    model: str = "base",
    language: Optional[str] = None,
    compute_type: str = "int8",
) -> Tuple[Optional[str], str]:
    """Transcribe an audio/video file. Returns (text, status)."""
    ok, reason = faster_whisper_available()
    if not ok:
        return None, reason
    if not path.exists():
        return None, f"file not found: {path}"

    try:
        from faster_whisper import WhisperModel
        m = WhisperModel(model, compute_type=compute_type)
        segments, info = m.transcribe(str(path), language=language)
        # `segments` is a generator — materialise here so we can join.
        text_parts = []
        for seg in segments:
            text_parts.append(seg.text.strip())
        text = " ".join(p for p in text_parts if p)
        # Build a small frontmatter block
        front = (
            "---\n"
            f"transcribed_by: faster-whisper / model={model} / compute_type={compute_type}\n"
            f"language: {info.language}\n"
            f"language_probability: {info.language_probability:.3f}\n"
            f"duration_seconds: {info.duration:.1f}\n"
            f"transcribed_at: {time.strftime('%Y-%m-%dT%H:%M:%S')}\n"
            "---\n\n"
        )
        return front + text, "ok"
    except Exception as exc:
        return None, f"faster-whisper error: {type(exc).__name__}: {exc}"


def iter_audio_files(target: Path, recursive: bool) -> Iterable[Path]:
    if target.is_file():
        yield target
        return
    if not target.is_dir():
        return
    walker = target.rglob("*") if recursive else target.glob("*")
    for p in sorted(walker):
        if p.is_file() and p.suffix.lower() in _AUDIO_EXTS:
            yield p


# ---------- CLI ----------

def main() -> int:
    _configure_stdio_for_unicode()
    parser = argparse.ArgumentParser(description="Transcribe audio / video files into .txt siblings using faster-whisper")
    parser.add_argument("target", help="Audio/video file OR directory containing audio/video files")
    parser.add_argument("--model", default="base", help="Whisper model size: tiny / base / small / medium / large (default: base)")
    parser.add_argument("--language", help="ISO language code (e.g. en, fr). Default: auto-detect.")
    parser.add_argument("--compute-type", default="int8", help="CT2 quantisation: int8 / int8_float16 / float16 / float32 (default: int8)")
    parser.add_argument("--recursive", action="store_true", help="When target is a directory, walk it recursively")
    parser.add_argument("--force", action="store_true", help="Re-transcribe even when a .txt sibling already exists")
    args = parser.parse_args()

    ok, reason = faster_whisper_available()
    if not ok:
        sys.stderr.write(f"extract_audio: {reason}\n")
        return 2

    target = Path(args.target)
    if not target.exists():
        sys.stderr.write(f"target not found: {target}\n")
        return 1

    files = list(iter_audio_files(target, recursive=args.recursive))
    if not files:
        sys.stderr.write(f"no audio/video files found at {target}\n")
        return 1

    transcribed = 0
    skipped = 0
    failed = 0
    for path in files:
        out_path = path.with_suffix(".txt")
        if out_path.exists() and not args.force:
            skipped += 1
            continue
        print(f"  transcribing  {path.name}  (model={args.model}) ...", end="", flush=True)
        text, status = transcribe_file(
            path,
            model=args.model,
            language=args.language,
            compute_type=args.compute_type,
        )
        if text is None:
            print(f"  FAILED — {status}")
            failed += 1
            continue
        out_path.write_text(text, encoding="utf-8")
        print(f"  ok ({len(text):,} chars → {out_path.name})")
        transcribed += 1

    print()
    print(f"summary: {transcribed} transcribed, {skipped} skipped, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
