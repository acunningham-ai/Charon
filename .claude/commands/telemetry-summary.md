---
description: Roll up hook telemetry over the last N days — counts, tokens, est cost
argument-hint: "[optional: number of days, default 7]"
allowed-tools: Bash, Read, Glob
---

# /telemetry-summary — what the harness has been doing

Reads append-only JSONL events written by telemetry hooks to `state/telemetry/{hook}/{YYYY-MM-DD}.jsonl` and summarises usage. Hooks that don't burn tokens (local-only deterministic hooks) don't show up here.

## Window
$ARGUMENTS

Default 7 days. Pass an integer (e.g. `30`) to widen.

## What to compute

Run this Python one-liner (adjust `--days` from `$ARGUMENTS` if provided, default 7):

```bash
python -c "
import json, sys, glob
from datetime import datetime, timezone, timedelta
from pathlib import Path
days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
cutoff = datetime.now(timezone.utc) - timedelta(days=days)
root = Path('state/telemetry')
if not root.exists():
    print('No telemetry yet — state/telemetry/ does not exist.'); sys.exit(0)
totals = {}
for hook_dir in root.iterdir():
    if not hook_dir.is_dir(): continue
    h = hook_dir.name
    t = totals.setdefault(h, {'invocations': 0, 'stage1_miss': 0, 'oversize': 0, 'no_api_key': 0, 'stage2_calls': 0, 'fact_detected': 0, 'errors': 0, 'in_tok': 0, 'out_tok': 0, 'cache_read': 0, 'cache_create': 0})
    for f in hook_dir.glob('*.jsonl'):
        for line in f.read_text(encoding='utf-8').splitlines():
            try: e = json.loads(line)
            except: continue
            try: ts = datetime.fromisoformat(e['ts'])
            except: continue
            if ts < cutoff: continue
            t['invocations'] += 1
            p = e.get('payload') or {}
            ev = e.get('event')
            if ev == 'skipped':
                t[p.get('reason','other')] = t.get(p.get('reason','other'),0) + 1
            if ev == 'stage2':
                t['stage2_calls'] += 1
                if p.get('fact_detected'): t['fact_detected'] += 1
                if p.get('error'): t['errors'] += 1
                t['in_tok'] += p.get('input_tokens') or 0
                t['out_tok'] += p.get('output_tokens') or 0
                t['cache_read'] += p.get('cache_read_input_tokens') or 0
                t['cache_create'] += p.get('cache_creation_input_tokens') or 0
print(f'=== Telemetry — last {days} day(s), as of {datetime.now(timezone.utc).isoformat(timespec=\"seconds\")} ===')
for h, t in totals.items():
    print(f'\n[{h}]')
    print(f'  invocations:        {t[\"invocations\"]}')
    print(f'  stage1_miss:        {t[\"stage1_miss\"]}')
    print(f'  oversize:           {t[\"oversize\"]}')
    print(f'  no_api_key:         {t[\"no_api_key\"]}')
    print(f'  stage2_calls:       {t[\"stage2_calls\"]}')
    print(f'    -> fact_detected: {t[\"fact_detected\"]}')
    print(f'    -> errors:        {t[\"errors\"]}')
    print(f'  tokens:  in={t[\"in_tok\"]}  out={t[\"out_tok\"]}  cache_read={t[\"cache_read\"]}  cache_create={t[\"cache_create\"]}')
    # Pricing example (Haiku 4.5): \$1/MTok input, \$5/MTok output, cached input ~\$0.10/MTok. Adjust to your hook's model.
    cost = (t['in_tok']/1_000_000)*1 + (t['out_tok']/1_000_000)*5 + (t['cache_read']/1_000_000)*0.1
    print(f'  est cost (USD):     \${cost:.4f}')
" $ARGUMENTS
```

## Output

After running, format a one-screen summary:

```markdown
## Telemetry — last {N} days

| hook | invocations | stage2 calls | fact_detected | est cost |
|---|---|---|---|---|
| save-on-mention | {} | {} | {} | ${} |

**Notes:**
- {anything anomalous, e.g. error rate >5%, stage1 hit rate weirdly high/low}
- {budget signal if cost is on a trajectory toward your cap}
```

Don't paste the raw Python output unless the user asks. Verdict, not data.

## When this is useful
- **Cap-near alarm:** when your provider notifies "approaching cap", run this with `30` to see which hook is responsible.
- **Tuning:** if `stage1_miss` is way higher than `stage2_calls`, the regex prefilter is doing its job. If `stage2_calls` is high but `fact_detected` is low, the model is rejecting candidates — possibly tighten the regex.
- **Health check:** errors > 0 for the live API call means something's intermittent (network, key, rate limit).
