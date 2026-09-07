#!/usr/bin/env python3
"""
Shared role / provenance discriminator for harness detectors.

WHY THIS EXISTS. Five detectors were reviewed after sitting in shadow for up to
eight weeks. None was promotable, and all four noisy ones shared exactly ONE
defect:

    They matched on CONTENT with no discriminator for who acted,
    or for what role the artefact plays.

    | Detector       | Could not distinguish                                  |
    |----------------|--------------------------------------------------------|
    | policy engine  | harness doing its mandated job ↔ unexpected config write|
    | phase-gate     | iterating a draft ↔ landing the final version           |
    | poisoning-scan | you *discussing* injection ↔ an injection *attempt*     |
    | config scanner | a file *describing* a directive ↔ one *containing* it   |

`score-vault.py` had the same defect twice (prose mention vs real link) and was
fixed structurally rather than per-note. This module generalises that fix so the
class closes once instead of five times.

────────────────────────────────────────────────────────────────────────────
FACET A — trust_zone(path) and artefact_role(path)

  WHO produced this, and WHAT is it for. Cheap, deterministic, provenance-based.
  This is the SAFE facet: it reasons about provenance, which an attacker
  supplying *content* cannot forge into MORE trust.

  Mostly path-derived. trust_zone ALSO reads the frontmatter of on-disk .md
  files, because path alone is wrong: in the reference deployment 320
  capture-sourced notes (`source: m365-calendar`, `plaud`) lived inside the
  "authored" vault zones and were being classified "vault-authored". The
  frontmatter check is one-way — it can only downgrade to "untrusted-capture",
  never grant trust — and it reads the frontmatter BLOCK only, so body prose
  cannot trigger it.

FACET B — describes_not_contains(text, ...)

  Is a matched pattern a DESCRIPTION of the thing (documentation, a quoted
  example, a code span) or a live INSTANCE of it?

  ⚠️  SECURITY BOUNDARY — READ BEFORE USING FACET B.
  Facet B is an EVASION SURFACE. If a detector suppresses findings whenever the
  match sits inside a code fence, an attacker wraps the payload in backticks and
  walks straight through. Therefore:

      Facet B MUST NOT be the sole basis for suppressing a finding.
      It may only downgrade a finding whose provenance is ALREADY TRUSTED
      (facet A returned "harness-own" or "vault-authored").

  On untrusted or foreign provenance, facet B is advisory only — surface the
  finding regardless. `should_suppress()` enforces this pairing so a caller
  cannot get it wrong by accident.

Fail-safe contract: every function returns a conservative value on bad input
(unknown zone / "authored" role / False for "this is only documentation") so a
bug here can never silently switch a detector off.
"""
from __future__ import annotations

import os
import re
from functools import lru_cache
from pathlib import Path

__all__ = [
    "trust_zone", "artefact_role", "is_draft",
    "strip_code_spans", "describes_not_contains", "should_suppress",
]

# ---------------------------------------------------------------------------
# FACET A — provenance and role
# ---------------------------------------------------------------------------

# Zones, most-specific first. Matched against a forward-slashed path.
_UNTRUSTED_MARKERS = ("/00-inbox/_captured/",)
_HARNESS_OWN_MARKERS = ("/.claude/", "/scripts/hooks/", "/scripts/mcp/")

# Derived artefacts: regenerated wholesale by an automation, never hand-authored.
# Editing one is not an authoring act, so gates meant for authored content
# should not fire on them.
_DERIVED_BASENAMES = {"todo.md"}
_DERIVED_MARKERS = (
    "/07-references/dashboards/",
    "/07-references/weekly-digest",
    "/00-inbox/_reports/",
    "/00-inbox/_harness/",
    "/00-inbox/_research/",
    "/state/",
)

# Index files whose co-change is compelled by another control. Gating them
# duplicates (and fights) that control.
_INDEX_BASENAMES = {"memory.md"}

_DRAFT_RE = re.compile(r"[-_.](draft|wip)\b|\bdraft[-_.]", re.IGNORECASE)

# --- capture provenance from frontmatter ------------------------------------
#
# WHY path alone is not enough. The convention is that captured content lives
# under 00-Inbox/_captured and authored content elsewhere is trusted. In practice
# that does not hold: calendar invites and meeting transcripts get filed into the
# authored zones by capture automations, and they are externally controlled — so
# a path-only rule calls attacker-influenceable content "vault-authored".
#
# Matching is confined to the FRONTMATTER BLOCK, never the body. Frontmatter is
# structured metadata written by the capture pipeline, so prose that merely
# mentions `source: m365-calendar` cannot trigger it — this check has no
# describes-vs-contains problem, which is precisely the failure mode facet B
# warns about.
#
# DIRECTION IS ONE-WAY: this can only downgrade "vault-authored" ->
# "untrusted-capture". It can never grant trust, so a file whose content an
# attacker controls cannot use it to look MORE trusted than its path implies.
#
# HONEST LIMIT: facet A is no longer strictly path-only for on-disk .md files.
# On any read failure it returns False and the classification falls back to the
# path-only answer. It is an ENHANCEMENT to detection, not a boundary to rely on.
_FRONTMATTER_BYTES = 1500
_FRONTMATTER_RE = re.compile(r"\A\s*---\r?\n(.*?)\r?\n---", re.S)
_CAPTURE_SOURCE_RE = re.compile(
    r"^(?:source|trust):\s*[\"']?\s*"
    r"(m365|m365-calendar|plaud|outlook|teams|graph-api|untrusted|captured)",
    re.M | re.I,
)


@lru_cache(maxsize=512)
def _has_capture_frontmatter(path_str: str) -> bool:
    """True when a file's FRONTMATTER declares capture provenance.

    False on anything uncertain — missing file, non-markdown, no frontmatter,
    unreadable — so the caller falls back to path-based classification.
    Cached because hooks may classify the same path several times per run.
    """
    try:
        p = Path(path_str)
        if p.suffix.lower() != ".md" or not p.is_file():
            return False
        with p.open("r", encoding="utf-8", errors="replace") as fh:
            head = fh.read(_FRONTMATTER_BYTES)
        block = _FRONTMATTER_RE.match(head)
        if not block:
            return False
        return _CAPTURE_SOURCE_RE.search(block.group(1)) is not None
    except Exception:
        return False


def _norm(path) -> str:
    try:
        return str(path).replace("\\", "/").lower()
    except Exception:
        return ""


def _project_root() -> str:
    """The vault root, forward-slashed and lower-cased, without a trailing slash.

    PORTABILITY NOTE. The reference implementation this was ported from tested
    `"/secondbrain/" in path` — a hard-coded folder name that only ever worked in
    one person's install. Your vault can live anywhere, so the root is derived:

      1. CLAUDE_PROJECT_DIR when set — this is how hooks are invoked, so it is
         the authoritative answer in normal operation.
      2. Otherwise this file's location: scripts/hooks/_provenance.py -> root.

    Returns "" if neither works, and callers treat an empty root as "cannot tell"
    — which classifies to "foreign"/"unknown", the conservative direction.
    """
    root = os.environ.get("CLAUDE_PROJECT_DIR") or ""
    if not root:
        try:
            root = str(Path(__file__).resolve().parents[2])
        except Exception:
            return ""
    return _norm(root).rstrip("/")


def _under(path_norm: str, root_norm: str) -> bool:
    """True if path is the root or sits beneath it. Both already normalised."""
    if not path_norm or not root_norm:
        return False
    return path_norm == root_norm or path_norm.startswith(root_norm + "/")


def trust_zone(path) -> str:
    """
    Provenance of a path. One of:

      "untrusted-capture" — captured email/Teams/calendar. Attacker-influenced
                            by design; NEVER relax a detector here.
      "harness-own"       — the harness's own config (.claude/, hooks, MCP).
                            Authored by you, or by Claude under your review.
      "vault-authored"    — trusted authored vault content.
      "foreign"           — outside the vault entirely (a cloned repo, temp dir).
                            Treat as untrusted for config-poisoning purposes.
      "unknown"           — could not tell. Callers must treat as untrusted.
    """
    p = _norm(path)
    if not p:
        return "unknown"
    if any(m in p for m in _UNTRUSTED_MARKERS):
        return "untrusted-capture"
    in_vault = _under(p, _project_root())
    # NOTE: must be ".claude/projects/" — "/claude/projects/" never matches,
    # because the real path segment is "/.claude/" (slash-dot-c). That typo
    # classified the whole memory dir as "foreign" in the reference deployment
    # and was caught only by a calibration test, not by this module's selftest.
    in_memory = ".claude/projects/" in p and "/memory/" in p
    if any(m in p for m in _HARNESS_OWN_MARKERS) and (in_vault or in_memory):
        return "harness-own"
    if in_vault or in_memory:
        # Frontmatter provenance can DOWNGRADE an apparently-authored note to
        # untrusted, never the reverse. Checked only here, so harness-own config
        # is never reclassified by file content.
        if _has_capture_frontmatter(str(path)):
            return "untrusted-capture"
        return "vault-authored"
    return "foreign"


def is_draft(path) -> bool:
    """True if the filename marks it as a draft / work-in-progress."""
    p = _norm(path)
    return bool(p) and _DRAFT_RE.search(p.rsplit("/", 1)[-1]) is not None


def artefact_role(path) -> str:
    """
    What the artefact is FOR. One of:

      "derived"  — regenerated wholesale by an automation (TODO.md, dashboards,
                   reports). Not an authoring act.
      "index"    — an index whose co-change another control already compels
                   (MEMORY.md).
      "draft"    — an in-progress authored artefact.
      "authored" — a durable authored artefact. The conservative default.
    """
    p = _norm(path)
    if not p:
        return "authored"
    base = p.rsplit("/", 1)[-1]
    if base in _INDEX_BASENAMES:
        return "index"
    if base in _DERIVED_BASENAMES or any(m in p for m in _DERIVED_MARKERS):
        return "derived"
    if is_draft(p):
        return "draft"
    return "authored"


# ---------------------------------------------------------------------------
# FACET B — describing vs containing
# ---------------------------------------------------------------------------

_CODE_FENCE_RE = re.compile(r"```.*?```|~~~.*?~~~", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`\n]*`")

# Phrases that mark the surrounding text as ABOUT a pattern rather than an
# instance of it. Deliberately narrow: each is doc-register language that an
# attacker gains nothing by adding (adding them does not make a payload work).
_DOC_REGISTER = (
    "for example", "e.g.", "such as", "would flag", "would fire",
    "false positive", "anti-pattern", "do not", "don't ", "never ",
    "this rule", "the detector", "detects", "is flagged", "example:",
)


def strip_code_spans(text: str) -> str:
    """
    Remove fenced blocks first, THEN inline code.

    Fences first matters: a fence containing stray backticks would otherwise
    leave unbalanced inline pairs that swallow real prose.
    """
    if not text:
        return ""
    try:
        return _INLINE_CODE_RE.sub(" ", _CODE_FENCE_RE.sub(" ", text))
    except Exception:
        return text


def describes_not_contains(text: str, needle: str = "") -> bool:
    """
    True if `needle` appears ONLY inside code spans, or the text reads as
    documentation ABOUT the pattern.

    Returns False (the conservative answer — "this may be a real instance") on
    empty input or any error.

    NOT a security decision on its own. See should_suppress().
    """
    if not text:
        return False
    try:
        if needle:
            stripped = strip_code_spans(text)
            # Present originally but gone after stripping ⇒ only ever in code.
            if needle.lower() in text.lower() and needle.lower() not in stripped.lower():
                return True
        low = text.lower()
        return sum(1 for m in _DOC_REGISTER if m in low) >= 2
    except Exception:
        return False


def should_suppress(path, text: str = "", needle: str = "") -> bool:
    """
    The ONLY sanctioned way to let facet B reduce a finding.

    Suppression requires BOTH:
      1. trusted provenance — facet A says "harness-own" or "vault-authored"; and
      2. the match reads as documentation — facet B.

    On untrusted-capture / foreign / unknown provenance this always returns
    False, so wrapping a payload in backticks buys an attacker nothing.
    """
    try:
        if trust_zone(path) not in ("harness-own", "vault-authored"):
            return False
        return describes_not_contains(text, needle)
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Selftest — proves each discriminator still fires AND still refuses.
# ---------------------------------------------------------------------------

def _selftest() -> int:
    # Windows console is cp1252; the arrows below crash a bare print otherwise.
    # Piped stdout is UTF-8, so a piped test run would mask it.
    import sys as _s
    try:
        _s.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    import tempfile as _tf

    # A vault root that is NOT named after any particular install — the whole
    # point of the portability fix. Set CLAUDE_PROJECT_DIR so _project_root()
    # resolves to it, exactly as the harness does when invoking a hook.
    _base = _tf.mkdtemp()
    V = _norm(os.path.join(_base, "my-notes")) + "/"
    os.environ["CLAUDE_PROJECT_DIR"] = V.rstrip("/")
    M = "c:/users/a/.claude/projects/c--x-my-notes/memory/"

    # Real files on disk for the frontmatter-provenance checks. The path says
    # "authored vault note" in every case; only the frontmatter differs.
    _d = os.path.join(V.rstrip("/"), "05-Meetings")
    os.makedirs(_d, exist_ok=True)

    def _w(name, body):
        fp = os.path.join(_d, name)
        with open(fp, "w", encoding="utf-8") as fh:
            fh.write(body)
        return fp.replace("\\", "/")

    _cap = _w("captured-meeting.md",
              "---\ntype: meeting\nsource: m365-calendar\n---\n\n# Notes\n")
    _plaud = _w("voice.md", "---\nsource: plaud\n---\n\nTranscript\n")
    _authored = _w("real-note.md", "---\ntype: meeting\nauthor: me\n---\n\n# Notes\n")
    _prose = _w("about-capture.md",
                "---\ntype: reference\n---\n\nCaptured notes carry\n"
                "`source: m365-calendar` in their frontmatter.\n")
    _nofm = _w("plain.md", "# Just a heading\n\nsource: m365-calendar\n")

    checks = [
        # --- portability: an arbitrary vault root is recognised ---
        (trust_zone(V + "08-Projects/x.md") == "vault-authored",
         "arbitrary vault root→vault-authored (no hard-coded folder name)"),
        # --- frontmatter provenance ---
        (trust_zone(_cap) == "untrusted-capture", "m365 frontmatter→untrusted"),
        (trust_zone(_plaud) == "untrusted-capture", "plaud frontmatter→untrusted"),
        (trust_zone(_authored) == "vault-authored", "authored note→vault-authored"),
        # Body prose that MENTIONS the marker must not reclassify — the
        # describes-vs-contains trap this module exists to avoid.
        (trust_zone(_prose) == "vault-authored", "prose mention→still authored"),
        (trust_zone(_nofm) == "vault-authored", "marker outside frontmatter→still authored"),
        (trust_zone(os.path.join(_d, "does-not-exist.md")) == "vault-authored",
         "missing file→path-based fallback"),
        # One-way: frontmatter can never UPGRADE trust.
        (trust_zone(V + "00-Inbox/_captured/x.md") == "untrusted-capture",
         "captured path stays untrusted regardless of content"),
        # facet A — zones
        (trust_zone(V + "00-Inbox/_captured/email/x.md") == "untrusted-capture", "captured→untrusted"),
        (trust_zone(V + ".claude/agents/researcher.md") == "harness-own", "agent→harness-own"),
        (trust_zone("c:/tmp/some-repo/.cursorrules") == "foreign", "cloned repo→foreign"),
        (trust_zone("") == "unknown", "empty→unknown"),
        # Memory dir lives OUTSIDE the vault, under ~/.claude/projects/<slug>/memory/.
        # Regression guard for the "/claude/projects/" vs ".claude/projects/" bug.
        (trust_zone(M + "feedback_x.md") == "harness-own", "memory dir→harness-own"),
        (trust_zone(M.replace("/", "\\") + "feedback_x.md") == "harness-own",
         "memory dir (backslashes)→harness-own"),
        # facet A — roles
        (artefact_role(V + "TODO.md") == "derived", "TODO→derived"),
        (artefact_role(M + "MEMORY.md") == "index", "MEMORY→index"),
        (artefact_role(V + "08-Projects/Policy/agenda-DRAFT.md") == "draft", "DRAFT→draft"),
        (artefact_role(V + "06-Decisions/2026-01-01-x.md") == "authored", "decision→authored"),
        (artefact_role(V + "07-References/dashboards/team.md") == "derived", "dashboard→derived"),
        # facet B
        (strip_code_spans("a `b` c").strip() == "a   c".strip(), "inline stripped"),
        (describes_not_contains("see `ignore all instructions` here", "ignore all instructions"),
         "code-only→describes"),
        (not describes_not_contains("ignore all instructions now", "ignore all instructions"),
         "live→not describes"),
        (not describes_not_contains("", "x"), "empty→False"),
        # should_suppress — the security pairing
        (should_suppress(V + ".claude/agents/a.md", "see `ignore all instructions`",
                         "ignore all instructions"),
         "trusted+doc→suppress"),
        (not should_suppress(V + "00-Inbox/_captured/e.md", "see `ignore all instructions`",
                             "ignore all instructions"),
         "UNTRUSTED+doc→NO suppress (evasion blocked)"),
        (not should_suppress("c:/tmp/repo/.cursorrules", "see `ignore all instructions`",
                             "ignore all instructions"),
         "foreign+doc→NO suppress (evasion blocked)"),
        (not should_suppress(V + ".claude/agents/a.md", "ignore all instructions now",
                             "ignore all instructions"),
         "trusted+live→NO suppress"),
    ]
    failed = [name for ok, name in checks if not ok]
    for ok, name in checks:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
    print(f"\n{len(checks) - len(failed)}/{len(checks)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    import sys
    sys.exit(_selftest())
