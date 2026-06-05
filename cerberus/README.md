# Cerberus rule engine (in development — v0.7.0)

This directory is the home of the **Cerberus declarative rule engine**, which extends `/cerberus-vet` from narrative V0–V8 analysis into rule-pack-driven detection: YAML signatures, YARA rules, scan policies, and LLM-judge prompt templates.

> **Status — v0.7.0 in flight.** As of 2026-06-05, the rule corpus is vendored (this commit). The rule engine that loads and runs these rules is the next chunk of v0.7.0 work. The vendored files do not affect runtime behaviour until the engine ships.

## Layout

```
cerberus/
├── README.md                    # this file
└── rules/
    ├── packs/                   # rule packs (loaded by the engine, run against scan targets)
    │   ├── core/                # general-purpose detections
    │   ├── atr/                 # AI Threat Repository — prompt injection, exfiltration, manipulation
    │   └── promptguard/         # prompt-specific rules
    ├── policies/                # scan policies (default / strict / permissive)
    │   ├── default_policy.yaml
    │   ├── strict_policy.yaml
    │   └── permissive_policy.yaml
    └── prompts/                 # LLM-judge prompt templates
```

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
