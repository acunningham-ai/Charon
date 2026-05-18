#!/usr/bin/env python3
"""One-shot inbox archive: move captures older than 30 days to 09-Archive/.

Source: 00-Inbox/_captured/email/** and 00-Inbox/_captured/teams/** (and any
other capture-source subdirs the user wires up)
Cutoff: file mtime older than (now - 30 days)
Destination: 09-Archive/_captured/<YYYY>/<email|teams|...>/... (preserves sub-structure)
Preserves: frontmatter (no file content modification)

Usage:
  python scripts/archive-captures.py --dry-run   # plan only
  python scripts/archive-captures.py --execute   # do the move
"""
import sys
import shutil
import time
from pathlib import Path
from collections import Counter

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.harness_paths import vault_root  # noqa: E402

VAULT = vault_root()
SRC_ROOT = VAULT / "00-Inbox" / "_captured"
DST_ROOT = VAULT / "09-Archive" / "_captured"
CUTOFF_SECONDS = 30 * 86400
NOW = time.time()
CUTOFF_MTIME = NOW - CUTOFF_SECONDS


def archive_year_for(mtime: float) -> str:
    return time.strftime("%Y", time.localtime(mtime))


def plan():
    """Return (to_move, by_year, by_subdir) without touching the filesystem."""
    to_move = []
    by_year = Counter()
    by_subdir = Counter()
    if not SRC_ROOT.exists():
        return to_move, by_year, by_subdir
    # Iterate every immediate subdir of _captured/ (email, teams, screenshots, etc.)
    for sub_path in SRC_ROOT.iterdir():
        if not sub_path.is_dir() or sub_path.name.startswith("_") or sub_path.name.startswith("."):
            continue
        sub = sub_path.name
        for path in sub_path.rglob("*.md"):
            try:
                mtime = path.stat().st_mtime
            except OSError:
                continue
            if mtime >= CUTOFF_MTIME:
                continue
            year = archive_year_for(mtime)
            rel = path.relative_to(SRC_ROOT)
            dst = DST_ROOT / year / rel
            to_move.append((path, dst))
            by_year[year] += 1
            by_subdir[sub] += 1
    return to_move, by_year, by_subdir


def execute(to_move):
    moved = 0
    errors = []
    for src, dst in to_move:
        try:
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            moved += 1
            if moved % 1000 == 0:
                print(f"  ... {moved} moved", flush=True)
        except Exception as e:
            errors.append((str(src), type(e).__name__, str(e)))
    return moved, errors


def main():
    if "--execute" not in sys.argv and "--dry-run" not in sys.argv:
        print("Specify --dry-run or --execute")
        return 1

    print(f"Cutoff: files with mtime older than {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(CUTOFF_MTIME))}")
    print(f"Source:      {SRC_ROOT}")
    print(f"Destination: {DST_ROOT}/<YYYY>/<sub>/...")
    print()

    to_move, by_year, by_subdir = plan()
    print(f"Files to archive: {len(to_move)}")
    print(f"  By subdir: {dict(by_subdir)}")
    print(f"  By year:   {dict(by_year)}")

    if to_move:
        print()
        print("Sample (first 3, last 3):")
        for src, dst in to_move[:3]:
            print(f"  {src.relative_to(VAULT)}")
            print(f"  -> {dst.relative_to(VAULT)}")
        if len(to_move) > 6:
            print("  ...")
        for src, dst in to_move[-3:]:
            print(f"  {src.relative_to(VAULT)}")
            print(f"  -> {dst.relative_to(VAULT)}")

    if "--dry-run" in sys.argv:
        print()
        print("DRY RUN — no files moved.")
        return 0

    print()
    print("Executing move...")
    moved, errors = execute(to_move)
    print()
    print(f"Done. Moved: {moved}, errors: {len(errors)}")
    if errors:
        print("First 10 errors:")
        for src, etype, msg in errors[:10]:
            print(f"  {src}: {etype}: {msg}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
