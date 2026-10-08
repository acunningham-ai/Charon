"""Regression tests for scripts/memory_working_set.py, on synthetic fixtures.

Never touches your real memory directory: every case builds a throwaway one and
points HARNESS_MEMORY_ROOT at it. Covers:
  * topic sections move to the catalog and MEMORY.md shrinks
  * score-vault counts exactly the same files as indexed before and after
    (the proof that nothing became unfindable)
  * the 16 KB ceiling holds on an inflated file while every 🔴 pickup is kept,
    and overflow is moved to the catalog, never deleted
  * rebuilds are idempotent
  * a pointer appended at the end of the file (inside a generated block) migrates
  * no commitments register is reported plainly, not as an error

Run: python scripts/test_memory_working_set.py   (exit 0 = all pass)
"""
import importlib.util
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO = Path(__file__).resolve().parent.parent
ok = total = 0


def check(label, cond):
    global ok, total
    total += 1
    ok += bool(cond)
    print(("PASS " if cond else "FAIL ") + label)


def load(name, rel, memdir):
    os.environ["HARNESS_MEMORY_ROOT"] = str(memdir)
    spec = importlib.util.spec_from_file_location(name, REPO / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def fixture(extra_pickups=0):
    d = Path(tempfile.mkdtemp())
    topics = {"Working discipline": 20, "Projects": 25, "People": 10, "Tooling": 15}
    lines = ["# Memory index", "", "Prior sessions: check `sessions/*.md`.", "",
             "## 📌 Pickups (read first)",
             "- ⭐🔴 [Backup not tested](bugs_backup_untested.md) — restore before the laptop swap",
             "- 🔴 [Renewal due](project_renewal.md) — sign by Friday",
             "- ⚠️ [Access review open](project_access_review.md) — new-style urgent mark",
             "- ⭐ [Release plan](project_release.md) — next minor"]
    lines += ["- [Follow-up %d](followup_%d.md) — routine item %d" % (i, i, i) for i in range(extra_pickups)]
    n = 0
    for topic, count in topics.items():
        lines += ["", "## " + topic]
        for _ in range(count):
            name = "note_%03d.md" % n
            lines.append("- [Note %d](%s) — pointer for topic %s" % (n, name, topic.lower()))
            (d / name).write_text("---\nname: n%d\ndescription: \"how the note %d decision was made for %s\"\n"
                                  "metadata:\n  type: project\n---\nBody of note %d about %s.\n"
                                  % (n, n, topic.lower(), n, topic.lower()), encoding="utf-8")
            n += 1
    for f in ("bugs_backup_untested.md", "project_renewal.md", "project_release.md"):
        (d / f).write_text("---\nname: x\ndescription: \"a pickup memory used by the test\"\n"
                           "metadata:\n  type: project\n---\nbody\n", encoding="utf-8")
    (d / "MEMORY.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return d


# 1. Normal migration, score-vault coverage unchanged.
d = fixture()
sv = load("sv", "scripts/score-vault.py", d)
before = sv.indexed_memory_names() & sv.ondisk_memory_names()
ws = load("ws", "scripts/memory_working_set.py", d)
r = ws.build(date.today())
(d / "MEMORY.md").write_text(r["new"], encoding="utf-8")
(d / ws.CATALOG_NAME).write_text(r["catalog"], encoding="utf-8")
sv2 = load("sv2", "scripts/score-vault.py", d)
after = sv2.indexed_memory_names() & sv2.ondisk_memory_names()
check("MEMORY.md shrank (%d -> %d bytes)" % (r["old_bytes"], r["new_bytes"]), r["new_bytes"] < r["old_bytes"])
check("topic pointers now live in the catalog", "note_069.md" in r["catalog"] and "note_069.md" not in r["new"])
check("no link target lost", not r["lost"])
check("score-vault indexed set unchanged (%d before, %d after, catalog itself +1)"
      % (len(before), len(after)), before <= after and len(after - before) <= 1)
check("catalog has a real description (so it is findable itself)", 'description: "Where is the full list' in r["catalog"])
check("no register reported plainly, not as an error", "No commitments register yet" in r["new"])

# 2. Idempotent.
r2 = ws.build(date.today())
check("second run changes nothing", r2["new"] == r["new"] and r2["catalog"] == r["catalog"])

# 3. Appended pointer (where an assistant's auto-memory puts it) migrates.
(d / "MEMORY.md").write_text(r["new"] + "- [New](feedback_new.md) — appended at the end\n", encoding="utf-8")
r3 = ws.build(date.today())
check("pointer appended into a generated block migrates",
      "feedback_new.md" in r3["catalog"] and "feedback_new.md" not in r3["new"] and not r3["lost"])

# 4. Ceiling on an inflated file.
d4 = fixture(extra_pickups=600)
ws4 = load("ws4", "scripts/memory_working_set.py", d4)
r4 = ws4.build(date.today())
check("inflated input is over the ceiling (%d bytes)" % r4["old_bytes"], r4["old_bytes"] > ws4.CEILING_BYTES)
check("output under the ceiling (%d <= %d)" % (r4["new_bytes"], ws4.CEILING_BYTES), r4["new_bytes"] <= ws4.CEILING_BYTES)
check("every 🔴 pickup kept", "bugs_backup_untested.md" in r4["new"] and "project_renewal.md" in r4["new"])
check("a ⚠️ pickup is urgent too and is kept", "project_access_review.md" in r4["new"])
check("overflow moved, not deleted", r4["overflow"] > 0 and "followup_599.md" in r4["catalog"] and not r4["lost"])

print("%d/%d pass" % (ok, total))
raise SystemExit(0 if ok == total else 1)
