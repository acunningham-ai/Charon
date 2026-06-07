# Cerberus rule engine (in development — v0.7.0)

This directory is the home of the **Cerberus declarative rule engine**, which extends `/cerberus-vet` from narrative V0–V8 analysis into rule-pack-driven detection: YAML signatures, YARA rules, scan policies, and LLM-judge prompt templates.

> **Status — v0.7.0 in flight.** As of 2026-06-05:
>
> - ✅ Chunks 1+2 — Apache-2.0 attribution + vendor of the cisco-ai-defense skill-scanner corpus
> - ✅ Chunk 3 — YAML signature matcher engine. **Loads 384 signature rules** from the vendored corpus (ATR 313 + core 45 + promptguard 26), 1 rule gracefully skipped due to an uncompilable backreference. Runs via `python -m cerberus.engine.smoke_test`.
> - ✅ Chunk 4 — **YARA-lite interpreter** in pure Python (no `yara-x` dep). Loads 16 YARA rules from 14 files (1 file gracefully skipped — uses hex alternation outside our subset). ELF/PE/Mach-O binary detection works. **Cumulative coverage: 400 detection rules.**
> - ✅ Chunk 4b — **`/charon-update` command** — one entry point for updating both the Charon harness itself AND any vendored content (currently the Cisco rule corpus). Manifest-driven at `scripts/update/sources.yaml`. Adding a new source = a YAML entry, not a code change. Designed for future Charon users who shouldn't have to think about per-source maintenance.
> - ✅ Chunk 5 — **Magic-byte file-type detection** in pure Python (no `magika` dep per dep-aversion). `cerberus/engine/file_type.py` covers ~30 common file types via signature matching (ELF/PE/Mach-O, ZIP/GZIP/XZ/7z/RAR, PDF/OLE, PNG/JPEG/GIF/BMP/TIFF, shebang scripts, XML/HTML/YAML markers). New `FILE_MAGIC_MISMATCH` finding (Charon-authored, in the `charon` pack) fires when a file's content magic disagrees with its extension — catches disguised executables.
> - ⏳ Chunks 6-10 — Homoglyph V8 sub-check, SARIF output, wire-up into `vet-external-skill`, tests, release.
>
> Note: only the `signature` layer is wired into the engine right now. The vendored `python/*.py` rules under each pack (which depend on Cisco's analyzer framework) remain dormant per the Option 1 scope lock — they stay vendored as future work.

## Layout

```
cerberus/
├── README.md                    # this file
├── engine/                      # Charon-native rule engine (MIT)
│   ├── __init__.py              # public API
│   ├── models.py                # Severity, FileType, SignatureRule, Finding dataclasses
│   ├── signatures.py            # YAML signature matcher (chunk 3 — landed)
│   ├── yara_lite.py             # pure-Python YARA-subset interpreter (chunk 4 — landed)
│   ├── file_type.py             # magic-byte file-type detection + FILE_MAGIC_MISMATCH (chunk 5 — landed)
│   └── smoke_test.py            # `python -m cerberus.engine.smoke_test`
└── rules/                       # vendored Apache-2.0 corpus
    ├── packs/                   # rule packs (loaded by the engine, run against scan targets)
    │   ├── core/                # 45 signatures + 17 YARA + 13 python modules
    │   ├── atr/                 # 313 signatures (AI Threat Repository — agent manipulation, prompt injection, etc.)
    │   └── promptguard/         # 26 signatures (markdown exfil, PII, secret providers)
    ├── policies/                # scan policies (default / strict / permissive)
    └── prompts/                 # LLM-judge prompt templates
```

## Run the smoke test

```bash
cd /path/to/Charon
python -m cerberus.engine.smoke_test
```

Expected output:

```
Cerberus signature engine — smoke test
  rules at: .../cerberus/rules/packs

  [PASS] corpus loads: 384 signature rules from ...
  [PASS] rules load from core + atr + promptguard packs
  [PASS] COMMAND_INJECTION_EVAL fires on eval(user_input)
  [PASS] comments about eval do NOT fire COMMAND_INJECTION_EVAL

  4/4 passed
```

You may see one `WARN cerberus.engine: skipping rule 'ATR_2026_00290'` line on stderr — that's the one corpus rule with an uncompilable backreference. Graceful skip.

Each pack contains:
- `pack.yaml` — pack metadata + load order
- `signatures/*.yaml` — pattern-based detection rules
- `yara/*.yara` — YARA binary/text-pattern rules (loaded by `yara-x`)
- `python/*.py` — Python rule modules (loaded into the engine's sandboxed exec context — limited surface, no network/filesystem)

## Attribution

The entire `rules/` tree is **vendored unchanged** from [cisco-ai-defense/skill-scanner](https://github.com/cisco-ai-defense/skill-scanner) at SHA `ff708ea00fd401640112c138711c5c36ff4992a0` (2026-06-05) under **Apache License, Version 2.0**.

- Apache-2.0 licence: see [`LICENSE-cisco-apache-2.0`](../LICENSE-cisco-apache-2.0) at repo root
- Attribution record: see [`NOTICE`](../NOTICE) at repo root
- Copyright: Cisco Systems, Inc. and its affiliates

If a file is ever modified for Charon-specific reasons, a `Modified by Charon` comment will be added at the top per Apache-2.0 §4(b).

The rule **engine** that runs these rules — when it ships in v0.7.0 — is a separate, Charon-native implementation under the project's own MIT licence ([`LICENSE`](../LICENSE)). The licence boundary is at the engine ↔ rules interface: rules carry Apache-2.0; engine code carries MIT.

## v0.7.0 roadmap

The remaining chunks of v0.7.0 work, after the corpus vendor:

| # | Chunk | Status |
|---|---|---|
| 1 | Licence + attribution scaffolding | ✅ landed (this commit) |
| 2 | Vendor the rule corpus | ✅ landed (this commit) |
| 3 | Rule engine — signature matcher (YAML) | pending |
| 4 | Rule engine — YARA runner | pending |
| 5 | V3 sub-check — Magika file-type detection | pending |
| 6 | V8 sub-check — Unicode homoglyph detection | pending |
| 7 | SARIF output format on `/cerberus-vet` | pending |
| 8 | Wire engine into `vet-external-skill` skill | pending |
| 9 | Test scenarios + deterministic checks | pending |
| 10 | Docs + CHANGELOG + release | pending |

New runtime deps (`yara-x`, `magika`, `confusable-homoglyphs`) will ship via an opt-in `requirements-cerberus.txt`, matching the existing Charon pattern (`requirements-semantic.txt` / `-graph.txt` / `-voice.txt`). Base Charon stays lean; users who want full rule-pack detection install the optional deps. Graceful degradation when any dep is absent.

## How to update the corpus

When upstream cisco-ai-defense/skill-scanner ships new rules:

1. Clone the upstream repo at the new SHA.
2. Run `git diff <old-sha>..<new-sha> -- skill_scanner/data/` upstream to see what changed.
3. Copy `skill_scanner/data/packs/`, `skill_scanner/data/policies/*.yaml`, and `skill_scanner/data/prompts/` into `cerberus/rules/`.
4. Update the SHA reference in `NOTICE` at repo root.
5. Update the SHA reference at the top of this file.
6. Run the v0.7.0+ rule-engine self-tests to confirm the new rules load + match.
7. Commit with message `corpus: sync cisco rules to <new-sha>`.

Do NOT modify vendored files except via marked `Modified by Charon` headers.

## How to add Charon-native rules

Charon-native rules (not from the Cisco corpus) live under `cerberus/rules/packs/charon/`. This pack does not exist yet — it will be created when the first native rule lands.

Files under `charon/` are Charon's own MIT-licensed work; they do not carry Apache-2.0 headers.
