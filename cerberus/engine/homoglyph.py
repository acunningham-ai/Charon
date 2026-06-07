"""Unicode homoglyph detection — V8 sub-check for typosquat patterns.

Charon-native, dep-free. Detects strings that mix ASCII Latin characters
with visually-confusable characters from other Unicode scripts (Cyrillic,
Greek, Armenian, etc.). The classic attack vector: a package or skill
name that looks like ``react`` but where the ``a`` is U+0430 (Cyrillic),
not U+0061 (Latin). To a human reviewer the name reads correctly; to
the runtime it resolves to a different (attacker-controlled) artifact.

Strategy: tokenise the input into "words" (sequences of letter chars).
For each word that contains at least one confusable AND at least one
ASCII Latin char, emit a HOMOGLYPH_DETECTED finding. Pure-script words
(all Cyrillic / all Greek / all Latin) don't fire — only mixed scripts
do. That keeps legitimate non-Latin content (ATR rule descriptions, etc.)
quiet while catching the typosquat pattern.

Rule lives in the ``charon`` pack alongside FILE_MAGIC_MISMATCH —
Charon-authored, sibling to vendored Cisco rules.

The full `confusable-homoglyphs` PyPI package would give us tens of
thousands of mappings via the official Unicode confusables.txt. We ship
~80 mappings covering the most-exploited attack characters per
feedback_charon_dep_aversion. Trade-off: tighter precision (~80 chars
that DO get used in typosquats vs the long tail of theoretical confusables).
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Iterable, List, Set, Tuple

from cerberus.engine.models import Finding, Severity


# ---------- Confusables table ----------
# Non-ASCII characters that visually resemble ASCII Latin chars.
# Each entry: NON_LATIN_CHAR -> (LATIN_LOOK_ALIKE, source_script_name)

_CONFUSABLES: dict = {
    # --- Cyrillic ---
    "а": ("a", "Cyrillic"), "А": ("A", "Cyrillic"),
    "е": ("e", "Cyrillic"), "Е": ("E", "Cyrillic"),
    "о": ("o", "Cyrillic"), "О": ("O", "Cyrillic"),
    "р": ("p", "Cyrillic"), "Р": ("P", "Cyrillic"),
    "с": ("c", "Cyrillic"), "С": ("C", "Cyrillic"),
    "х": ("x", "Cyrillic"), "Х": ("X", "Cyrillic"),
    "у": ("y", "Cyrillic"), "У": ("Y", "Cyrillic"),
    "В": ("B", "Cyrillic"),
    "Н": ("H", "Cyrillic"),
    "К": ("K", "Cyrillic"),
    "М": ("M", "Cyrillic"),
    "Т": ("T", "Cyrillic"),
    "ѕ": ("s", "Cyrillic"), "Ѕ": ("S", "Cyrillic"),
    "і": ("i", "Cyrillic"), "І": ("I", "Cyrillic"),
    "ј": ("j", "Cyrillic"), "Ј": ("J", "Cyrillic"),
    "ԁ": ("d", "Cyrillic"),
    "ԛ": ("q", "Cyrillic"),
    "ԝ": ("w", "Cyrillic"),

    # --- Greek ---
    "α": ("a", "Greek"), "Α": ("A", "Greek"),
    "β": ("b", "Greek"), "Β": ("B", "Greek"),
    "ε": ("e", "Greek"), "Ε": ("E", "Greek"),
    "ο": ("o", "Greek"), "Ο": ("O", "Greek"),
    "ρ": ("p", "Greek"), "Ρ": ("P", "Greek"),
    "τ": ("t", "Greek"), "Τ": ("T", "Greek"),
    "Η": ("H", "Greek"),
    "Κ": ("K", "Greek"),
    "Μ": ("M", "Greek"),
    "Ν": ("N", "Greek"),
    "Χ": ("X", "Greek"),
    "Ζ": ("Z", "Greek"),
    "ι": ("i", "Greek"), "Ι": ("I", "Greek"),
    "υ": ("u", "Greek"), "Υ": ("Y", "Greek"),
    "ν": ("v", "Greek"),

    # --- Armenian ---
    "ո": ("n", "Armenian"),
    "օ": ("o", "Armenian"),

    # --- Latin (extended) look-alikes ---
    "ı": ("i", "Latin-Extended"),   # dotless i (Turkish)
    "ł": ("l", "Latin-Extended"),   # Polish l-with-stroke
    "ø": ("o", "Latin-Extended"),
    "ɑ": ("a", "Latin-IPA"),

    # --- Fullwidth (East Asian) Latin look-alikes ---
    "ａ": ("a", "Fullwidth"), "Ａ": ("A", "Fullwidth"),
    "ｂ": ("b", "Fullwidth"), "Ｂ": ("B", "Fullwidth"),
    "ｃ": ("c", "Fullwidth"), "Ｃ": ("C", "Fullwidth"),
    "ｄ": ("d", "Fullwidth"), "Ｄ": ("D", "Fullwidth"),
    "ｅ": ("e", "Fullwidth"), "Ｅ": ("E", "Fullwidth"),
    "ｉ": ("i", "Fullwidth"), "Ｉ": ("I", "Fullwidth"),
    "ｏ": ("o", "Fullwidth"), "Ｏ": ("O", "Fullwidth"),
    "ｐ": ("p", "Fullwidth"), "Ｐ": ("P", "Fullwidth"),
    "ｓ": ("s", "Fullwidth"), "Ｓ": ("S", "Fullwidth"),
}


# ---------- Scanning ----------

# Word = run of letter-class characters (Latin + non-Latin together)
# Use a Unicode-aware regex: \w in Python's `re` module matches letters by default.
_WORD_RE = re.compile(r"[^\W\d_]+", re.UNICODE)

# Cheap "is ASCII Latin letter" check
def _is_latin_ascii(ch: str) -> bool:
    return ("a" <= ch <= "z") or ("A" <= ch <= "Z")


def _ascii_canonical(word: str) -> str:
    """Substitute confusables with their Latin look-alike. Returns the
    canonical-Latin form of the input. e.g. 'pаypal' (Cyrillic а) → 'paypal'."""
    out = []
    for ch in word:
        sub = _CONFUSABLES.get(ch)
        out.append(sub[0] if sub else ch)
    return "".join(out)


def find_mixed_script_words(text: str) -> List[Tuple[str, int, str, Set[str]]]:
    """Return [(word, char_offset, canonical_form, scripts_found), ...]
    for every word containing both ASCII Latin AND confusable characters.

    Pure-script words (all Latin, or all Cyrillic, or all Greek) don't fire.
    """
    matches: List[Tuple[str, int, str, Set[str]]] = []
    for m in _WORD_RE.finditer(text):
        word = m.group(0)
        if len(word) < 2:
            continue
        has_latin = False
        scripts_found: Set[str] = set()
        for ch in word:
            if _is_latin_ascii(ch):
                has_latin = True
            elif ch in _CONFUSABLES:
                scripts_found.add(_CONFUSABLES[ch][1])
        if has_latin and scripts_found:
            matches.append((word, m.start(), _ascii_canonical(word), scripts_found))
    return matches


def scan_text_for_homoglyphs(text: str, path: Path) -> List[Finding]:
    """Scan an in-memory text blob for mixed-script words. Returns Findings."""
    findings: List[Finding] = []
    for word, offset, canonical, scripts in find_mixed_script_words(text):
        line_no = text.count("\n", 0, offset) + 1
        scripts_str = " + ".join(sorted(scripts))
        findings.append(Finding(
            rule_id="HOMOGLYPH_DETECTED",
            pack="charon",
            category="hardcoded_secrets",
            severity=Severity.HIGH,
            path=str(path),
            line=line_no,
            matched_text=word,
            description=(
                f"Word {word!r} mixes ASCII Latin with {scripts_str} characters — "
                f"canonical form is {canonical!r}. Typosquat indicator: the word "
                f"looks like {canonical!r} to a human reviewer but resolves to a "
                f"different identifier at runtime."
            ),
            remediation=(
                f"Replace any non-Latin look-alike characters with the intended "
                f"Latin character. Verify the artifact's true identifier matches "
                f"the canonical name {canonical!r}."
            ),
        ))
    return findings


def scan_file_for_homoglyphs(path: Path) -> List[Finding]:
    """Public wrapper — read file as text and scan for mixed-script words."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    return scan_text_for_homoglyphs(text, path)
