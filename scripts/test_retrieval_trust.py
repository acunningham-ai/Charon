"""Safety tests for prompt-conditioned retrieval.

The retrieval index feeds EVERY prompt, so the property that matters is not
"does it find things" but "can untrusted content reach the context". Two
independent filters enforce that, and this test asserts both — plus that they
agree, since a silent divergence is how a two-filter design degrades into one.

  1. build_memory_retrieval_index.py::CAPTURE_PROVENANCE — used at index build
  2. _provenance.py::trust_zone()                        — used by the hooks

They are deliberately NOT the same code path. The index must not inherit a change
in a shared primitive's semantics by accident.

WHY PROVENANCE AND NOT PATH. A note gets filed by topic, not by where it came
from. On the reference deployment 320 capture-sourced notes were sitting inside
the "authored" zones — 05-Meetings, 03-Domains, 08-Projects. "Authored content
elsewhere in the vault is trusted" does not hold as a path rule, so a path-only
filter would have fed calendar invites and meeting transcripts into every prompt.

NOTE ON FILTER #1: this test IMPORTS the builder's regex rather than restating
it. An earlier version kept its own third copy of the token list, which could
drift from the builder without anything noticing — the exact failure this file's
own docstring warns about. Importing also means the test tracks whatever you add
to capture-provenance-config.json, instead of silently testing the defaults.

Run: python scripts/test_retrieval_trust.py
Exit: 0 = pass (or skipped because no index is built), 1 = a real failure.
"""
import io
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE / "lib"))
sys.path.insert(0, str(HERE / "hooks"))
sys.path.insert(0, str(HERE))

FRONTMATTER = re.compile(r"\A\s*---\r?\n(.*?)\r?\n---", re.S)


def _builder():
    """The index builder, loaded as a module.

    Both the vault root and the capture filter are taken FROM IT rather than
    restated here, so this test can never assert against a different tree or a
    different token list than the thing it is testing. Note the builder defines
    its own `vault_root()` (co-located install: the vault IS the repo) which
    shadows the env-var-aware helper in scripts/lib/harness_paths.py — reading
    it from the builder means this test follows whichever one is live.
    """
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_bmri", HERE / "build_memory_retrieval_index.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def declares_capture(path, capture):
    try:
        head = io.open(path, encoding="utf-8", errors="replace").read(1500)
    except Exception:
        return True  # unreadable -> assume capture -> fail CLOSED
    block = FRONTMATTER.match(head)
    return bool(block and capture.search(block.group(1)))


def main():
    failures = []

    try:
        bmri = _builder()
        VAULT = bmri.vault_root()
        capture = bmri.CAPTURE_PROVENANCE
    except Exception as exc:
        print("FAIL: could not load the index builder: %s" % exc)
        return 1

    INDEX = VAULT / ".charon" / "memory-retrieval-index.json"
    if not INDEX.is_file():
        print("SKIP: index not built — run scripts/build_memory_retrieval_index.py")
        return 0

    index = json.loads(io.open(INDEX, encoding="utf-8").read())
    entries = index.get("entries") or {}
    vault_entries = {k: v for k, v in entries.items() if v.get("kind") == "vault"}

    # 1. No indexed vault note may declare capture provenance.
    leaks = [k for k in vault_entries
             if (VAULT / k).is_file() and declares_capture(VAULT / k, capture)]
    if leaks:
        failures.append("%d capture-sourced notes in the index, e.g. %s"
                        % (len(leaks), leaks[:3]))

    # 2. No indexed entry may come from an excluded zone.
    zoned = [k for k in entries if k.startswith(("00-Inbox", "09-Archive"))]
    if zoned:
        failures.append("%d entries from excluded zones, e.g. %s" % (len(zoned), zoned[:3]))

    # 3. Every indexed vault note must still exist (a stale index points at
    #    content that may since have been replaced).
    missing = [k for k in vault_entries if not (VAULT / k).is_file()]
    if missing:
        failures.append("%d indexed notes no longer exist, e.g. %s"
                        % (len(missing), missing[:3]))

    # 4. The two filters must agree: anything trust_zone calls untrusted must
    #    not be in the index.
    try:
        from _provenance import trust_zone
    except Exception as exc:
        failures.append("could not import trust_zone: %s" % exc)
        trust_zone = None

    disagreements = []
    if trust_zone is not None:
        for k in vault_entries:
            p = VAULT / k
            if not p.is_file():
                continue
            if trust_zone(str(p)) == "untrusted-capture":
                disagreements.append(k)
        if disagreements:
            failures.append(
                "%d indexed notes that trust_zone calls untrusted-capture, e.g. %s"
                % (len(disagreements), disagreements[:3]))

    # 5. trust_zone must actually catch a capture-sourced file sitting in an
    #    AUTHORED zone. Guards against a silent regression to path-only
    #    behaviour, which is the whole reason the frontmatter check exists.
    #
    #    The probe must live INSIDE the vault. trust_zone returns "foreign" for
    #    anything outside the project root and returns it BEFORE reading
    #    frontmatter, so a probe in the system temp dir would fail this check
    #    while the code under test is perfectly healthy — a false alarm, not a
    #    finding.
    if trust_zone is not None:
        zone = VAULT / "05-Meetings"
        if not zone.is_dir():
            zone = VAULT
        probe = None
        try:
            probe = Path(tempfile.mkdtemp(prefix="trust-probe-", dir=str(zone)))
            cap = probe / "captured.md"
            cap.write_text("---\nsource: m365-calendar\n---\n\nnotes\n", encoding="utf-8")
            auth = probe / "authored.md"
            auth.write_text("---\ntype: meeting\n---\n\nnotes\n", encoding="utf-8")
            if trust_zone(str(probe)) == "foreign":
                failures.append(
                    "probe dir %s classified foreign — cannot test the frontmatter "
                    "downgrade; check _provenance._project_root()" % probe)
            else:
                if trust_zone(str(cap)) != "untrusted-capture":
                    failures.append(
                        "trust_zone regressed to path-only: capture frontmatter not caught")
                if trust_zone(str(auth)) != "vault-authored":
                    failures.append("trust_zone over-reaches: authored note misclassified")
        except Exception as exc:
            failures.append("could not run the trust_zone probe: %r" % exc)
        finally:
            if probe is not None:
                shutil.rmtree(probe, ignore_errors=True)

    # 6. The imported filter must be live, not an empty or broken pattern — a
    #    regex matching nothing would make checks 1 and 4 vacuously pass.
    if not capture.search("source: m365-calendar\n"):
        failures.append("capture filter does not match a known built-in marker; "
                        "checks 1 and 4 would pass vacuously")

    print("indexed vault notes : %d" % len(vault_entries))
    print("capture-sourced     : %d" % len(leaks))
    print("excluded-zone       : %d" % len(zoned))
    print("missing on disk     : %d" % len(missing))
    print("filter disagreement : %d" % len(disagreements))
    print()
    if failures:
        for f in failures:
            print("FAIL: %s" % f)
        return 1
    print("PASS: no untrusted content reachable via retrieval; filters agree")
    return 0


if __name__ == "__main__":
    sys.exit(main())
