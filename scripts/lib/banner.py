"""banner.py — install + first-run banner rendering.

Two shapes:
  - SMALL: 5-line boxed text. Fits any terminal. Used by default.
  - FULL:  full ASCII trademark logo loaded from `charon-logo.txt`. Wide
    (~200 cols) — only renders when the terminal is wide enough OR when
    the caller passes `force_full=True`.

The full logo is the harness author's trademark mark; ships as part of
Charon. Adam owns the copyright on the logo. Distribution under the
repo's MIT license means downstream forks inherit it — keep it as the
project's identity unless replacing wholesale.
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

LOGO_PATH = Path(__file__).resolve().parent / "charon-logo.txt"

FULL_LOGO_WIDTH = 200  # approximate width of charon-logo.txt content
SMALL_BANNER_WIDTH = 60

SMALL_BANNER = r"""
+----------------------------------------------------------+
|                                                          |
|        CHARON  -  second-brain harness                   |
|        for Claude Code                                   |
|                                                          |
+----------------------------------------------------------+
""".strip("\n")


def terminal_width(default: int = 80) -> int:
    """Best-effort terminal width. Falls back to `default` if undetectable."""
    try:
        cols = shutil.get_terminal_size((default, 24)).columns
        return cols if cols and cols > 0 else default
    except Exception:
        return default


def load_full_logo() -> str:
    """Read the full ASCII logo from `charon-logo.txt`. Returns empty
    string if the file is missing (degrades to small banner)."""
    try:
        return LOGO_PATH.read_text(encoding="utf-8").rstrip("\n")
    except Exception:
        return ""


def render_banner(
    *,
    force_full: bool = False,
    force_small: bool = False,
    no_logo: bool = False,
    width: int | None = None,
) -> str:
    """Return the banner text appropriate for the current terminal.

    Selection precedence:
      1. no_logo=True   → empty string
      2. force_full     → full logo (even if it'll wrap)
      3. force_small    → small banner
      4. auto-detect    → full if width >= FULL_LOGO_WIDTH else small
    """
    if no_logo:
        return ""
    if force_full:
        full = load_full_logo()
        return full if full else SMALL_BANNER
    if force_small:
        return SMALL_BANNER
    cols = width if width is not None else terminal_width()
    if cols >= FULL_LOGO_WIDTH:
        full = load_full_logo()
        if full:
            return full
    return SMALL_BANNER


def print_banner(
    *,
    force_full: bool = False,
    force_small: bool = False,
    no_logo: bool = False,
    width: int | None = None,
    stream=None,
) -> None:
    """Print the banner to `stream` (default: stdout). No-op when empty."""
    text = render_banner(
        force_full=force_full,
        force_small=force_small,
        no_logo=no_logo,
        width=width,
    )
    if not text:
        return
    out = stream or sys.stdout
    print(text, file=out)
    print(file=out)


def parse_logo_flag(argv: list[str]) -> dict:
    """Parse --logo / --no-logo flags. Returns kwargs for render_banner.

    Recognised:
      --logo full      → force_full
      --logo small     → force_small
      --no-logo        → no_logo
    Unrecognised values for --logo fall back to auto-detect.
    """
    kwargs: dict = {}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--no-logo":
            kwargs["no_logo"] = True
        elif a == "--logo" and i + 1 < len(argv):
            v = argv[i + 1].lower()
            if v == "full":
                kwargs["force_full"] = True
            elif v == "small":
                kwargs["force_small"] = True
            i += 1
        i += 1
    return kwargs


if __name__ == "__main__":
    flags = parse_logo_flag(sys.argv[1:])
    print_banner(**flags)
