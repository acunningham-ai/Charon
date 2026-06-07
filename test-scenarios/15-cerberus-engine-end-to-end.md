---
id: 15
slug: cerberus-engine-end-to-end
category: cerberus
tests: rule-pack engine + signature + YARA + magic-byte + homoglyph + SARIF output (v0.7.0)
setup_required: yes
---

# 15 — Cerberus rule-pack engine fires end-to-end

Tests that the v0.7.0 rule-pack engine (signature + YARA-lite + magic-byte + homoglyph layers) runs against a fixture and produces the expected findings via `scripts.cerberus.scan`. Independent of the assistant — pure deterministic check that the engine machinery is wired.

## Setup

Create a fixture skill in a tempdir that intentionally contains several attack patterns:

```bash
SCN15=$(mktemp -d)
cat > "$SCN15/skill.py" <<'EOF'
# Synthetic skill — intentionally contains attack patterns for engine testing.
def run_unsafe(user_input):
    return eval(user_input)             # COMMAND_INJECTION_EVAL

import pаypal                            # Cyrillic 'а' → HOMOGLYPH_DETECTED
PASSWORD = "sk_test_4eC39HqLyjWDarjtT1zdp7dc"  # benign test value (Stripe docs)
EOF

# A disguised binary (.py file with ELF magic) → FILE_MAGIC_MISMATCH
printf '\x7fELF\x02\x01\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00' > "$SCN15/disguised.py"
```

## Prompt to test

> Run the Cerberus rule-pack engine over `$SCN15` and tell me what fires.

## Expected behaviour

1. The assistant runs (or quotes the invocation of):
   ```bash
   python -m scripts.cerberus.scan "$SCN15" --format json
   ```
2. The output JSON lists at least the following findings (rule_id may vary slightly by pack):
   - `COMMAND_INJECTION_EVAL` on `skill.py` line 3 (CRITICAL)
   - `HOMOGLYPH_DETECTED` on `skill.py` line 5 (HIGH) — Cyrillic 'а' in `pаypal`
   - `FILE_MAGIC_MISMATCH` on `disguised.py` (HIGH) — ELF magic in a .py file
3. The reporter notes total finding count and severity distribution.
4. The reporter does NOT flag the Stripe test-key (it's a known-test value per the policy allow-list inside the vendored corpus).

## Anti-patterns to flag

- Running the scan WITHOUT going through `scripts.cerberus.scan` (e.g. inventing a fresh grep instead of using the engine)
- Missing the homoglyph finding because the assistant didn't run the engine
- Flagging the Stripe test-key as a finding (it's an allow-listed example)
- Reporting findings without showing exit code (0 clean / 1 findings / 2 error)

## Cleanup

```bash
rm -rf "$SCN15"
```

## Notes

This scenario exercises the four engine layers added in v0.7.0:
- Signature engine (`cerberus/engine/signatures.py`) — `COMMAND_INJECTION_EVAL`
- Homoglyph detection (`cerberus/engine/homoglyph.py`) — `HOMOGLYPH_DETECTED`
- Magic-byte file-type check (`cerberus/engine/file_type.py`) — `FILE_MAGIC_MISMATCH`
- The driver (`scripts/cerberus/scan.py`) orchestrates them

SARIF and YARA layers are covered by deterministic checks D14 and D12 respectively in `run-deterministic-checks.py`.
