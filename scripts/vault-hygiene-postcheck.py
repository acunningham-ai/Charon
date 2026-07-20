#!/usr/bin/env python
"""vault-hygiene-postcheck.py — Phase 4 of the self-improving vault-hygiene loop.

The KEYSTONE. For every proposal marked APPLIED (in vault-hygiene-proposal.py),
it asks the only question that matters — *did it actually work?* — and answers it
DETERMINISTICALLY, from the ledger's own counts, with ZERO model self-assessment:

    after you applied the structural fix on date D, did that finding-class's
    recurrence actually FALL in the ledger snapshots dated >= D?

This is the whole thesis of the loop made mechanical. The loop is only ever
allowed to believe a change helped because a deterministic signal (score-vault →
ledger) says the recurrence dropped — never because a model graded its own work.
If the recurrence didn't fall, this says so plainly. A fix that didn't hold is a
result, not a failure to hide — a control that's present is not a control that's
working. Clean-signal gate: only the deterministic ledger concludes "it worked".

Read-only by default. `--record` writes each verdict back onto the proposal
(status + measured outcome + checked date) so the proposal→outcome history — the
substrate the loop actually LEARNS from — accretes over time.

Verdicts (per applied proposal):
  resolved   — class is gone after the fix (mean count after == 0)
  improved   — recurrence meaningfully lower after than before
  no_change  — indistinguishable before/after (the fix didn't hold)
  worse      — recurrence higher after (the fix backfired)
  pending    — not enough post-apply snapshots yet to judge

Usage:
  python vault-hygiene-postcheck.py            # markdown report on applied proposals
  python vault-hygiene-postcheck.py --json
  python vault-hygiene-postcheck.py --record   # also write verdicts back to the ledger
  python vault-hygiene-postcheck.py --ledger PATH --proposals PATH   # testing

Exit code is always 0 — measurement is information, not a gate.
"""
import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(THIS_DIR))
from lib.harness_paths import vault_root  # noqa: E402

_VH = vault_root() / "state" / "vault-hygiene"
DEFAULT_LEDGER = _VH / "ledger.jsonl"
DEFAULT_PROPOSALS = _VH / "proposals.jsonl"
_DIGITS_RE = re.compile(r"\d+")

MIN_AFTER_SNAPSHOTS = 3   # need at least this many snapshots on/after apply-date to judge
IMPROVE_MARGIN = 0.70     # mean_after < margin * mean_before counts as "improved"


def load_jsonl(path: Path) -> list:
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def _norm(msg: str) -> str:
    return _DIGITS_RE.sub("#", msg or "")


def category_count(snapshot: dict, category: str) -> int:
    """Deterministic count of a category in one snapshot: prefer the stored
    category_counts, else derive from the findings list."""
    counts = snapshot.get("category_counts")
    if isinstance(counts, dict) and category in counts:
        return int(counts[category])
    return sum(1 for f in snapshot.get("findings", []) if f.get("category") == category)


def finding_present(snapshot: dict, target_key: str) -> bool:
    """Is the specific finding (category::file::digit-normalised-message) present
    in this snapshot? Matches the proposal/recurrence identity."""
    for f in snapshot.get("findings", []):
        key = f"{f.get('category', '?')}::{f.get('file') or '—'}::{_norm(f.get('message', ''))}"
        if key == target_key:
            return True
    return False


def series_for(snapshots: list, kind: str, key: str):
    """(date, value) per snapshot. value = category count (int) or finding-present (0/1)."""
    out = []
    for s in snapshots:
        d = s.get("date", "")
        if not d:
            continue
        if kind == "category":
            out.append((d, category_count(s, key)))
        else:
            out.append((d, 1 if finding_present(s, key) else 0))
    out.sort(key=lambda x: x[0])
    return out


def judge(series, apply_date: str) -> dict:
    """Deterministic before/after comparison split on the apply-date."""
    before = [v for (d, v) in series if d < apply_date]
    after = [v for (d, v) in series if d >= apply_date]
    n_before, n_after = len(before), len(after)
    if n_after < MIN_AFTER_SNAPSHOTS:
        return {"verdict": "pending", "n_before": n_before, "n_after": n_after,
                "need_after": MIN_AFTER_SNAPSHOTS}
    mean_before = sum(before) / n_before if n_before else None
    mean_after = sum(after) / n_after
    if mean_after == 0:
        verdict = "resolved"
    elif mean_before is None:
        verdict = "no_change"  # nothing to compare against — can't claim improvement
    elif mean_after > mean_before:
        verdict = "worse"
    elif mean_after < IMPROVE_MARGIN * mean_before:
        verdict = "improved"
    else:
        verdict = "no_change"
    return {"verdict": verdict,
            "mean_before": round(mean_before, 3) if mean_before is not None else None,
            "mean_after": round(mean_after, 3),
            "n_before": n_before, "n_after": n_after}


VERDICT_PLAIN = {
    "resolved": "gone since the fix — the class stopped recurring",
    "improved": "recurrence is meaningfully lower since the fix",
    "no_change": "no measurable change — the fix didn't hold",
    "worse": "recurrence is HIGHER since the fix — it backfired",
    "pending": "not enough snapshots since the fix to judge yet",
}


def evaluate(proposals: list, snapshots: list) -> list:
    results = []
    for p in proposals:
        if p.get("status") != "applied" or not p.get("applied_date"):
            continue
        series = series_for(snapshots, p["target_kind"], p["target_key"])
        outcome = judge(series, p["applied_date"])
        results.append({
            "id": p["id"], "target_kind": p["target_kind"], "target_key": p["target_key"],
            "applied_date": p["applied_date"], "change": p.get("change", ""),
            **outcome, "plain": VERDICT_PLAIN.get(outcome["verdict"], ""),
        })
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--record", action="store_true",
                    help="write verdicts back onto the proposals (builds the learning history)")
    ap.add_argument("--ledger", default=str(DEFAULT_LEDGER))
    ap.add_argument("--proposals", default=str(DEFAULT_PROPOSALS))
    args = ap.parse_args()

    snapshots = load_jsonl(Path(args.ledger))
    snapshots.sort(key=lambda s: s.get("date", ""))
    proposals = load_jsonl(Path(args.proposals))
    results = evaluate(proposals, snapshots)

    if args.record and results:
        # Scope guard: --record MUTATES the proposals ledger, so fence the write to the
        # vault-hygiene state dir — a stray --proposals must never overwrite an
        # authoritative file. The read-only path stays open for testing. (secure-code 2026-07-20)
        prop_path = Path(args.proposals).resolve()
        try:
            in_scope = prop_path.is_relative_to(_VH.resolve())
        except Exception:
            in_scope = False
        if not in_scope:
            print(f"refusing --record: {prop_path} is outside {_VH}. The record path is fenced "
                  f"to the vault-hygiene state dir so a mistyped --proposals can't clobber "
                  f"MEMORY.md or any authoritative file.")
            return 0
        by_id = {r["id"]: r for r in results}
        checked = datetime.now().strftime("%Y-%m-%d")
        for p in proposals:
            r = by_id.get(p["id"])
            if r and r["verdict"] != "pending":
                entry = {"verdict": r["verdict"], "mean_before": r.get("mean_before"),
                         "mean_after": r.get("mean_after"), "checked_date": checked}
                # Append-only history: the learning substrate must never lose a prior verdict
                # if later snapshots shift the ratio. Append only on a verdict change so
                # re-runs don't bloat. (secure-code 2026-07-20)
                hist = p.get("outcome_history") or []
                if not hist or hist[-1].get("verdict") != entry["verdict"]:
                    hist.append(entry)
                p["outcome_history"] = hist
                p["outcome"] = entry  # latest, for convenience
                p["status"] = {"resolved": "resolved", "improved": "improved",
                               "no_change": "ineffective", "worse": "ineffective"}.get(r["verdict"], p["status"])
        tmp = prop_path.with_suffix(".jsonl.tmp")
        tmp.write_text("".join(json.dumps(p, ensure_ascii=False) + "\n" for p in proposals), encoding="utf-8")
        tmp.replace(prop_path)

    if args.json:
        print(json.dumps({"applied_evaluated": len(results), "results": results}, indent=2))
        return 0

    print("# Vault-hygiene post-check — did the applied fixes actually work?\n")
    if not results:
        print("No applied proposals to check yet. Open one with vault-hygiene-proposal.py, "
              "apply the fix, mark it --apply, and let a few days of snapshots accrue.")
        return 0
    for r in results:
        nums = (f"before {r['mean_before']} → after {r['mean_after']} "
                f"({r['n_before']} vs {r['n_after']} snapshots)"
                if r["verdict"] != "pending"
                else f"{r['n_after']}/{r['need_after']} post-fix snapshots so far")
        print(f"[{r['id']}] {r['verdict'].upper()} — {r['plain']}")
        print(f"    {r['target_kind']}:{r['target_key']}")
        print(f"    applied {r['applied_date']} · {nums}")
        print(f"    fix: {r['change']}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
