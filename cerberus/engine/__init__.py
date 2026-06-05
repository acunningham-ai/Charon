"""Cerberus rule engine — layered detection over scan targets.

Detection layers (lands across v0.7.0 chunks 3-6):

- Signatures   — YAML pattern rules, this module (chunk 3)
- YARA         — binary/text pattern rules via yara-x (chunk 4, opt-in dep)
- Magika       — file-type detection upgrade for V3 (chunk 5, opt-in dep)
- Homoglyph    — Unicode confusable detection for V8 (chunk 6, opt-in dep)
- SARIF output — chunk 7

The rule **corpus** under ``cerberus/rules/`` is vendored Apache-2.0 content
from cisco-ai-defense/skill-scanner. See the top-level NOTICE for attribution.

The rule **engine** (this package) is Charon-native, MIT-licensed.

Scope note (Option 1, locked 2026-06-05): this engine implements the
``source: signature`` and ``source: yara`` layers of the corpus. The
``source: python`` rules under ``cerberus/rules/packs/*/python/`` depend
on Cisco's full analyzer framework and stay vendored as future work — they
do not load or run in this engine. ~47 of the ~107 corpus rules are active.
"""

from cerberus.engine.models import (
    FileType,
    Finding,
    Severity,
    SignatureRule,
)
from cerberus.engine.signatures import (
    detect_file_type,
    load_all_packs,
    load_pack_signatures,
    scan_file,
    scan_path,
)

__all__ = [
    "FileType",
    "Finding",
    "Severity",
    "SignatureRule",
    "detect_file_type",
    "load_all_packs",
    "load_pack_signatures",
    "scan_file",
    "scan_path",
]
