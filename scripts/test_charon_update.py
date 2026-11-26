#!/usr/bin/env python3
"""Tests for scripts/update/charon_update.py (the /charon-update engine).

    python scripts/test_charon_update.py

Never touches the network and never touches this Charon folder's own files:
every git repo is a throwaway fixture in a temp folder, cloned by local file
path, with the user's global and system git config switched off (so no user
hooks, credential helpers or URL rewrites apply), and only the `file`
protocol allowed. urllib is blocked for the whole run.

What it proves:
  - vendored corpus: a pre-flight miss, a copy that fails halfway, and a swap
    that fails halfway all leave the destination byte-identical (negative);
    a good update swaps every path in and rewrites the SHA pins (positive);
  - review fixes (backlog row 49, W2e): a link in the upstream tree is
    refused (S1); Ctrl-C at any rename rolls back (A1); EOF or no terminal
    is a no (D2); a clone past the approved commit is refused or re-asked,
    and the approved commit is what lands (S3); destinations outside the
    allowlist, '.git' in any case and nested destinations are refused; bad
    repo, branch and name values are refused; the read-only temp clone is
    removed;
  - smokes starting with `python` run on this interpreter (sys.executable);
  - self-update: a modified tracked file blocks (negative); untracked-only
    proceeds with a warning (positive) and the pull lands;
  - post-update wiring: a stub that exits 0 reads as wired, one that exits 1
    is reported loudly, and a missing script is a loud warning;
  - menu duplicates: no command merely wraps a skill that still shows in the
    `/` menu (fixture positive + negative, then the real tree).

Exit 0 when every test passes, 1 otherwise.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import traceback
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
UPDATER = REPO / "scripts" / "update" / "charon_update.py"

OLD_SHA = "a" * 40
SHORT_OLD = OLD_SHA[:7]


# ---------------- isolation ----------------

_ISOLATION = Path(tempfile.mkdtemp(prefix="charon-update-test-env-"))
_EMPTY_GITCONFIG = _ISOLATION / "empty.gitconfig"
_EMPTY_GITCONFIG.write_text("", encoding="utf-8")
os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
os.environ["GIT_CONFIG_GLOBAL"] = str(_EMPTY_GITCONFIG)
os.environ["GIT_ALLOW_PROTOCOL"] = "file"
os.environ["GIT_TERMINAL_PROMPT"] = "0"
for _k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
    os.environ.pop(_k, None)


def _no_network(*_a, **_k):
    raise AssertionError("test tried to reach the network")


urllib.request.urlopen = _no_network  # type: ignore[assignment]


def _load_updater():
    spec = importlib.util.spec_from_file_location("charon_update_under_test", UPDATER)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


cu = _load_updater()
_REAL = {name: getattr(cu, name) for name in (
    "REPO_ROOT", "_copy_one", "_move", "_clone_url", "_fetch_github_branch_sha",
    "_run_scaffold_ensure", "_whats_new_after_update", "_prompt_yes_no")}


def _restore() -> None:
    for name, value in _REAL.items():
        setattr(cu, name, value)


def _rmtree(path: Path) -> None:
    def _onerr(func, p, _exc):
        try:
            os.chmod(p, stat.S_IWRITE)
            func(p)
        except OSError:
            pass
    if path.exists():
        shutil.rmtree(path, onerror=_onerr)


@contextlib.contextmanager
def _tmp(tag: str):
    d = Path(tempfile.mkdtemp(prefix=f"charon-update-test-{tag}-"))
    try:
        yield d
    finally:
        _restore()
        _rmtree(d)


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=Charon Test", "-c", "user.email=test@example.invalid",
         "-c", "commit.gpgsign=false", "-c", "core.hooksPath=" + str(_ISOLATION / "no-hooks"),
         *args],
        cwd=str(cwd), check=True, capture_output=True, text=True).stdout


def make_repo(path: Path, files: dict) -> str:
    path.mkdir(parents=True, exist_ok=True)
    write_files(path, files)
    git(path, "init", "-q", "-b", "main")
    git(path, "add", "-A")
    git(path, "commit", "-q", "-m", "fixture")
    return git(path, "rev-parse", "HEAD").strip()


def write_files(root: Path, files: dict) -> None:
    for rel, content in files.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(content.encode("utf-8") if isinstance(content, str) else content)


def snapshot(root: Path) -> dict:
    """Every file (bytes) and folder under root, .git excluded."""
    snap = {}
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != ".git"]
        rel_dir = Path(dirpath).relative_to(root).as_posix()
        snap[f"dir:{rel_dir}"] = None
        for f in filenames:
            p = Path(dirpath) / f
            snap[(Path(rel_dir) / f).as_posix()] = p.read_bytes()
    return snap


# ---------------- vendored fixtures ----------------

# Fixture destinations sit under the same prefix the updater allows for real
# (cerberus/rules/), so the tests exercise the shipped allowlist, not a bypass.
LOCAL_FILES = {
    "cerberus/rules/packs/a.yaml": "old a\n",
    "cerberus/rules/packs/stale.yaml": "only in the old corpus\n",
    "cerberus/rules/policies/default.yaml": "old default\n",
    "NOTICE": f"Vendored at SHA {OLD_SHA} (short {SHORT_OLD}).\n",
    "cerberus/rules/README.md": f"pinned sha: {OLD_SHA}\n",
    "keep/user-notes.md": "not part of the corpus\n",
}
UPSTREAM_FILES = {
    "data/packs/a.yaml": "new a\n",
    "data/packs/b.yaml": "new b\n",
    "data/policies/default.yaml": "new default\n",
    "data/prompts/p.md": "new prompt\n",
}


def vendored_source(smoke: str | None = None) -> dict:
    src = {
        "name": "fixture-corpus",
        "type": "github-vendored",
        "repo": "example/upstream",
        "branch": "main",
        "copy_paths": [
            {"from": "data/packs/", "to": "cerberus/rules/packs/"},
            {"from": "data/policies/default.yaml", "to": "cerberus/rules/policies/default.yaml"},
            {"from": "data/prompts/", "to": "cerberus/rules/prompts/"},
        ],
        "sha_pin_files": ["NOTICE", "cerberus/rules/README.md"],
    }
    if smoke:
        src["post_update_smoke"] = smoke
    return src


def _assert_no_temp_siblings(root: Path) -> None:
    left = [p for p in root.rglob("*") if ".charon-update-" in p.name]
    assert not left, f"temp siblings left behind: {left}"


# ---------------- tests: vendored corpus ----------------

def test_preflight_missing_source_changes_nothing() -> None:
    """NEGATIVE: upstream moved a file. Pre-flight stops before any write."""
    with _tmp("preflight") as d:
        local, up = d / "local", d / "up"
        write_files(local, LOCAL_FILES)
        files = dict(UPSTREAM_FILES)
        files.pop("data/policies/default.yaml")
        files["data/policies/moved/default.yaml"] = "moved\n"
        write_files(up, files)
        before = snapshot(local)
        try:
            cu.apply_vendored_copy(vendored_source(), up, OLD_SHA, "b" * 40, repo_root=local)
        except cu.UpdateAborted as exc:
            assert "pre-flight" in str(exc) and "data/policies/default.yaml" in str(exc), exc
        else:
            raise AssertionError("pre-flight did not abort on a missing upstream file")
        assert snapshot(local) == before, "destination changed after a pre-flight failure"


def test_preflight_refuses_escaping_paths() -> None:
    """NEGATIVE: a manifest path with '..' or an absolute path is refused."""
    with _tmp("escape") as d:
        local, up = d / "local", d / "up"
        write_files(local, LOCAL_FILES)
        write_files(up, UPSTREAM_FILES)
        before = snapshot(local)
        for bad in ({"from": "data/packs/", "to": "../outside/"},
                    {"from": "../../etc/", "to": "rules/x/"},
                    {"from": "data/packs/", "to": ".git/hooks/"}):
            src = vendored_source()
            src["copy_paths"] = [bad]
            try:
                cu.apply_vendored_copy(src, up, OLD_SHA, "b" * 40, repo_root=local)
            except cu.UpdateAborted:
                pass
            else:
                raise AssertionError(f"unsafe copy path accepted: {bad}")
        assert snapshot(local) == before
        assert not (d / "outside").exists()


def test_copy_failing_halfway_leaves_destination_identical() -> None:
    """NEGATIVE: the second copy raises mid-way. Every destination and pin is
    byte-identical afterwards, and no temp sibling is left behind."""
    with _tmp("halfcopy") as d:
        local, up = d / "local", d / "up"
        write_files(local, LOCAL_FILES)
        write_files(up, UPSTREAM_FILES)
        before = snapshot(local)
        calls = {"n": 0}
        real = _REAL["_copy_one"]

        def flaky(src, staged, kind):
            calls["n"] += 1
            if calls["n"] == 2:
                staged.write_bytes(b"partial")  # half-written copy, then the disk fails
                raise OSError("simulated disk error during copy")
            return real(src, staged, kind)

        cu._copy_one = flaky
        try:
            cu.apply_vendored_copy(vendored_source(), up, OLD_SHA, "b" * 40, repo_root=local)
        except cu.UpdateAborted as exc:
            assert "simulated disk error" in str(exc), exc
        else:
            raise AssertionError("a failing copy did not abort the update")
        assert calls["n"] == 2
        assert snapshot(local) == before, "destination not byte-identical after a failed copy"
        _assert_no_temp_siblings(local)


def test_swap_failing_halfway_rolls_back() -> None:
    """NEGATIVE: the swap of the second path fails after the first path was
    already swapped in. The first is rolled back; the tree is byte-identical."""
    with _tmp("halfswap") as d:
        local, up = d / "local", d / "up"
        write_files(local, LOCAL_FILES)
        write_files(up, UPSTREAM_FILES)
        before = snapshot(local)
        calls = {"n": 0}
        real = _REAL["_move"]

        def flaky(a, b):
            calls["n"] += 1
            # move 1: old packs aside, move 2: new packs in,
            # move 3: old default.yaml aside, move 4: new default.yaml in -> fail
            if calls["n"] == 4:
                raise OSError("simulated rename failure")
            return real(a, b)

        cu._move = flaky
        try:
            cu.apply_vendored_copy(vendored_source(), up, OLD_SHA, "b" * 40, repo_root=local)
        except cu.UpdateAborted as exc:
            assert "simulated rename failure" in str(exc), exc
            assert "INCOMPLETE" not in str(exc), exc
        else:
            raise AssertionError("a failing swap did not abort the update")
        assert snapshot(local) == before, "destination not byte-identical after a failed swap"
        _assert_no_temp_siblings(local)


def test_good_update_swaps_and_repins() -> None:
    """POSITIVE: the real apply path (clone by local file URL -> pre-flight ->
    stage -> swap -> re-pin -> smoke). New corpus lands, stale file is gone,
    the user's other files are untouched, pins carry the new SHA."""
    with _tmp("good") as d:
        local, up = d / "local", d / "up"
        write_files(local, LOCAL_FILES)
        new_sha = make_repo(up, UPSTREAM_FILES)
        cu.REPO_ROOT = local
        cu._clone_url = lambda _repo: up.as_uri()
        status = {"repo": "example/upstream", "branch": "main",
                  "upstream_sha": new_sha, "pinned_sha": OLD_SHA}
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            result = cu._apply_github_vendored(vendored_source(smoke="python --version"), status,
                                               interactive=False)
        assert result.get("applied") is True, result
        assert result["new_sha"] == new_sha
        assert result["smoke_ok"] is True, result
        assert (local / "cerberus/rules/packs/a.yaml").read_text() == "new a\n"
        assert (local / "cerberus/rules/packs/b.yaml").read_text() == "new b\n"
        assert not (local / "cerberus/rules/packs/stale.yaml").exists(), \
            "old corpus file survived the swap"
        assert (local / "cerberus/rules/policies/default.yaml").read_text() == "new default\n"
        assert (local / "cerberus/rules/prompts/p.md").read_text() == "new prompt\n"
        assert (local / "keep/user-notes.md").read_text() == "not part of the corpus\n"
        notice = (local / "NOTICE").read_text()
        assert new_sha in notice and new_sha[:7] in notice and OLD_SHA not in notice, notice
        assert new_sha in (local / "cerberus/rules/README.md").read_text()
        assert sum(p["replaced"] for p in result["sha_pins_rewritten"]) == 3, result
        _assert_no_temp_siblings(local)
        assert sys.executable in out.getvalue(), "python smoke did not run on sys.executable"


def test_failed_clone_changes_nothing() -> None:
    """NEGATIVE: the clone fails (bad local URL). Nothing changes."""
    with _tmp("badclone") as d:
        local = d / "local"
        write_files(local, LOCAL_FILES)
        before = snapshot(local)
        cu.REPO_ROOT = local
        cu._clone_url = lambda _repo: (d / "does-not-exist").as_uri()
        status = {"repo": "example/upstream", "branch": "main",
                  "upstream_sha": "c" * 40, "pinned_sha": OLD_SHA}
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = cu._apply_github_vendored(vendored_source(), status, interactive=False)
        assert result.get("applied") is False and "clone failed" in result["reason"], result
        assert snapshot(local) == before


# ---------------- tests: review fixes (backlog row 49, W2e) ----------------

def _make_link(link: Path, target: Path, is_dir: bool) -> bool:
    """Create a symlink. False when this OS or account may not create one."""
    try:
        link.parent.mkdir(parents=True, exist_ok=True)
        os.symlink(target, link, target_is_directory=is_dir)
        return True
    except (OSError, NotImplementedError):
        return False


def test_symlink_in_upstream_tree_is_refused() -> None:
    """NEGATIVE (S1): a link nested inside an upstream folder points at a local
    file or folder outside the clone. The update is refused before any write,
    and the local bytes never land in the repo."""
    made = 0
    for i, (rel, is_dir) in enumerate((("data/packs/leak.yaml", False),
                                       ("data/prompts/deep/sub", True))):
        with _tmp(f"symlink{i}") as d:
            local, up = d / "local", d / "up"
            write_files(local, LOCAL_FILES)
            write_files(up, UPSTREAM_FILES)
            write_files(d, {"outside/private.txt": "LOCAL-ONLY-BYTES\n"})
            target = d / "outside" / ("" if is_dir else "private.txt")
            if not _make_link(up / rel, target, is_dir):
                continue
            made += 1
            before = snapshot(local)
            try:
                cu.apply_vendored_copy(vendored_source(), up, OLD_SHA, "b" * 40, repo_root=local)
            except cu.UpdateAborted as exc:
                assert "link" in str(exc).lower(), exc
            else:
                raise AssertionError(f"a link in the upstream tree was accepted: {rel}")
            after = snapshot(local)
            assert after == before, "destination changed after a refused link"
            assert not any(isinstance(v, bytes) and b"LOCAL-ONLY-BYTES" in v
                           for v in after.values()), "local file bytes were copied in"
            _assert_no_temp_siblings(local)
    if made == 0:
        print("    note: this OS refused to create symlinks; link cases covered by "
              "test_link_walk_checks_every_entry only")


def test_link_walk_checks_every_entry() -> None:
    """NEGATIVE (S1), no symlink privilege needed: the pre-flight walk asks the
    link check about every nested entry, and one flagged entry refuses the run."""
    with _tmp("linkwalk") as d:
        local, up = d / "local", d / "up"
        write_files(local, LOCAL_FILES)
        write_files(up, dict(UPSTREAM_FILES, **{"data/prompts/deep/er/x.md": "x\n"}))
        before = snapshot(local)
        real = cu._is_link
        flagged = up / "data" / "prompts" / "deep" / "er"
        cu._is_link = lambda p: Path(p) == flagged or real(p)
        try:
            cu.apply_vendored_copy(vendored_source(), up, OLD_SHA, "b" * 40, repo_root=local)
        except cu.UpdateAborted as exc:
            assert "link" in str(exc).lower() and "deep" in str(exc), exc
        else:
            raise AssertionError("a flagged nested entry was not refused")
        finally:
            cu._is_link = real
        assert snapshot(local) == before


def test_ctrl_c_mid_swap_rolls_back() -> None:
    """NEGATIVE (A1): Ctrl-C lands right after a rename, before the run could
    record it. Every case must still roll back to a byte-identical tree and let
    the KeyboardInterrupt through."""
    for at in (1, 2, 3, 4):
        with _tmp(f"ctrlc{at}") as d:
            local, up = d / "local", d / "up"
            write_files(local, LOCAL_FILES)
            write_files(up, UPSTREAM_FILES)
            before = snapshot(local)
            calls = {"n": 0}
            real = _REAL["_move"]

            def interrupted(a, b, _at=at):
                calls["n"] += 1
                real(a, b)
                if calls["n"] == _at:
                    raise KeyboardInterrupt

            cu._move = interrupted
            try:
                cu.apply_vendored_copy(vendored_source(), up, OLD_SHA, "b" * 40, repo_root=local)
            except KeyboardInterrupt:
                pass
            else:
                raise AssertionError(f"Ctrl-C after move {at} did not propagate")
            assert snapshot(local) == before, f"tree not restored after Ctrl-C at move {at}"
            _assert_no_temp_siblings(local)


class _FakeStdin(io.StringIO):
    def __init__(self, text: str, tty: bool) -> None:
        super().__init__(text)
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


def _ask(text: str, tty: bool, default_yes: bool = True) -> bool:
    real = sys.stdin
    sys.stdin = _FakeStdin(text, tty)
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            return cu._prompt_yes_no("Apply?", default_yes=default_yes)
    finally:
        sys.stdin = real


def test_prompt_says_no_on_eof_or_without_terminal() -> None:
    """NEGATIVE (D2): end of input, or no terminal at all, is never a yes.
    POSITIVE: a real answer on a terminal still works, Enter takes the default."""
    assert _ask("", tty=True) is False, "EOF approved the prompt"
    assert _ask("y\n", tty=False) is False, "a prompt with no terminal approved"
    assert _ask("", tty=False, default_yes=False) is False
    assert _ask("y\n", tty=True) is True
    assert _ask("yes\n", tty=True) is True
    assert _ask("\n", tty=True) is True
    assert _ask("n\n", tty=True) is False


def _two_commit_upstream(up: Path) -> tuple[str, str]:
    first = make_repo(up, UPSTREAM_FILES)
    write_files(up, {"data/packs/a.yaml": "newer a\n"})
    git(up, "add", "-A")
    git(up, "commit", "-q", "-m", "upstream moves on")
    return first, git(up, "rev-parse", "HEAD").strip()


def _vendored_status(sha: str) -> dict:
    return {"repo": "example/upstream", "branch": "main",
            "upstream_sha": sha, "pinned_sha": OLD_SHA}


def test_clone_past_approved_sha_is_refused_unattended() -> None:
    """NEGATIVE (S3): the approved commit cannot be checked out and the clone
    sits on another commit. A --yes run refuses; nothing changes."""
    with _tmp("moved") as d:
        local, up = d / "local", d / "up"
        write_files(local, LOCAL_FILES)
        _first, _head = _two_commit_upstream(up)
        before = snapshot(local)
        cu.REPO_ROOT = local
        cu._clone_url = lambda _repo: up.as_uri()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = cu._apply_github_vendored(vendored_source(), _vendored_status("d" * 40),
                                               interactive=False)
        assert result.get("applied") is False and "approved" in result.get("reason", ""), result
        assert snapshot(local) == before


def test_clone_past_approved_sha_reprompts() -> None:
    """NEGATIVE (S3), interactive: the clone moved on, so the user is asked
    again naming the new commit. Declining changes nothing; accepting applies
    the commit that was actually shown."""
    for answer in (False, True):
        with _tmp(f"reprompt{int(answer)}") as d:
            local, up = d / "local", d / "up"
            write_files(local, LOCAL_FILES)
            _first, head = _two_commit_upstream(up)
            before = snapshot(local)
            cu.REPO_ROOT = local
            cu._clone_url = lambda _repo: up.as_uri()
            asked: list = []
            answers = [True, answer]

            def scripted(prompt, default_yes=True):
                asked.append((prompt, default_yes))
                return answers.pop(0)

            cu._prompt_yes_no = scripted
            with contextlib.redirect_stdout(io.StringIO()), \
                    contextlib.redirect_stderr(io.StringIO()):
                result = cu._apply_github_vendored(vendored_source(), _vendored_status("d" * 40),
                                                   interactive=True)
            assert len(asked) == 2, asked
            assert head[:10] in asked[1][0] and asked[1][1] is False, asked
            if answer:
                assert result.get("applied") is True and result["new_sha"] == head, result
                assert (local / "cerberus/rules/packs/a.yaml").read_text() == "newer a\n"
            else:
                assert result.get("applied") is False, result
                assert snapshot(local) == before


def test_approved_older_commit_is_what_lands() -> None:
    """POSITIVE (S3): upstream moved on after approval. The approved commit is
    checked out and applied, not the newer clone head."""
    with _tmp("approved") as d:
        local, up = d / "local", d / "up"
        write_files(local, LOCAL_FILES)
        first, head = _two_commit_upstream(up)
        assert first != head
        cu.REPO_ROOT = local
        cu._clone_url = lambda _repo: up.as_uri()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            result = cu._apply_github_vendored(vendored_source(), _vendored_status(first),
                                               interactive=False)
        assert result.get("applied") is True and result["new_sha"] == first, result
        assert (local / "cerberus/rules/packs/a.yaml").read_text() == "new a\n"
        assert first in (local / "NOTICE").read_text()


def _refused(copy_paths: list, needle: str) -> None:
    with _tmp("dest") as d:
        local, up = d / "local", d / "up"
        write_files(local, LOCAL_FILES)
        write_files(up, UPSTREAM_FILES)
        before = snapshot(local)
        src = vendored_source()
        src["copy_paths"] = copy_paths
        try:
            cu.apply_vendored_copy(src, up, OLD_SHA, "b" * 40, repo_root=local)
        except cu.UpdateAborted as exc:
            assert needle in str(exc).lower(), (needle, str(exc))
        else:
            raise AssertionError(f"unsafe destination accepted: {copy_paths}")
        assert snapshot(local) == before, f"tree changed for {copy_paths}"


def test_destination_outside_allowlist_refused() -> None:
    """NEGATIVE: a to: outside the vendored-content prefixes is refused, even
    though it is inside the repo (scripts, docs, root files)."""
    _refused([{"from": "data/packs/", "to": "scripts/packs/"}], "allowed")
    _refused([{"from": "data/policies/default.yaml", "to": "README.md"}], "allowed")
    _refused([{"from": "data/packs/", "to": "cerberus/rulesX/"}], "allowed")
    _refused([{"from": "data/packs/", "to": "cerberus/rules/"}], "allowed")  # the prefix itself


def test_destination_case_folded_git_refused() -> None:
    """NEGATIVE: .git in any letter case, anywhere in to: or from:, is refused."""
    _refused([{"from": "data/packs/", "to": "cerberus/rules/.GIT/hooks/"}], ".git")
    _refused([{"from": "data/policies/default.yaml", "to": "cerberus/rules/.Git"}], ".git")
    _refused([{"from": ".git/", "to": "cerberus/rules/x/"}], ".git")


def test_nested_destinations_refused() -> None:
    """NEGATIVE: one destination inside another (in any letter case) is refused."""
    _refused([{"from": "data/policies/default.yaml", "to": "cerberus/rules/packs/default.yaml"},
              {"from": "data/packs/", "to": "cerberus/rules/packs/"}], "nested")
    _refused([{"from": "data/packs/", "to": "cerberus/rules/Packs/"},
              {"from": "data/prompts/", "to": "cerberus/rules/packs/sub/"}], "nested")


def test_repo_branch_and_name_validated() -> None:
    """NEGATIVE: repo, branch and source-name values that could become a git
    option, a path step or a URL are refused before any network or git call."""
    bad = [
        {"branch": "--upload-pack=touch x"},
        {"branch": "main;echo x"},
        {"branch": "a..b"},
        {"branch": "-main"},
        {"repo": "example/../x"},
        {"repo": "ex ample/up"},
        {"repo": "example/upstream/extra"},
        {"repo": "https://example.invalid/x"},
        {"repo": "-x/y"},
        {"name": "../escape"},
    ]
    for override in bad:
        for stype in ("github-vendored", "github-self"):
            src = vendored_source()
            src["type"] = stype
            src.update(override)
            st = cu.check_source(src)
            assert st["status"] == "error" and "invalid" in st.get("message", ""), (override, st)
    with _tmp("badstatus") as d:
        local = d / "local"
        write_files(local, LOCAL_FILES)
        before = snapshot(local)
        cu.REPO_ROOT = local

        def no_clone(_repo):
            raise AssertionError("clone attempted with an invalid value")

        cu._clone_url = no_clone
        for status in (dict(_vendored_status("e" * 40), branch="--upload-pack=x"),
                       dict(_vendored_status("e" * 40), repo="a/../b"),
                       _vendored_status("not-a-sha")):
            with contextlib.redirect_stdout(io.StringIO()):
                result = cu._apply_github_vendored(vendored_source(), status, interactive=False)
            assert result.get("applied") is False and "invalid" in result["reason"], result
        assert snapshot(local) == before


def test_shipped_manifest_passes_validation() -> None:
    """POSITIVE: the real sources.yaml passes every new manifest check."""
    import yaml
    data = yaml.safe_load((REPO / "scripts/update/sources.yaml").read_text(encoding="utf-8"))
    for s in data["sources"]:
        cu._validate_source(s)  # raises ValueError on a bad value


def test_temp_clone_removed_even_when_read_only() -> None:
    """NEGATIVE (Windows): git leaves read-only object files in the clone; the
    temp folder must still be removed after the run. Plus the helper alone on
    a read-only file inside a read-only folder."""
    with _tmp("rocleanup") as d:
        local, up = d / "local", d / "up"
        write_files(local, LOCAL_FILES)
        new_sha = make_repo(up, UPSTREAM_FILES)
        cu.REPO_ROOT = local
        cu._clone_url = lambda _repo: up.as_uri()
        made: list = []
        real_mkdtemp = tempfile.mkdtemp

        def spy(*a, **k):
            p = real_mkdtemp(*a, **k)
            made.append(Path(p))
            return p

        tempfile.mkdtemp = spy
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                result = cu._apply_github_vendored(vendored_source(), _vendored_status(new_sha),
                                                   interactive=False)
        finally:
            tempfile.mkdtemp = real_mkdtemp
        assert result.get("applied") is True, result
        assert made, "no temp folder was made"
        left = [p for p in made if p.exists()]
        for p in left:
            _rmtree(p)
        assert not left, f"temp clone left behind: {left}"
        ro = d / "ro"
        write_files(ro, {"inner/locked.txt": "x\n"})
        os.chmod(ro / "inner" / "locked.txt", stat.S_IREAD)
        os.chmod(ro / "inner", stat.S_IREAD | stat.S_IEXEC)
        cu._rmtree_force(ro)
        assert not ro.exists(), "read-only tree survived _rmtree_force"


# ---------------- tests: smoke interpreter ----------------

def test_python_smoke_runs_on_own_interpreter() -> None:
    assert cu._smoke_argv("python -m cerberus.engine.smoke_test") == \
        [sys.executable, "-m", "cerberus.engine.smoke_test"]
    assert cu._smoke_argv("python3 -m x.y") == [sys.executable, "-m", "x.y"]
    assert cu._smoke_argv("py -3 -m x") == [sys.executable, "-m", "x"]
    # Negative: a non-python smoke is left as written.
    assert cu._smoke_argv("echo hello") is None
    assert cu._smoke_argv("pythonic-tool --x") is None


def test_shipped_smokes_resolve_to_own_interpreter() -> None:
    import yaml
    data = yaml.safe_load((REPO / "scripts/update/sources.yaml").read_text(encoding="utf-8"))
    smokes = [s.get("post_update_smoke") for s in data["sources"] if s.get("post_update_smoke")]
    assert smokes, "no smokes in sources.yaml"
    for cmd in smokes:
        if cmd.split()[0].lower().startswith("python"):
            argv = cu._smoke_argv(cmd)
            assert argv and argv[0] == sys.executable, (cmd, argv)


# ---------------- tests: self-update ----------------

def _self_fixture(d: Path) -> tuple[Path, Path, dict]:
    up, local = d / "up", d / "local"
    make_repo(up, {"a.txt": "one\n"})
    git(d, "clone", "-q", up.as_uri(), str(local))
    write_files(up, {"b.txt": "two\n"})
    git(up, "add", "-A")
    git(up, "commit", "-q", "-m", "upstream moves on")
    up_sha = git(up, "rev-parse", "HEAD").strip()
    cu.REPO_ROOT = local
    cu._fetch_github_branch_sha = lambda _repo, _branch: up_sha
    cu._run_scaffold_ensure = lambda: None
    cu._whats_new_after_update = lambda: None
    return up, local, {"name": "charon", "type": "github-self", "repo": "example/charon", "branch": "main"}


def test_modified_tracked_file_blocks() -> None:
    """NEGATIVE: a modified tracked file blocks the update."""
    with _tmp("tracked") as d:
        _up, local, source = _self_fixture(d)
        (local / "a.txt").write_text("edited locally\n")
        st = cu._check_github_self(source)
        assert st["update_available"] is False, st
        assert "tracked" in (st.get("blocked_reason") or ""), st
        assert any("a.txt" in p for p in st["tracked_dirty"]), st


def test_untracked_only_proceeds_with_warning() -> None:
    """POSITIVE: untracked files only. The update is offered, the warning is
    printed, the pull lands, and the untracked file is untouched."""
    with _tmp("untracked") as d:
        _up, local, source = _self_fixture(d)
        write_files(local, {"03-Domains/README.md": "made by the wizard\n"})
        st = cu._check_github_self(source)
        assert st["update_available"] is True, st
        assert st["blocked_reason"] is None, st
        assert any("03-Domains" in p for p in st["untracked"]), st
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            cu._print_status(st)
            result = cu._apply_github_self(source, st, interactive=False)
        text = out.getvalue()
        assert "untracked" in text and "do NOT block" in text, text
        assert result["applied"] is True, result
        assert (local / "b.txt").read_text() == "two\n", "pull did not land"
        assert (local / "03-Domains/README.md").read_text() == "made by the wizard\n"
        # No wiring script in the fixture: a loud warning, not silence.
        assert result["wiring"]["missing"] is True, result
        assert "WIRING NOT CHECKED" in text, text


# ---------------- tests: post-update wiring ----------------

STUB = (
    "import sys, pathlib\n"
    "pathlib.Path(__file__).with_name('argv.txt').write_text(' '.join(sys.argv[1:]))\n"
    "sys.exit({code})\n"
)


def _wiring(code: int, interactive: bool) -> tuple[dict, str, str]:
    with _tmp(f"wiring{code}") as d:
        write_files(d, {"scripts/post_install_wiring.py": STUB.format(code=code)})
        cu.REPO_ROOT = d
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            res = cu._run_post_update_wiring(interactive)
        argv = (d / "scripts" / "argv.txt").read_text()
        return res, out.getvalue(), argv


def test_wiring_stub_exit_0_reads_as_wired() -> None:
    res, text, argv = _wiring(0, interactive=False)
    assert res == {"ok": True, "missing": False, "exit": 0}, res
    assert argv == "--mode update --non-interactive", argv
    assert "everything is wired" in text, text


def test_wiring_stub_exit_1_is_loud() -> None:
    res, text, argv = _wiring(1, interactive=True)
    assert res["ok"] is False and res["exit"] == 1, res
    assert argv == "--mode update", argv  # interactive: the script may ask
    assert "WIRING NOT COMPLETE" in text and "!!!!" in text, text


def test_wiring_missing_script_is_loud() -> None:
    with _tmp("wiringmissing") as d:
        cu.REPO_ROOT = d
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            res = cu._run_post_update_wiring(False)
        assert res["missing"] is True and res["ok"] is False, res
        assert "WIRING NOT CHECKED" in out.getvalue()


# ---------------- tests: menu duplicates (row 8) ----------------

_FM = re.compile(r"\A---\s*\n(.*?)\n---\s*\n", re.S)
_WRAP = re.compile(r"\b(?:run|use|invoke)\s+the\s+`?([A-Za-z0-9_-]+)`?\s+skill\b", re.I)

# Commands outside this change that also wrap a menu-visible skill. Tracked as a
# follow-up (they are printed, not hidden); any NEW wrapper fails the test.
KNOWN_WRAPPERS_PENDING = {"cerberus-deps", "cerberus-recover", "cerberus-vet", "vault-query"}


def _frontmatter(text: str) -> dict:
    m = _FM.match(text)
    out = {}
    if m:
        for line in m.group(1).splitlines():
            if ":" in line and not line.startswith((" ", "\t")):
                k, v = line.split(":", 1)
                out[k.strip()] = v.strip().strip("'\"")
    return out


def menu_visible_skills(skills_dir: Path) -> set:
    visible = set()
    for p in sorted(skills_dir.glob("*/SKILL.md")):
        fm = _frontmatter(p.read_text(encoding="utf-8"))
        if fm.get("user-invocable", "true").lower() != "false":
            visible.add(fm.get("name") or p.parent.name)
    return visible


def wrapper_commands(commands_dir: Path, skills_dir: Path) -> dict:
    """{command name: skill name} for every command whose body tells Claude to
    run a skill that is still visible in the `/` menu (a duplicate entry)."""
    visible = menu_visible_skills(skills_dir)
    found = {}
    for p in sorted(commands_dir.glob("*.md")):
        text = p.read_text(encoding="utf-8")
        body = _FM.sub("", text, count=1)
        for m in _WRAP.finditer(body):
            if m.group(1) in visible:
                found[p.stem] = m.group(1)
                break
    return found


def test_wrapper_check_fires_and_stays_quiet() -> None:
    with _tmp("wrappers") as d:
        cmds, skills = d / "commands", d / "skills"
        write_files(d, {
            "commands/dup.md": "---\nname: dup\n---\nRun the `shown` skill.\n",
            "commands/ok.md": "---\nname: ok\n---\nRun the `hidden` skill.\n",
            "commands/plain.md": "---\nname: plain\n---\nDo the thing yourself.\n",
            "skills/shown/SKILL.md": "---\nname: shown\ndescription: x\n---\nbody\n",
            "skills/hidden/SKILL.md": "---\nname: hidden\ndescription: x\nuser-invocable: false\n---\nbody\n",
        })
        assert wrapper_commands(cmds, skills) == {"dup": "shown"}  # fires on dup only
        write_files(d, {"skills/shown/SKILL.md":
                        "---\nname: shown\ndescription: x\nuser-invocable: false\n---\nbody\n"})
        assert wrapper_commands(cmds, skills) == {}  # quiet once hidden


def test_no_command_wraps_a_menu_visible_skill() -> None:
    """The real tree: /charon-update must not sit beside a visible /update-charon."""
    found = wrapper_commands(REPO / ".claude" / "commands", REPO / ".claude" / "skills")
    pending = {c: s for c, s in found.items() if c in KNOWN_WRAPPERS_PENDING}
    new = {c: s for c, s in found.items() if c not in KNOWN_WRAPPERS_PENDING}
    if pending:
        print(f"    note: known wrappers still to fix (follow-up): {pending}")
    assert not new, f"command(s) wrapping a skill that shows in the / menu: {new}"


# ---------------- runner ----------------

def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass
    tests = [(n, f) for n, f in globals().items() if n.startswith("test_") and callable(f)]
    passed = failed = 0
    for name, fn in tests:
        try:
            fn()
        except Exception:  # noqa: BLE001
            failed += 1
            print(f"FAIL {name}")
            traceback.print_exc()
        else:
            passed += 1
            print(f"PASS {name}")
        finally:
            _restore()
    _rmtree(_ISOLATION)
    print(f"\n{passed} passed, {failed} failed ({len(tests)} tests)")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
