#!/usr/bin/env python
"""vault-hygiene-recurrence.py — deterministic recurrence detector.

Phase 2 of the self-improving vault-hygiene prototype (roadmap §B). Reads the
drift ledger written by `vault-hygiene-ledger.py` and derives, deterministically,
which finding-categories and specific findings RECUR over time. This derived
model is what the Phase 3 proposal layer reasons over and the Phase 4 post-check
measures against.

DETERMINISTIC. No LLM call, read-only. Everything it reports is computed from the
ledger's deterministic history — nothing here is model-generated (clean-signal
gate: no autophagy).

Two recurrence signals (they mean different things):
  - PERSISTENT  — present across many runs = never resolved.
  - REAPPEARED  — present, then ABSENT in a later run, then present again =
                  fixed-then-returned. The strongest signal that a one-off fix
                  is not enough and a STRUCTURAL prevention is warranted.

Finding identity = (category, file, digit-normalised message), so a finding
whose message embeds a volatile count (e.g. "1233 captures" -> "1240 captures")
is recognised as the SAME finding across runs rather than a new one each time.

Usage:
  python vault-hygiene-recurrence.py                 # markdown report on the real ledger
  python vault-hygiene-recurrence.py --json          # machine-readable
  python vault-hygiene-recurrence.py --ledger PATH   # analyse a specific ledger (testing)
  python vault-hygiene-recurrence.py --threshold N   # runs-seen bar for "recurring" (default 3)

Exit code is always 0 — analysis is information, not failure.
"""
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.harness_paths import vault_root  # noqa: E402

DEFAULT_LEDGER = vault_root() / "state" / "vault-hygiene" / "ledger.jsonl"
DEFAULT_THRESHOLD = 3  # a category/finding is "recurring" at >= this many runs seen
_DIGITS_RE = re.compile(r"\d+")


def load_snapshots(ledger_path):
    if not ledger_path.exists():
        return []
    snapshots = []
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            snapshots.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    # Ledger is append-only and written in chronological order; sort by date
    # defensively so analysis never depends on write order.
    snapshots.sort(key=lambda s: s.get("date", ""))
    return snapshots


def finding_key(f):
    cat = f.get("category", "?")
    file = f.get("file") or "—"
    msg = _DIGITS_RE.sub("#", f.get("message", ""))
    return (cat, file, msg)


def _trend(series):
    """series: list of (date, count). Returns rising/falling/flat over the span."""
    counts = [c for _, c in series]
    if len(counts) < 2 or counts[0] == counts[-1]:
        return "flat"
    return "rising" if counts[-1] > counts[0] else "falling"


def _reappeared(present_flags):
    """present_flags: list of bool, one per run in chronological order, from the
    first run the item was seen onward. True if there was an absence (False)
    followed later by a presence (True) — i.e. it came back after being gone."""
    seen_absence_after_presence = False
    been_present = False
    for present in present_flags:
        if present and been_present and seen_absence_after_presence:
            return True
        if present:
            been_present = True
        elif been_present:
            seen_absence_after_presence = True
    return False


def analyze(snapshots, threshold=DEFAULT_THRESHOLD):
    total_runs = len(snapshots)
    dates = [s.get("date", "?") for s in snapshots]

    # --- per-category time series ---
    cat_series = defaultdict(dict)  # category -> {date: count}
    for s in snapshots:
        counts = s.get("category_counts") or {}
        # fall back to deriving from findings if category_counts absent
        if not counts and s.get("findings"):
            tmp = defaultdict(int)
            for f in s["findings"]:
                tmp[f.get("category", "?")] += 1
            counts = dict(tmp)
        for cat, n in counts.items():
            cat_series[cat][s.get("date", "?")] = n

    categories = {}
    for cat, by_date in cat_series.items():
        series = [(d, by_date.get(d, 0)) for d in dates]
        present_flags = [by_date.get(d, 0) > 0 for d in dates]
        runs_seen = sum(1 for p in present_flags if p)
        seen_dates = [d for d, p in zip(dates, present_flags) if p]
        first_seen, last_seen = seen_dates[0], seen_dates[-1]
        # persistent = present in every run from first appearance to the end.
        idx_first = dates.index(first_seen)
        persistent = all(present_flags[idx_first:])
        reappeared = _reappeared(present_flags)
        categories[cat] = {
            "runs_seen": runs_seen,
            "prevalence": round(runs_seen / total_runs, 3) if total_runs else 0,
            "first_seen": first_seen,
            "last_seen": last_seen,
            "current_count": series[-1][1],
            "count_series": [[d, c] for d, c in series],
            "persistent": persistent,
            "reappeared": reappeared,
            "trend": _trend(series),
            "recurring": runs_seen >= threshold or reappeared,
        }

    # --- per-finding recurrence (file-level granularity) ---
    finding_runs = defaultdict(list)   # key -> list of bool present-per-run
    finding_meta = {}                  # key -> {category,file,latest message,dates seen}
    for s in snapshots:
        present_keys = set()
        for f in s.get("findings", []):
            k = finding_key(f)
            present_keys.add(k)
            finding_meta[k] = {
                "category": f.get("category", "?"),
                "file": f.get("file"),
                "message": f.get("message", ""),  # latest raw message wins
            }
        for k in set(list(finding_runs.keys()) + list(present_keys)):
            finding_runs[k].append(k in present_keys)

    recurring_findings = []
    for k, flags in finding_runs.items():
        runs_seen = sum(1 for p in flags if p)
        reappeared = _reappeared(flags)
        if runs_seen >= threshold or reappeared:
            seen_dates = [d for d, p in zip(dates, flags) if p]
            meta = finding_meta[k]
            recurring_findings.append({
                "category": meta["category"],
                "file": meta["file"],
                "message": meta["message"],
                "runs_seen": runs_seen,
                "first_seen": seen_dates[0],
                "last_seen": seen_dates[-1],
                "reappeared_after_absence": reappeared,
            })
    recurring_findings.sort(key=lambda r: (-r["runs_seen"], r["category"], r["file"] or ""))

    return {
        "total_runs": total_runs,
        "date_range": [dates[0], dates[-1]] if dates else [],
        "threshold": threshold,
        "categories": categories,
        "recurring_findings": recurring_findings,
    }


def emit_markdown(a):
    if a["total_runs"] == 0:
        print("# Recurrence analysis\n\nLedger empty — nothing to analyse yet.")
        return
    print(f"# Vault-hygiene recurrence analysis")
    print()
    print(f"**History:** {a['total_runs']} run(s), {a['date_range'][0]} → {a['date_range'][1]}  ")
    print(f"**Recurrence threshold:** {a['threshold']} runs (or any reappear-after-absence)")
    print()
    if a["total_runs"] < a["threshold"]:
        print(f"> Insufficient history for confident recurrence detection "
              f"({a['total_runs']} run(s) < {a['threshold']}). Reappear-after-absence "
              f"is still reported. Let the ledger accrue more daily snapshots.")
        print()

    recurring_cats = {c: v for c, v in a["categories"].items() if v["recurring"]}
    print(f"## Recurring categories ({len(recurring_cats)})")
    print()
    if recurring_cats:
        print("| Category | Runs seen | Prevalence | Trend | Persistent | Reappeared | Current |")
        print("|---|---|---|---|---|---|---|")
        for cat, v in sorted(recurring_cats.items(), key=lambda kv: -kv[1]["runs_seen"]):
            print(f"| {cat} | {v['runs_seen']}/{a['total_runs']} | {v['prevalence']} | "
                  f"{v['trend']} | {'yes' if v['persistent'] else '—'} | "
                  f"{'YES' if v['reappeared'] else '—'} | {v['current_count']} |")
    else:
        print("None yet.")
    print()

    rf = a["recurring_findings"]
    print(f"## Recurring specific findings ({len(rf)})")
    print()
    if rf:
        print("| Category | File | Runs | Reappeared | Message |")
        print("|---|---|---|---|---|")
        for r in rf:
            msg = (r["message"] or "").replace("|", "\\|")[:80]
            print(f"| {r['category']} | `{r['file']}` | {r['runs_seen']} | "
                  f"{'YES' if r['reappeared_after_absence'] else '—'} | {msg} |")
    else:
        print("None yet.")
    print()


def main():
    # Windows console is cp1252 and chokes on the report's arrows/dashes when
    # output goes to a terminal (piped stdout defaults to UTF-8, hence tests pass
    # but interactive runs crash). Force UTF-8; guard in case stdout isn't
    # reconfigurable.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    argv = sys.argv[1:]
    threshold = DEFAULT_THRESHOLD
    ledger_path = DEFAULT_LEDGER
    if "--threshold" in argv:
        i = argv.index("--threshold")
        try:
            threshold = int(argv[i + 1])
        except (IndexError, ValueError):
            print("ERROR: --threshold needs an integer", file=sys.stderr)
            return 0
    if "--ledger" in argv:
        i = argv.index("--ledger")
        try:
            ledger_path = Path(argv[i + 1])
        except IndexError:
            print("ERROR: --ledger needs a path", file=sys.stderr)
            return 0

    snapshots = load_snapshots(ledger_path)
    analysis = analyze(snapshots, threshold=threshold)

    if "--json" in argv:
        print(json.dumps(analysis, indent=2))
    else:
        emit_markdown(analysis)
    return 0


if __name__ == "__main__":
    sys.exit(main())
