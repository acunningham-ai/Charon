"""Regression tests for the three MEMORY.md guards in scripts/hooks/deny-destructive.py.

  memory-index-content-write  -- a write that puts a 3+ line PROSE BLOCK into MEMORY.md
  memory-index-line-budget    -- a bullet whose prose (links stripped) runs past 120 bytes
  memory-index-total-ceiling  -- a growing write that takes MEMORY.md past 16 KB

Why prose burden and not line length: a row of twenty pointers can be a very long
line carrying almost no prose. A line-byte cap would flag it, and its only "fix" is
deleting pointers, i.e. destroying index coverage. The essays are what we want
caught. Case `pointer_row_passes` pins that distinction.

Self-contained: every case runs against a FIXTURE MEMORY.md in a temporary project
directory, never your real one, and every hook call sets HARNESS_HOOK_TEST=1 so its
verdicts land in state/verdict/_test/ instead of the production log. A missing
precondition is a FAILURE, never a skip: a test that cannot run must not read as
a pass.

Run: python scripts/test_memory_index_budget.py      (exit 0 = all passed)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "hooks", "deny-destructive.py")

ALLOW, BLOCK = 0, 2

FAT_BULLET = (
    "- [Some thing](project_x.md) — this is a long editorial paragraph that belongs "
    "in the memory file itself rather than the index, because it is content and not "
    "a pointer with a short hook attached to it"
)
OK_BULLET = "- [Some thing](project_x.md) — short hook, well under budget"
POINTER_ROW = "- " + " · ".join(
    "[Pointer %d](feedback_thing_number_%d.md)" % (i, i) for i in range(20)
)
PROSE_BLOCK = "paragraph one\nparagraph two\nparagraph three"

# A realistic, compliant index: a heading, short pointer bullets, one long-ish
# bullet whose tail serves as the mid-line fragment for the partial-Edit cases.
FIXTURE = "\n".join(
    ["# Memory index", "", "## Pickups"]
    + ["- [Topic %d](project_topic_%d.md) — short hook %d" % (i, i, i) for i in range(12)]
    + ["- [Release checklist](reference_release_checklist.md) — gates, tag, release page, site"]
    + ["", "## Everything else", "- [Catalog](reference_memory_catalog_index.md) — every pointer"]
) + "\n"
FRAGMENT = "gates, tag, release page, site"


def run_hook(project_dir, tool_name, tool_input):
    payload = {
        "tool_name": tool_name,
        "session_id": "test-memory-index-budget",
        "tool_input": tool_input,
    }
    env = dict(os.environ, HARNESS_HOOK_TEST="1", CLAUDE_PROJECT_DIR=project_dir)
    proc = subprocess.run(
        [sys.executable, HOOK],
        input=json.dumps(payload),
        capture_output=True, text=True, encoding="utf-8",
        cwd=project_dir, env=env,
    )
    return proc.returncode, (proc.stderr or "")


def write_token(project_dir, rule_id):
    state = os.path.join(project_dir, "state")
    os.makedirs(state, exist_ok=True)
    with open(os.path.join(state, "policy-confirm.json"), "w", encoding="utf-8") as fh:
        json.dump({"rule_id": rule_id, "issued_epoch": time.time(), "granted_by": "test"}, fh)


def clear_token(project_dir):
    p = os.path.join(project_dir, "state", "policy-confirm.json")
    if os.path.exists(p):
        os.remove(p)


def main():
    if not os.path.isfile(HOOK):
        print("FAIL: hook not found at %s" % HOOK)
        return 1

    project = tempfile.mkdtemp(prefix="charon-memidx-")
    try:
        mem_dir = os.path.join(project, "memory")
        os.makedirs(mem_dir)
        mem = os.path.join(mem_dir, "MEMORY.md")
        with open(mem, "w", encoding="utf-8") as fh:
            fh.write(FIXTURE)
        live = FIXTURE
        if FRAGMENT not in live:
            print("FAIL: fixture is missing the fragment the partial-Edit cases need")
            return 1

        cases = [
            # (name, tool, tool_input, expected_exit, expected_rule_in_stderr, token_rule)
            ("fat new bullet blocked",
             "Edit", {"file_path": mem, "new_string": FAT_BULLET},
             BLOCK, "memory-index-line-budget", None),
            ("compliant bullet allowed",
             "Edit", {"file_path": mem, "new_string": OK_BULLET}, ALLOW, None, None),
            # The load-bearing case: a very long LINE holding almost no prose must pass.
            ("pointer_row_passes",
             "Edit", {"file_path": mem, "new_string": POINTER_ROW}, ALLOW, None, None),
            ("prose block blocked",
             "Edit", {"file_path": mem, "new_string": PROSE_BLOCK},
             BLOCK, "memory-index-content-write", None),
            # A full-file rewrite must not be blocked by lines it merely carries through.
            ("file rewritten verbatim allowed",
             "Write", {"file_path": mem, "content": live}, ALLOW, None, None),
            ("file plus one fat bullet blocked",
             "Write", {"file_path": mem, "content": live + "\n" + FAT_BULLET},
             BLOCK, "memory-index-line-budget", None),
            ("non-MEMORY target unaffected",
             "Edit", {"file_path": os.path.join(mem_dir, "not-memory.md"),
                      "new_string": FAT_BULLET}, ALLOW, None, None),
            # An Edit whose new_string is a mid-line FRAGMENT is not itself a bullet;
            # the hook reconstructs the resulting text so it is measured as a whole line.
            ("fragment edit that inflates a bullet is blocked",
             "Edit", {"file_path": mem, "old_string": FRAGMENT,
                      "new_string": FRAGMENT + " " + "x" * 200},
             BLOCK, "memory-index-line-budget", None),
            ("fragment edit that keeps a bullet compliant is allowed",
             "Edit", {"file_path": mem, "old_string": FRAGMENT,
                      "new_string": FRAGMENT}, ALLOW, None, None),
            # When old_string does not match the file, `replace` silently no-ops; a
            # whole-line bullet in the payload must still be caught.
            ("unmatched old_string still measures a whole-line bullet",
             "Edit", {"file_path": mem, "old_string": "!! this text is not in the file !!",
                      "new_string": FAT_BULLET}, BLOCK, "memory-index-line-budget", None),
            # Many COMPLIANT bullets that together push the file past 16 KB must ask.
            ("compliant bullets that cross the total ceiling are blocked",
             "Write", {"file_path": mem, "content": live + "\n" + "\n".join(
                 "- [Filler %d](filler_%d.md) — short hook" % (i, i) for i in range(500))},
             BLOCK, "memory-index-total-ceiling", None),
            ("shrinking rewrite is never blocked by the ceiling",
             "Write", {"file_path": mem, "content": live[: len(live) // 2]}, ALLOW, None, None),
            # The answer channel: an ask must be answerable.
            ("token for the matching rule unlocks the write",
             "Edit", {"file_path": mem, "new_string": FAT_BULLET},
             ALLOW, None, "memory-index-line-budget"),
            ("token for a different rule does not unlock it",
             "Edit", {"file_path": mem, "new_string": FAT_BULLET},
             BLOCK, "memory-index-line-budget", "memory-index-content-write"),
        ]

        failed = 0
        for name, tool, tool_input, want_exit, want_rule, token_rule in cases:
            clear_token(project)
            if token_rule:
                write_token(project, token_rule)
            code, err = run_hook(project, tool, tool_input)
            ok = code == want_exit
            if ok and want_rule:
                ok = want_rule in err
            if not ok:
                failed += 1
            print("[%s] %s (exit %s, wanted %s)"
                  % ("PASS" if ok else "FAIL", name, code, want_exit))
            if not ok and err.strip():
                print("       " + err.strip().replace("\n", "\n       ")[:400])
        clear_token(project)

        print("\n%d/%d passed" % (len(cases) - failed, len(cases)))
        return 1 if failed else 0
    finally:
        shutil.rmtree(project, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
