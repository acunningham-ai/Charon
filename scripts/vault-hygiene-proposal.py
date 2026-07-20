#!/usr/bin/env python
"""vault-hygiene-proposal.py — Phase 3 of the self-improving vault-hygiene loop.

The PROPOSE step. Turns a recurring, deterministically-detected finding-class
(from `vault-hygiene-recurrence.py`) into a tracked *structural prevention*
proposal — a plain-English CHANGE plus the BENEFIT it buys — and captures the
class's BASELINE recurrence at the moment the proposal is opened.

Design guarantees (this is the highest-blast-radius capability in the harness —
the discipline is the point):
  - OBSERVE / PROPOSE ONLY. This script NEVER edits the vault, never applies a
    fix, never runs a remediation. It is a ledger + baseline recorder.
  - HUMAN-GATED. The CHANGE and BENEFIT text are SUPPLIED (by a human, or by a
    model drafting via /harness-improve) — the script does not invent them. A
    human opens, a human applies. No model judgement is stored as fact here.
  - CLEAN SIGNAL. The baseline it records is copied verbatim from the
    deterministic recurrence analysis (score-vault → ledger → recurrence). The
    loop later LEARNS only from whether that baseline FELL after a fix
    (`vault-hygiene-postcheck.py`) — never from a model's say-so. No autophagy.
    Clean-signal gate: the loop learns only from the deterministic ledger.

Proposal ledger: state/vault-hygiene/proposals.jsonl (one JSON record per
proposal; small, rewritten atomically on status change).

Usage:
  python vault-hygiene-proposal.py --targets
      list the recurring classes worth a structural fix (persistent / rising /
      reappeared), i.e. the legitimate inputs to a proposal.
  python vault-hygiene-proposal.py --open --kind category --key memory-index \
      --change "..." --benefit "..."
      open a proposal against a recurring class, capturing its baseline now.
  python vault-hygiene-proposal.py --apply <id> [--date YYYY-MM-DD]
      record that YOU applied the structural fix on that date (no vault change).
  python vault-hygiene-proposal.py --list
      show all proposals and their status.

Exit code is always 0 — this is bookkeeping, not a gate.
"""
import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))
from lib.harness_paths import vault_root  # noqa: E402

RECURRENCE_SCRIPT = THIS_DIR / "vault-hygiene-recurrence.py"
PROPOSALS_PATH = vault_root() / "state" / "vault-hygiene" / "proposals.jsonl"

VALID_KINDS = ("category", "finding")


# --- recurrence analysis (deterministic signal source) ----------------

def run_recurrence() -> dict:
    """Run the deterministic recurrence detector and return its analysis.
    Subprocess (not import) because the sibling script's name isn't importable,
    and this keeps the single source of truth for the analysis."""
    try:
        r = subprocess.run(
            [sys.executable, str(RECURRENCE_SCRIPT), "--json"],
            capture_output=True, encoding="utf-8", errors="replace", timeout=120,
        )
        return json.loads(r.stdout) if r.stdout.strip() else {}
    except Exception as e:
        print(f"could not read recurrence analysis: {type(e).__name__}: {e}")
        return {}


def finding_key(category: str, file, message: str) -> str:
    """Stable identity for a specific finding, matching the recurrence detector's
    (category, file, digit-normalised message) identity so a proposal tracks the
    same finding across runs even as embedded counts drift."""
    import re
    norm = re.sub(r"\d+", "#", message or "")
    return f"{category}::{file or '—'}::{norm}"


def qualifying_targets(analysis: dict) -> dict:
    """The legitimate inputs to a structural-prevention proposal: recurring
    classes that PERSIST, are RISING, or REAPPEARED — the signals that a one-off
    fix won't hold and a structural change is warranted."""
    cats = []
    for name, v in (analysis.get("categories") or {}).items():
        if not v.get("recurring"):
            continue
        if v.get("persistent") or v.get("reappeared") or v.get("trend") == "rising":
            cats.append({
                "kind": "category", "key": name,
                "runs_seen": v.get("runs_seen"), "prevalence": v.get("prevalence"),
                "current_count": v.get("current_count"), "trend": v.get("trend"),
                "persistent": v.get("persistent"), "reappeared": v.get("reappeared"),
            })
    finds = []
    for f in analysis.get("recurring_findings") or []:
        finds.append({
            "kind": "finding",
            "key": finding_key(f.get("category", "?"), f.get("file"), f.get("message", "")),
            "category": f.get("category"), "file": f.get("file"),
            "message": f.get("message"), "runs_seen": f.get("runs_seen"),
            "reappeared": f.get("reappeared_after_absence"),
        })
    return {"categories": cats, "findings": finds}


def baseline_for(analysis: dict, kind: str, key: str):
    """Copy the target's CURRENT deterministic recurrence stats verbatim — this
    is the yardstick the post-check measures the applied fix against."""
    if kind == "category":
        v = (analysis.get("categories") or {}).get(key)
        if not v:
            return None
        return {k: v.get(k) for k in
                ("runs_seen", "prevalence", "current_count", "trend", "persistent", "reappeared")}
    for f in analysis.get("recurring_findings") or []:
        if finding_key(f.get("category", "?"), f.get("file"), f.get("message", "")) == key:
            return {"runs_seen": f.get("runs_seen"), "current_count": f.get("current_count", 1),
                    "reappeared": f.get("reappeared_after_absence"),
                    "category": f.get("category"), "file": f.get("file")}
    return None


# --- proposal ledger ---------------------------------------------------

def load_proposals() -> list:
    if not PROPOSALS_PATH.exists():
        return []
    out = []
    for line in PROPOSALS_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def save_proposals(proposals: list) -> None:
    PROPOSALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PROPOSALS_PATH.with_suffix(".jsonl.tmp")
    tmp.write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in proposals),
                   encoding="utf-8")
    tmp.replace(PROPOSALS_PATH)  # atomic


def make_id(kind: str, key: str, opened: str) -> str:
    h = hashlib.sha1(f"{kind}:{key}:{opened}".encode("utf-8")).hexdigest()[:6]
    return f"vh-{opened[:10]}-{h}"


# --- commands ----------------------------------------------------------

def cmd_targets():
    t = qualifying_targets(run_recurrence())
    print("# Recurring classes worth a structural fix (proposal inputs)\n")
    print(f"## Categories ({len(t['categories'])})")
    for c in t["categories"]:
        flags = ",".join(x for x in (
            "persistent" if c["persistent"] else "",
            "reappeared" if c["reappeared"] else "",
            "rising" if c["trend"] == "rising" else "") if x)
        print(f"  [{c['key']}] seen {c['runs_seen']}x · now {c['current_count']} · {flags}")
    print(f"\n## Specific findings ({len(t['findings'])})")
    for f in t["findings"]:
        tag = "reappeared" if f["reappeared"] else f"seen {f['runs_seen']}x"
        print(f"  [{f['category']}] {f['file']} · {tag}")
        print(f"      key: {f['key']}")
    print("\nOpen one with:  --open --kind <category|finding> --key <key> "
          "--change \"...\" --benefit \"...\"")


def cmd_open(args):
    if args.kind not in VALID_KINDS:
        print(f"--kind must be one of {VALID_KINDS}")
        return
    if not (args.change and args.benefit):
        print("both --change and --benefit are required (human/model supplies them; "
              "this script does not invent the fix)")
        return
    analysis = run_recurrence()
    baseline = baseline_for(analysis, args.kind, args.key)
    if baseline is None:
        print(f"no CURRENT recurring target matches kind={args.kind} key={args.key!r}. "
              f"Run --targets to see valid keys. (A class that isn't currently recurring "
              f"isn't a legitimate proposal input.)")
        return
    opened = datetime.now(timezone.utc).isoformat(timespec="seconds")
    pid = make_id(args.kind, args.key, opened)
    proposals = load_proposals()
    if any(p["id"] == pid for p in proposals):
        print(f"proposal {pid} already exists for this target today.")
        return
    proposals.append({
        "id": pid,
        "opened_utc": opened,
        "status": "proposed",
        "target_kind": args.kind,
        "target_key": args.key,
        "baseline": baseline,          # verbatim deterministic stats at open time
        "change": args.change,         # supplied — the structural prevention, plain English
        "benefit": args.benefit,       # supplied — what it buys
        "applied_date": None,          # set by --apply when the human applies the fix
        "notes": args.notes or "",
    })
    save_proposals(proposals)
    print(f"opened {pid}  [{args.kind}:{args.key}]  status=proposed")
    print(f"  baseline: {baseline}")
    print(f"  change:   {args.change}")
    print(f"  benefit:  {args.benefit}")
    print("  (nothing applied — this is a proposal. Apply the fix yourself, then "
          "record it with --apply.)")


def cmd_apply(args):
    # Validate the date FIRST, before any lookup — a malformed apply-date would silently
    # poison the post-check's before/after split and corrupt the learning signal, the one
    # thing this loop can't get wrong. Local date is intentional (matches the ledger's
    # local-date snapshots).
    if args.date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.date):
        print(f"--date must be YYYY-MM-DD (got {args.date!r}); refusing.")
        return
    proposals = load_proposals()
    p = next((x for x in proposals if x["id"] == args.id), None)
    if p is None:
        print(f"no proposal with id {args.id}. --list to see them.")
        return
    date = args.date or datetime.now().strftime("%Y-%m-%d")
    p["status"] = "applied"
    p["applied_date"] = date
    save_proposals(proposals)
    print(f"{args.id} marked applied on {date}. The post-check "
          f"(vault-hygiene-postcheck.py) will measure whether the recurrence actually "
          f"falls after this date — deterministically, no model self-assessment.")


def cmd_list():
    proposals = load_proposals()
    if not proposals:
        print("no proposals yet. --targets to see what's worth proposing.")
        return
    print(f"# Vault-hygiene proposals ({len(proposals)})\n")
    for p in proposals:
        applied = f" · applied {p['applied_date']}" if p.get("applied_date") else ""
        print(f"[{p['id']}] {p['status']}{applied}  ({p['target_kind']}:{p['target_key']})")
        print(f"    change:  {p['change']}")
        print(f"    benefit: {p['benefit']}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--targets", action="store_true", help="list recurring classes worth a structural fix")
    ap.add_argument("--open", action="store_true", help="open a proposal against a recurring target")
    ap.add_argument("--apply", metavar="ID", help="record that you applied a proposal's fix")
    ap.add_argument("--list", action="store_true", help="list all proposals")
    ap.add_argument("--kind", help="category | finding (with --open)")
    ap.add_argument("--key", help="target key from --targets (with --open)")
    ap.add_argument("--change", help="the structural prevention, plain English (with --open)")
    ap.add_argument("--benefit", help="what the change buys (with --open)")
    ap.add_argument("--date", help="apply date YYYY-MM-DD (with --apply; default today local)")
    ap.add_argument("--notes", help="optional note (with --open)")
    args = ap.parse_args()

    if args.open:
        cmd_open(args)
    elif args.apply:
        args.id = args.apply
        cmd_apply(args)
    elif args.list:
        cmd_list()
    else:
        cmd_targets()  # default: show what's worth proposing
    return 0


if __name__ == "__main__":
    sys.exit(main())
