#!/usr/bin/env python3
"""backup-brain.py - offline backup and restore for a Charon brain.

WHY THIS EXISTS
---------------
A Charon brain has two halves, and they usually live in different places:

  1. The VAULT (your notes) - often already in Dropbox/OneDrive/iCloud/git.
  2. The HARNESS STATE - `~/.claude` (memory, session summaries, transcripts) and
     the capture-pipeline directory. This half is almost never synced, because it
     sits in a hidden home-directory folder nobody thinks to back up.

Losing half 2 loses every rule the harness has learned about you: your memory
files, your session history, your pipeline state. The vault survives and the
brain arrives on the new machine amnesiac.

This tool backs up BOTH halves to a removable drive you control (keep it
somewhere physically safe), and restores them onto a new machine.

TARGETING
---------
The destination is found by a MARKER FILE (`.charon-backup-target`) in a volume
root, never by drive letter or mount path - those change between machines and
reboots, which is precisely the situation a migration tool must survive.

    Windows : any drive root, e.g.  D:\\.charon-backup-target
    macOS   : /Volumes/<name>/.charon-backup-target
    Linux   : /media/<user>/<name>/ or /mnt/<name>/.charon-backup-target

SILENCE IS NOT SUCCESS
----------------------
A backup drive kept somewhere safe is usually NOT plugged in, so most scheduled
runs legitimately find nothing. A job that quietly no-ops in that situation is
indistinguishable from a job that has been broken for months. So every run writes
a status file recording `last_attempt` AND `last_success` SEPARATELY. Liveness
checks must judge `last_success` - never the log's mtime, which stays fresh
forever while nothing is actually being backed up.

SECRETS - THIS TOOL NEVER COPIES THEM, AND THAT IS DELIBERATE
--------------------------------------------------------------
There is no option to back up credential values. Not a guarded one, not a flagged
one - none. This tool cannot encrypt, and as a normal-user process it cannot verify
that the destination drive is encrypted (BitLocker status needs admin; FileVault and
LUKS are equally opaque unelevated). A "copy my secrets" path would therefore be an
unprotected copy wearing a warning label, and warning labels lose to convenience over
a long enough period.

So instead: every backup writes SECRETS-INVENTORY.json listing WHAT you hold - the
filenames, sizes, dates and the shape of each file - and never a single value. You
move the credentials yourself, by hand, once, using whatever you already trust
(password manager, encrypted volume, re-issuing them fresh). See "Moving your
credentials" in the /backup-brain documentation.

USAGE
-----
    python scripts/backup-brain.py                     # back up
    python scripts/backup-brain.py --dry-run           # show what would copy
    python scripts/backup-brain.py --status            # when did it last succeed?
    python scripts/backup-brain.py --restore           # restore onto this machine
    python scripts/backup-brain.py --restore --from /path/to/backup
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

MARKER = ".charon-backup-target"
BACKUP_DIRNAME = "Charon-Backup"
MANIFEST = "BACKUP-MANIFEST.json"

# Never copied. Keep this list in step with any new secret-bearing path.
EXCLUDE_NAMES = {
    ".credentials.json",
    "mcp-needs-auth-cache.json",
    "token-cache.json",
    "calendar-token-cache.json",
    ".env",
}
EXCLUDE_DIRS = {
    "node_modules", "__pycache__", ".git", ".venv", "venv",
    "cache", "paste-cache", "downloads", "shell-snapshots",
    "session-env", "daemon", ".pytest_cache",
}
EXCLUDE_SUFFIXES = {".key", ".pem", ".lock", ".pyc"}


# --------------------------------------------------------------------------- #
# paths
# --------------------------------------------------------------------------- #
def harness_root() -> Path:
    """Charon repo root (this file lives in <root>/scripts/)."""
    return Path(__file__).resolve().parent.parent


def claude_home() -> Path:
    return Path(os.environ.get("CLAUDE_HOME") or (Path.home() / ".claude"))


# NOTE on the env-var checks below: an explicitly-set env var is honoured even when
# the directory does not exist yet. That is the restore-onto-a-clean-machine case —
# the target legitimately has not been created. Requiring is_dir() here made both
# helpers silently fall through to their "guess" branch during a restore, which
# resolved capture-pipeline to Charon's OWN repo directory and would have written a
# restored brain over the installation. Caught by the round-trip test, 2026-08-17.
def vault_root() -> Path | None:
    """Vault path: HARNESS_VAULT / CLAUDE_PROJECT_DIR if declared, else None."""
    env = os.environ.get("HARNESS_VAULT") or os.environ.get("CLAUDE_PROJECT_DIR")
    if env:
        return Path(env)
    return None


def capture_pipeline() -> Path | None:
    """Pipeline dir: explicit env var wins, even if not yet created."""
    env = os.environ.get("HARNESS_CAPTURE_PIPELINE")
    if env:
        return Path(env)
    for cand in (harness_root() / "capture-pipeline", Path.home() / "capture-pipeline"):
        if cand.is_dir():
            return cand
    return None


def status_path() -> Path:
    return harness_root() / "state" / "last-brain-backup.json"


def candidate_volumes() -> list[Path]:
    """Plausible removable-volume roots for this OS."""
    system = platform.system()
    roots: list[Path] = []
    if system == "Windows":
        import string
        sysdrive = os.environ.get("SystemDrive", "C:").rstrip("\\")
        for letter in string.ascii_uppercase:
            drive = f"{letter}:"
            if drive.upper() == sysdrive.upper():
                continue
            p = Path(f"{drive}\\")
            try:
                if p.exists():
                    roots.append(p)
            except OSError:
                continue
    elif system == "Darwin":
        vols = Path("/Volumes")
        if vols.is_dir():
            roots.extend(c for c in vols.iterdir() if c.is_dir())
    else:  # Linux/BSD
        for base in (Path("/media") / os.environ.get("USER", ""), Path("/media"), Path("/mnt"), Path("/run/media")):
            if base.is_dir():
                for c in base.iterdir():
                    if c.is_dir():
                        roots.append(c)
                        # /media/<user>/<label> nesting
                        for sub in c.iterdir() if c.is_dir() else []:
                            if sub.is_dir():
                                roots.append(sub)
    return roots


CLOUD_MARKERS = {
    "onedrive": "OneDrive", "dropbox": "Dropbox", "icloud": "iCloud",
    "google drive": "Google Drive", "googledrive": "Google Drive",
    "box": "Box", "nextcloud": "Nextcloud", "syncthing": "Syncthing",
}


def detect_sync_provider(path: Path | None) -> str | None:
    """Best-effort guess at which cloud provider (if any) syncs `path`.

    Used only to make the restore prompt concrete ("looks like OneDrive") — the
    decision always stays with the user, because presence of a provider folder does
    not prove they still have ACCESS to the account behind it. That distinction is
    the whole point: someone who has left an employer still has the folder on disk.
    """
    if not path:
        return None
    lowered = str(path).lower()
    for needle, label in CLOUD_MARKERS.items():
        if needle in lowered:
            return f"looks like {label}"
    try:
        if (path / ".git").exists():
            return "git repo"
    except OSError:
        pass
    return None


def find_target() -> Path | None:
    for root in candidate_volumes():
        try:
            if (root / MARKER).exists():
                return root
        except OSError:
            continue
    return None


# --------------------------------------------------------------------------- #
# copy engine
# --------------------------------------------------------------------------- #
def excluded(path: Path) -> bool:
    if path.name in EXCLUDE_NAMES:
        return True
    if path.suffix in EXCLUDE_SUFFIXES:
        return True
    return any(part in EXCLUDE_DIRS for part in path.parts)


def copy_tree(src: Path, dst: Path, dry_run: bool) -> tuple[int, int]:
    """Copy src->dst honouring exclusions. Returns (files, bytes)."""
    files = total = 0
    for item in src.rglob("*"):
        if not item.is_file():
            continue
        rel = item.relative_to(src)
        if excluded(rel) or excluded(item):
            continue
        target = dst / rel
        try:
            size = item.stat().st_size
        except OSError:
            continue
        # Skip unchanged files so repeat runs over USB stay quick.
        if target.exists():
            try:
                if target.stat().st_mtime >= item.stat().st_mtime and target.stat().st_size == size:
                    continue
            except OSError:
                pass
        files += 1
        total += size
        if dry_run:
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
        except OSError as exc:
            print(f"  WARN could not copy {rel}: {exc}", file=sys.stderr)
    return files, total


def save_status(result: str, target, files: int, mb: float, note: str) -> None:
    """Persist run status. last_success survives failed/skipped attempts."""
    prev_success = None
    sp = status_path()
    if sp.exists():
        try:
            prev_success = json.loads(sp.read_text(encoding="utf-8")).get("last_success")
        except (OSError, ValueError):
            pass
    now = datetime.now(timezone.utc).isoformat()
    payload = {
        "last_attempt": now,
        "last_attempt_result": result,
        "last_success": now if result == "success" else prev_success,
        "target": str(target) if target else None,
        "files_copied": files,
        "megabytes_copied": round(mb, 1),
        "note": note,
    }
    try:
        sp.parent.mkdir(parents=True, exist_ok=True)
        sp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError as exc:
        print(f"WARN could not write status file: {exc}", file=sys.stderr)


def secrets_dir() -> Path:
    env = os.environ.get("HARNESS_SECRETS")
    return Path(env) if env else (Path.home() / ".secrets")


def write_secrets_inventory(dest: Path) -> int:
    """Record WHAT credentials exist, never their values.

    This is the default answer to "how do I move my secrets?" - and for most people it
    is the RIGHT answer. Credentials should be re-issued on a new machine, not ferried
    around on removable media. But "just re-authenticate" is useless if you cannot
    remember what you had, so we back up the inventory: filename, size, when it last
    changed, and where it came from if the file records that.

    Values are never read. Only os.stat() metadata and, where a JSON file exposes an
    obvious non-secret hint key, that hint.
    """
    src = secrets_dir()
    if not src.is_dir():
        return 0
    entries = []
    for f in sorted(src.rglob("*")):
        if not f.is_file():
            continue
        try:
            st = f.stat()
        except OSError:
            continue
        hint = None
        # Only ever surface obviously-non-secret descriptive keys.
        if f.suffix.lower() == ".json":
            try:
                data = json.loads(f.read_text(encoding="utf-8-sig"))
                if isinstance(data, dict):
                    for k in ("_comment", "comment", "description", "purpose", "issuer", "tenant", "account"):
                        if isinstance(data.get(k), str):
                            hint = data[k][:160]
                            break
                    if hint is None:
                        hint = "keys: " + ", ".join(sorted(data.keys())[:12])
            except (OSError, ValueError):
                pass
        entries.append({
            "file": str(f.relative_to(src)).replace("\\", "/"),
            "bytes": st.st_size,
            "modified": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc).isoformat(),
            "hint": hint,
        })
    payload = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "source": str(src),
        "WARNING": "INVENTORY ONLY - no credential values are recorded here, by design.",
        "how_to_restore": "Re-issue each credential on the new machine and recreate the file. "
                          "The 'hint' field shows the shape of each file, not its contents.",
        "count": len(entries),
        "entries": entries,
    }
    try:
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "SECRETS-INVENTORY.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    except OSError as exc:
        print(f"  WARN could not write secrets inventory: {exc}", file=sys.stderr)
        return 0
    return len(entries)


def jobs_for_backup(args) -> list[tuple[str, Path]]:
    """What gets copied. Note what is ABSENT: the secrets directory.

    There is deliberately no --include-secrets option. This tool cannot encrypt, and
    as a normal-user process it cannot verify the destination drive is encrypted, so
    any "copy my credentials" path would be an unguarded one wearing a warning label.
    Rather than guard a dangerous capability, we do not ship it. Users move credentials
    by hand, deliberately, once - see the "Moving your credentials" section of the
    /backup-brain docs. The inventory below tells them exactly what to move.
    """
    out: list[tuple[str, Path]] = [("claude", claude_home())]
    cp = capture_pipeline()
    if cp:
        out.append(("capture-pipeline", cp))
    if args.vault_backup != "no":
        v = vault_root()
        if v:
            out.append(("vault", v))
    return [(n, p) for n, p in out if p and p.is_dir()]


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #
def do_backup(args) -> int:
    target = Path(args.to) if args.to else find_target()
    if not target:
        print(f"No backup drive found (no volume carries '{MARKER}').")
        print("This is expected when the drive is stored away. Recording the skip so")
        print("an overdue backup is still visible to liveness checks.")
        save_status("drive-absent", None, 0, 0, f"no volume carried '{MARKER}'")
        return 0

    dest = target / BACKUP_DIRNAME
    print(f"Backup target: {dest}")

    files = total = 0
    for name, src in jobs_for_backup(args):
        print(f"  {name:18} {src}")
        f, b = copy_tree(src, dest / name, args.dry_run)
        files += f
        total += b
    mb = total / (1024 * 1024)

    if args.dry_run:
        print(f"DRY RUN - would copy {files} file(s), {mb:.1f} MB. Nothing written.")
        save_status("dry-run", target, files, mb, "dry run")
        return 0

    # Always record WHAT credentials exist, even (especially) when values are excluded.
    inv = write_secrets_inventory(dest)
    if inv:
        print(f"  secrets inventory: {inv} credential file(s) listed (no values recorded)")

    try:
        (dest / MANIFEST).write_text(json.dumps({
            "created": datetime.now(timezone.utc).isoformat(),
            "machine": platform.node(),
            "os": platform.platform(),
            "files": files,
            "megabytes": round(mb, 1),
            "contents": [n for n, _ in jobs_for_backup(args)],
            "secrets_values_included": False,  # never - by design, see jobs_for_backup()
            "secrets_inventory_entries": inv,
            "excluded_note": "credentials, keys, token caches and node_modules are deliberately NOT backed up",
            "restore": "python scripts/backup-brain.py --restore",
        }, indent=2), encoding="utf-8")
    except OSError as exc:
        print(f"WARN could not write manifest: {exc}", file=sys.stderr)

    print(f"Backup complete: {files} file(s), {mb:.1f} MB -> {dest}")
    save_status("success", target, files, mb, "ok")
    return 0


def do_restore(args) -> int:
    src_root = Path(args.source) if args.source else None
    if src_root is None:
        t = find_target()
        src_root = (t / BACKUP_DIRNAME) if t else None
    if not src_root or not src_root.is_dir():
        print("No backup found. Plug in the backup drive, or pass --from <path>.")
        return 1

    manifest = src_root / MANIFEST
    if manifest.exists():
        try:
            m = json.loads(manifest.read_text(encoding="utf-8"))
            print(f"Backup created {m.get('created')} on {m.get('machine')}")
            print(f"  {m.get('files')} files, {m.get('megabytes')} MB")
            print(f"  contents: {', '.join(m.get('contents', []))}")
        except (OSError, ValueError):
            print("(manifest unreadable - continuing)")
    else:
        print("WARNING: no manifest found; this may not be a Charon backup.")

    targets = {
        "claude": claude_home(),
        "capture-pipeline": capture_pipeline() or (Path.home() / "capture-pipeline"),
        "vault": vault_root(),
        "secrets": Path.home() / ".secrets",
    }

    # --- vault: ask before restoring over a cloud-synced copy -------------------
    # The vault is usually the one half that IS synced (OneDrive/Dropbox/iCloud/git).
    # If the user still has access to that sync, the notes will arrive on their own and
    # restoring on top risks sync conflicts and duplicate files. If they have LOST access
    # (left the employer, new tenant, dead account) the backup is the only copy and must
    # be restored. Only the user knows which - so ask, with a sensible detected default.
    if (src_root / "vault").is_dir() and not args.vault_decision:
        vdst = targets.get("vault")
        detected = detect_sync_provider(vdst)
        if vdst and vdst.is_dir() and any(vdst.iterdir()):
            where = f" ({detected})" if detected else ""
            print(f"\nA vault already exists at {vdst}{where} and has content.")
            print("If it is syncing from cloud storage you still have access to, you do")
            print("NOT want to restore over it - the notes will arrive on their own, and")
            print("restoring on top can create sync conflicts and duplicates.")
            args.vault_decision = "skip" if args.yes else None
            if args.vault_decision is None:
                try:
                    ans = input("Do you still have access to that cloud sync? [Y/n] ").strip().lower()
                except EOFError:
                    ans = "y"
                args.vault_decision = "skip" if ans in ("", "y", "yes") else "restore"
        else:
            print("\nNo synced vault found on this machine - the backup copy will be restored.")
            args.vault_decision = "restore"
        if args.vault_decision == "skip":
            print("  -> skipping vault restore; letting cloud sync bring the notes back.")
            targets.pop("vault", None)

    planned = []
    for name, dst in targets.items():
        s = src_root / name
        if not s.is_dir() or dst is None:
            continue
        occupied = dst.exists() and any(dst.iterdir())
        planned.append((name, s, dst, occupied))

    if not planned:
        print("Nothing in the backup maps to a restore target on this machine.")
        return 1

    print("\nRestore plan:")
    for name, _s, dst, occupied in planned:
        flag = "  [EXISTS - will merge]" if occupied else ""
        print(f"  {name:18} -> {dst}{flag}")

    if any(o for *_x, o in planned) and not args.force:
        print("\nOne or more targets already contain data.")
        print("Re-run with --force to merge the backup over them (newer files win).")
        return 2

    if not args.yes:
        try:
            if input("\nProceed with restore? [y/N] ").strip().lower() not in ("y", "yes"):
                print("Aborted.")
                return 1
        except EOFError:
            print("Non-interactive and --yes not given; aborting.")
            return 1

    files = 0
    for name, s, dst, _o in planned:
        print(f"  restoring {name} -> {dst}")
        f, _b = copy_tree(s, dst, dry_run=False)
        files += f

    print(f"\nRestore complete: {files} file(s).")
    print("\nNEXT STEPS - credentials were deliberately NOT restored:")
    print("  * Re-authenticate the capture pipeline (see EMAIL-PROVIDER-SETUP.md)")
    print("  * Re-create any API keys in your secrets directory")
    print("  * Run: python scripts/first-run.py --scaffold-only   (ensure folder skeleton)")
    return 0


def do_status(_args) -> int:
    sp = status_path()
    if not sp.exists():
        print("No backup has ever run (no status file).")
        return 1
    try:
        d = json.loads(sp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        print("Status file unreadable.")
        return 1
    last = d.get("last_success")
    print(f"last attempt : {d.get('last_attempt')} ({d.get('last_attempt_result')})")
    print(f"last SUCCESS : {last or 'never'}")
    if last:
        try:
            days = (datetime.now(timezone.utc) - datetime.fromisoformat(last)).days
            print(f"             : {days} day(s) ago")
        except ValueError:
            pass
    print(f"target       : {d.get('target')}")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description="Offline backup/restore for a Charon brain.")
    p.add_argument("--restore", action="store_true", help="restore from a backup")
    p.add_argument("--from", dest="source", help="explicit backup folder to restore from")
    p.add_argument("--to", help="explicit volume root to back up to")
    p.add_argument("--status", action="store_true", help="report last successful backup")
    p.add_argument("--dry-run", action="store_true", help="show what would copy")
    p.add_argument("--vault", dest="vault_backup", choices=["yes", "no"], default="yes",
                   help="on backup: include the vault (default: yes, when a vault path "
                        "is known). Use --vault no if it is already reliably synced.")
    p.add_argument("--force", action="store_true", help="restore over non-empty targets")
    p.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    p.add_argument("--restore-vault", dest="vault_decision", choices=["restore", "skip"],
                   help="on restore: force restoring the vault, or skip it because "
                        "cloud sync will bring it back (default: ask)")
    args = p.parse_args()

    if args.status:
        return do_status(args)
    if args.restore:
        return do_restore(args)
    return do_backup(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nInterrupted.")
        sys.exit(130)
