#!/usr/bin/env python
"""telemetry-summary.py — roll up hook telemetry over the last N days.

Standalone version of the inline Python in `.claude/commands/telemetry-summary.md`.
Useful for unattended weekly summarisation via scheduled task.

Reads append-only JSONL events from `state/telemetry/{hook}/{YYYY-MM-DD}.jsonl`
under the VAULT root (matching where `_telemetry.py` writes them).

Usage:
  python telemetry-summary.py            # default 7 days
  python telemetry-summary.py 30         # 30-day window
"""
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.harness_paths import vault_root  # noqa: E402

TELEMETRY_ROOT = vault_root() / "state" / "telemetry"

# Pricing example (Haiku 4.5): $1/MTok input, $5/MTok output, ~$0.10/MTok cached input.
# Adjust to match the model your hooks call. Provider websites publish current pricing.
PRICE_IN_PER_MTOK = 1.0
PRICE_OUT_PER_MTOK = 5.0
PRICE_CACHE_READ_PER_MTOK = 0.1


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    if not TELEMETRY_ROOT.exists():
        print(f"No telemetry yet — {TELEMETRY_ROOT} does not exist.")
        return 0

    totals = {}
    for hook_dir in TELEMETRY_ROOT.iterdir():
        if not hook_dir.is_dir():
            continue
        h = hook_dir.name
        t = totals.setdefault(
            h,
            {
                "invocations": 0,
                "stage1_miss": 0,
                "oversize": 0,
                "no_api_key": 0,
                "stage2_calls": 0,
                "fact_detected": 0,
                "errors": 0,
                "in_tok": 0,
                "out_tok": 0,
                "cache_read": 0,
                "cache_create": 0,
            },
        )
        for f in hook_dir.glob("*.jsonl"):
            for line in f.read_text(encoding="utf-8").splitlines():
                try:
                    e = json.loads(line)
                except Exception:
                    continue
                try:
                    ts = datetime.fromisoformat(e["ts"])
                except Exception:
                    continue
                if ts < cutoff:
                    continue
                t["invocations"] += 1
                p = e.get("payload") or {}
                ev = e.get("event")
                if ev == "skipped":
                    reason = p.get("reason", "other")
                    t[reason] = t.get(reason, 0) + 1
                if ev == "stage2":
                    t["stage2_calls"] += 1
                    if p.get("fact_detected"):
                        t["fact_detected"] += 1
                    if p.get("error"):
                        t["errors"] += 1
                    t["in_tok"] += p.get("input_tokens") or 0
                    t["out_tok"] += p.get("output_tokens") or 0
                    t["cache_read"] += p.get("cache_read_input_tokens") or 0
                    t["cache_create"] += p.get("cache_creation_input_tokens") or 0

    now_iso = datetime.now(timezone.utc).isoformat(timespec="seconds")
    print(f"=== Telemetry — last {days} day(s), as of {now_iso} ===")

    if not totals:
        print("(no hook directories under state/telemetry/)")
        return 0

    for h, t in totals.items():
        print(f"\n[{h}]")
        print(f"  invocations:        {t['invocations']}")
        print(f"  stage1_miss:        {t['stage1_miss']}")
        print(f"  oversize:           {t['oversize']}")
        print(f"  no_api_key:         {t['no_api_key']}")
        print(f"  stage2_calls:       {t['stage2_calls']}")
        print(f"    -> fact_detected: {t['fact_detected']}")
        print(f"    -> errors:        {t['errors']}")
        print(
            f"  tokens:  in={t['in_tok']}  out={t['out_tok']}  "
            f"cache_read={t['cache_read']}  cache_create={t['cache_create']}"
        )
        cost = (
            (t["in_tok"] / 1_000_000) * PRICE_IN_PER_MTOK
            + (t["out_tok"] / 1_000_000) * PRICE_OUT_PER_MTOK
            + (t["cache_read"] / 1_000_000) * PRICE_CACHE_READ_PER_MTOK
        )
        print(f"  est cost (USD):     ${cost:.4f}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
