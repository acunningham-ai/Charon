#!/usr/bin/env python3
"""W1 security tests: credential recovery, `claude -p` tool limits, token provenance.

Proves, through each script's real entry point where there is one:

  (a) recover-ssh-creds.py with the credential in the secrets file: reports FOUND,
      and the value appears in neither stdout nor stderr.
  (b) with ONLY a ~/.claude/history.jsonl holding a typed-in password: reports NOT
      FOUND (history is never searched), and the value appears nowhere.
      Plus: the ssh-recovery hook's nudge names the check script, never says
      "retrieve", never tells the model to run a bare `python`, and stays silent
      on a successful ssh.
  (c) both shipped `claude -p` runners build an argument list carrying
      --disallowedTools "Bash PowerShell Agent WebFetch WebSearch" and
      --strict-mcp-config; a scan of the repo finds no `claude -p` call without
      them, and the same scan DOES flag synthetic fixtures that lack them.
  (d) confirm_token_provenance.py: spends with a matching operator `!` issuance
      exit 0; an unmatched spend exits 1. The scheduled audit reports it.

Hermetic: HOME / USERPROFILE and every HARNESS_* path point into a temp folder
for the whole run, so no real secret, transcript or verdict log is ever read.
Secret values are random per run.

Files under scripts/hooks/ and scripts/checks/ may be tested from a flat staging
folder before they are promoted:

  test_w1_security.py [--staged DIR]

Default: state/daedalus-staging/w1-sec/ if it holds the staged copies, else the
real locations. The folder used is printed first.

Exit 0 = all passed, 1 = any failure.
"""
import argparse
import ast
import importlib.util
import json
import os
import re
import secrets
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "scripts"
DEFAULT_STAGING = REPO / "state" / "daedalus-staging" / "w1-sec"

REQUIRED_DISALLOWED = {"Bash", "PowerShell", "Agent", "WebFetch", "WebSearch"}
STRICT_MCP = "--strict-mcp-config"
DISALLOW_FLAG = "--disallowedTools"

# file name -> real location (relative to the repo)
STAGEABLE = {
    "ssh-recovery.py": "scripts/hooks/ssh-recovery.py",
    "lint-permission-rules.py": "scripts/hooks/cerberus/lint-permission-rules.py",
    "confirm_token_provenance.py": "scripts/checks/confirm_token_provenance.py",
}

RESULTS: list = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"  ({detail})" if detail and not ok else ""))


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run(args: list, stdin: str = "") -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, *args], input=stdin, capture_output=True,
                          text=True, encoding="utf-8", errors="replace", timeout=120,
                          env=dict(os.environ))


# --------------------------------------------------------------------------- setup

def hermetic_env(tmp: Path) -> dict:
    """Point every home and harness path into tmp for this process and children."""
    home = tmp / "home"
    project = tmp / "project"
    memory = home / ".claude" / "projects" / "test-project" / "memory"
    for d in (home, project, memory):
        d.mkdir(parents=True, exist_ok=True)
    os.environ["HOME"] = str(home)
    os.environ["USERPROFILE"] = str(home)
    os.environ["HARNESS_VAULT_ROOT"] = str(project)
    os.environ["HARNESS_MEMORY_ROOT"] = str(memory)
    os.environ["HARNESS_CAPTURE_ROOT"] = str(tmp / "capture-pipeline")
    os.environ["CLAUDE_PROJECT_DIR"] = str(project)
    os.environ["HARNESS_HOOK_TEST"] = "1"
    os.environ.pop("HARNESS_SECRETS_DIR", None)  # default: <HOME>/.secrets
    return {"home": home, "project": project, "memory": memory}


def locate(staged_arg) -> tuple:
    if staged_arg:
        base = Path(staged_arg).resolve()
        return base, {n: base / n for n in STAGEABLE}
    if all((DEFAULT_STAGING / n).is_file() for n in STAGEABLE):
        return DEFAULT_STAGING, {n: DEFAULT_STAGING / n for n in STAGEABLE}
    return None, {n: REPO / rel for n, rel in STAGEABLE.items()}


# --------------------------------------------------------------------------- (a) (b)

def test_recover(paths: dict) -> None:
    print("\n(a)/(b) recover-ssh-creds.py")
    script = str(SCRIPTS / "recover-ssh-creds.py")
    value = "Tst-" + secrets.token_hex(12)
    home = paths["home"]

    # (a) the secrets file holds the user
    sdir = home / ".secrets"
    sdir.mkdir(exist_ok=True)
    (sdir / "ssh-fallback.json").write_text(json.dumps(
        {"ssh-fallback": {"ssh": {"password_fallback": {"deploy": value}}}}), encoding="utf-8")
    p = run([script, "deploy"])
    out = p.stdout + p.stderr
    check("(a) secrets file holds the user: exit 0", p.returncode == 0, f"rc={p.returncode}")
    check("(a) reports FOUND", "FOUND" in p.stdout and "NOT FOUND" not in out)
    check("(a) value absent from stdout and stderr", value not in out)

    p = run([script, "someone-else"])
    check("(a) a user not in the file: exit 1, value absent",
          p.returncode == 1 and value not in p.stdout + p.stderr, f"rc={p.returncode}")
    p = run([script, "deploy", "--service", "../ssh-fallback"])
    check("(a) a path-shaped --service is refused (exit 2)", p.returncode == 2,
          f"rc={p.returncode}")

    # (b) only a history.jsonl with a password, no secrets file
    (sdir / "ssh-fallback.json").unlink()
    hist = home / ".claude" / "history.jsonl"
    hist.parent.mkdir(parents=True, exist_ok=True)
    hist.write_text("\n".join(json.dumps({"display": t}) for t in (
        f"ssh deploy@host1 the password is {value}",
        f"password = {value} for deploy",
    )) + "\n", encoding="utf-8")
    p = run([script, "deploy"])
    out = p.stdout + p.stderr
    check("(b) only history.jsonl holds it: exit 1", p.returncode == 1, f"rc={p.returncode}")
    check("(b) reports NOT FOUND", "NOT FOUND" in p.stderr and "FOUND:" not in p.stdout)
    check("(b) value absent from stdout and stderr", value not in out)

    src = (SCRIPTS / "recover-ssh-creds.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    opened_history = any(isinstance(n, ast.Constant) and isinstance(n.value, str)
                         and n.value == "history.jsonl" for n in ast.walk(tree))
    check("(b) no code path names history.jsonl", not opened_history)


def test_ssh_hook(hook: Path) -> None:
    print(f"\n(b) ssh-recovery hook nudge  [{hook.relative_to(REPO).as_posix()}]")
    fail = {"stderr": "deploy@host1: Permission denied (publickey,password)."}
    cases = {
        "user parsed": {"tool_input": {"command": "ssh deploy@host1 uptime"},
                        "tool_response": fail},
        "user unknown": {"tool_input": {"command": "ssh host1 uptime"},
                         "tool_response": fail},
    }
    for label, payload in cases.items():
        p = run([str(hook)], json.dumps(payload))
        text = p.stdout
        check(f"nudge fires ({label})", p.returncode == 0 and "recover-ssh-creds.py" in text,
              f"rc={p.returncode} out={text[:120]!r}")
        check(f"nudge never says 'retrieve' ({label})", "retrieve" not in text.lower())
        check(f"nudge has no bare 'python' ({label})", not re.search(r"\bpython\b", text),
              text[:160])
    p = run([str(hook)], json.dumps({"tool_input": {"command": "ssh deploy@host1 uptime"},
                                      "tool_response": {"stdout": "up 3 days"}}))
    check("hook stays silent on a successful ssh", p.returncode == 0 and not p.stdout.strip(),
          repr(p.stdout[:80]))
    p = run([str(hook)], json.dumps(cases["user parsed"]))
    check("nudge names the parsed user", "recover-ssh-creds.py deploy" in p.stdout)


# --------------------------------------------------------------------------- (c)

def flags_ok(cmd: list) -> tuple:
    if "-p" not in cmd:
        return False, "no -p"
    if STRICT_MCP not in cmd:
        return False, f"no {STRICT_MCP}"
    if DISALLOW_FLAG not in cmd:
        return False, f"no {DISALLOW_FLAG}"
    i = cmd.index(DISALLOW_FLAG)
    denied = set(str(cmd[i + 1]).split()) if i + 1 < len(cmd) else set()
    missing = REQUIRED_DISALLOWED - denied
    return (not missing), (f"not denied: {sorted(missing)}" if missing else "")


SCAN_EXTS = {".py", ".sh", ".ps1", ".bat", ".cmd", ".mjs", ".js"}
SKIP_DIRS = {".git", "node_modules", "__pycache__", "state", ".venv", "venv"}
_SHELL_CLAUDE_P = re.compile(
    r"""(?i)(?<![\w.-])claude(?:\.exe|\.cmd)?["']?\s(?:.*?\s)?(?:-p|--print)(?=\s|$|["'])""")
_JS_P = re.compile(r"""["'`](?:-p|--print)["'`]""")
_RUNNER_CALLS = {"run", "Popen", "call", "check_call", "check_output", "system", "spawn"}


def _flag_text_ok(text: str) -> bool:
    return DISALLOW_FLAG in text and STRICT_MCP in text


def _logical_lines(text: str) -> list:
    out, buf, start = [], "", 1
    for n, line in enumerate(text.splitlines(), 1):
        if not buf:
            start = n
        stripped = line.rstrip()
        if stripped.endswith(("\\", "^", "`")):
            buf += stripped[:-1] + " "
            continue
        out.append((start, buf + line))
        buf = ""
    if buf:
        out.append((start, buf))
    return out


def scan_text(rel: str, text: str) -> list:
    """Return [(rel, line, ok)] for every `claude -p` call site found in one file."""
    sites = []
    ext = Path(rel).suffix.lower()
    if "claude" not in text.lower():
        return sites
    if ext == ".py":
        try:
            tree = ast.parse(text)
        except SyntaxError:
            return [(rel, 0, False)]  # unparseable: fail loud, never skip
        for node in ast.walk(tree):
            if isinstance(node, (ast.List, ast.Tuple)):
                consts = [e.value for e in node.elts
                          if isinstance(e, ast.Constant) and isinstance(e.value, str)]
                if not any(c in ("-p", "--print") for c in consts) or not node.elts:
                    continue
                head = (ast.get_source_segment(text, node.elts[0]) or "").lower()
                if "claude" in head or "exe" in head or any("claude" in c for c in consts):
                    seg = ast.get_source_segment(text, node) or ""
                    sites.append((rel, node.lineno, _flag_text_ok(seg)))
            elif isinstance(node, ast.Call):
                fn = node.func
                name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
                if name not in _RUNNER_CALLS:
                    continue
                for arg in node.args:
                    if isinstance(arg, (ast.Constant, ast.JoinedStr)):
                        seg = ast.get_source_segment(text, arg) or ""
                        if _SHELL_CLAUDE_P.search(seg):
                            sites.append((rel, arg.lineno, _flag_text_ok(seg)))
        return sites
    for lineno, line in _logical_lines(text):
        s = line.strip()
        low = s.lower()
        if (not s or s.startswith(("#", "//", "*", "::")) or low.startswith("rem ")
                or low.startswith(("echo ", "write-host"))):
            continue
        if _SHELL_CLAUDE_P.search(s):
            sites.append((rel, lineno, _flag_text_ok(s)))
    if ext in (".js", ".mjs"):
        for m in _JS_P.finditer(text):
            # The enclosing statement: spawn('claude', [...]) puts the executable
            # outside the argument array, so the array alone is not enough.
            lo = max(text.rfind(ch, 0, m.start()) for ch in ";{}") + 1
            hi = text.find(";", m.end())
            span = text[lo: hi if hi >= 0 else len(text)]
            if "claude" in span.lower():
                sites.append((rel, text.count("\n", 0, m.start()) + 1, _flag_text_ok(span)))
    return sites


def scan_tree(root: Path, overrides: dict | None = None) -> list:
    overrides = overrides or {}
    sites = []
    for dirpath, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for f in files:
            p = Path(dirpath) / f
            if p.suffix.lower() not in SCAN_EXTS:
                continue
            rel = p.relative_to(root).as_posix()
            src = overrides.get(rel, p)
            try:
                text = Path(src).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            sites.extend(scan_text(rel, text))
    return sites


def test_claude_p(located: dict, tmp: Path) -> None:
    print("\n(c) claude -p runners")
    autoreview = load_module("w1_autoreview", SCRIPTS / "harness_autoreview.py")
    cmd = autoreview.build_claude_cmd("claude", "prompt.txt", "deny.settings.json",
                                      "vault", "memory")
    ok, why = flags_ok(cmd)
    check("harness_autoreview.build_claude_cmd carries both flags", ok, why)
    check("harness_autoreview keeps its allow list and budget cap",
          "Read Write Glob Grep" in cmd and "--max-budget-usd" in cmd)

    lint = load_module("w1_lint", located["lint-permission-rules.py"])
    cmd = lint.build_claude_lint_cmd("claude")
    ok, why = flags_ok(cmd)
    check("lint-permission-rules.build_claude_lint_cmd carries both flags", ok, why)

    overrides = {STAGEABLE[n]: located[n] for n in STAGEABLE}
    sites = scan_tree(REPO, overrides)
    files = {s[0] for s in sites}
    check("repo scan finds both known runners",
          {"scripts/harness_autoreview.py",
           "scripts/hooks/cerberus/lint-permission-rules.py"} <= files,
          f"found: {sorted(files)}")
    bad = [f"{r}:{ln}" for r, ln, good in sites if not good]
    check("repo scan: no claude -p call without both flags", not bad, ", ".join(bad))
    print(f"      call sites found: {', '.join(f'{r}:{ln}' for r, ln, _ in sites) or 'none'}")

    # Synthetic fixtures. The command text is assembled from pieces so this test
    # file does not itself contain a `claude -p` call for the repo scan to find.
    c = "clau" + "de"
    flags = f'{DISALLOW_FLAG} "Bash PowerShell Agent WebFetch WebSearch" {STRICT_MCP}'
    fx = tmp / "fixture-repo"
    fx.mkdir()
    (fx / "bad_list.py").write_text(
        f'import subprocess\nsubprocess.run(["{c}", "-p", "hi", "--max-turns", "1"])\n',
        encoding="utf-8")
    (fx / "bad_shell.py").write_text(
        f'import os\nos.system("{c} -p hi --model haiku")\n', encoding="utf-8")
    (fx / "bad.sh").write_text(f'#!/bin/sh\n{c} -p "summarise" \\\n  --max-budget-usd 1\n',
                               encoding="utf-8")
    (fx / "bad.bat").write_text(f'@echo off\r\n{c} -p "summarise" --max-budget-usd 1\r\n',
                                encoding="utf-8")
    (fx / "bad.mjs").write_text(
        f"import {{ spawn }} from 'node:child_process';\nspawn('{c}', ['-p', 'hi']);\n",
        encoding="utf-8")
    (fx / "good.sh").write_text(f'#!/bin/sh\n{c} -p "summarise" {flags} \\\n'
                                f'  --max-budget-usd 1\n', encoding="utf-8")
    (fx / "good.py").write_text(
        f'import subprocess\nsubprocess.run(["{c}", "-p", "hi", "{DISALLOW_FLAG}",\n'
        f'    "Bash PowerShell Agent WebFetch WebSearch", "{STRICT_MCP}"])\n', encoding="utf-8")
    (fx / "prose.py").write_text(f'"""Runs `{c} -p` once."""\nprint("{c} -p exit 1")\n',
                                 encoding="utf-8")
    (fx / "mkdir.sh").write_text("#!/bin/sh\nmkdir -p state\n", encoding="utf-8")
    fsites = scan_tree(fx)
    flagged = {r for r, _, good in fsites if not good}
    expect_bad = {"bad_list.py", "bad_shell.py", "bad.sh", "bad.bat", "bad.mjs"}
    check("scan flags every synthetic fixture missing the flags", flagged == expect_bad,
          f"flagged={sorted(flagged)}")
    found = {r for r, _, _ in fsites}
    check("scan passes compliant fixtures and ignores prose / mkdir -p",
          {"good.sh", "good.py"} <= found and not ({"prose.py", "mkdir.sh"} & found)
          and not ({"good.sh", "good.py"} & flagged), f"found={sorted(found)}")


# --------------------------------------------------------------------------- (d)

def _iso(t: datetime) -> str:
    return t.isoformat()


def _verdict_line(t, session, rule_id, reuse=0, test=False) -> str:
    o = {"ts": _iso(t), "hook": "deny-destructive", "rule": "policy-confirmed-bypass",
         "declared": "observe", "effective": "observe", "session_id": session,
         "context": {"rule_id": rule_id, "reuse_count": reuse}}
    if test:
        o["test"] = True
    return json.dumps(o)


def _issue_line(t, cmd) -> str:
    return json.dumps({"type": "user", "timestamp": _iso(t),
                       "message": {"role": "user",
                                   "content": f"<bash-input>{cmd}</bash-input>"}})


def _agent_line(t, cmd) -> str:
    return json.dumps({"type": "assistant", "timestamp": _iso(t),
                       "message": {"role": "assistant", "content": [
                           {"type": "tool_use", "name": "Bash", "input": {"command": cmd}}]}})


def test_provenance(checker: Path, paths: dict, tmp: Path) -> None:
    print(f"\n(d) confirm-token provenance  [{checker.relative_to(REPO).as_posix()}]")
    marker = "MARK" + secrets.token_hex(6)
    deny = str(SCRIPTS / "hooks" / "deny-destructive.py")
    now = datetime.now(timezone.utc)
    t0 = now - timedelta(hours=2)

    # Charon's own issuance command form (deny-destructive.py), Python-dict quoting.
    charon_cmd = ("python -c \"import json,time,pathlib;pathlib.Path('state').mkdir(exist_ok=True);"
                  "pathlib.Path('state/policy-confirm.json').write_text(json.dumps("
                  "{'rule_id':'protected-zone','issued_epoch':time.time(),'granted_by':'me'}))\""
                  f" # {marker}")
    json_cmd = ('python3 -c \'import json,time,pathlib;pathlib.Path("state/policy-confirm.json")'
                '.write_text(json.dumps({"rule_id": "memory-index-line-budget", '
                f'"issued_epoch": time.time()}}))\' # {marker}')

    def case(name):
        d = tmp / f"prov-{name}"
        (d / "verdict").mkdir(parents=True)
        (d / "transcripts").mkdir()
        return d

    def go(d, *extra):
        return run([str(checker), "--json", "--verdict-dir", str(d / "verdict"),
                    "--transcripts", str(d / "transcripts"), "--deny-destructive", deny, *extra])

    # matched: Python-dict form, first use + a re-use inside the grace window,
    # JSON form in a second session, and a HARNESS_HOOK_TEST line that must be ignored.
    d = case("matched")
    (d / "transcripts" / "sess-a.jsonl").write_text(
        _issue_line(t0, charon_cmd) + "\n", encoding="utf-8")
    (d / "transcripts" / "sess-b.jsonl").write_text(
        _issue_line(t0, json_cmd) + "\n", encoding="utf-8")
    (d / "verdict" / "day.jsonl").write_text("\n".join([
        _verdict_line(t0 + timedelta(seconds=40), "sess-a", "protected-zone"),
        _verdict_line(t0 + timedelta(seconds=90), "sess-a", "protected-zone", reuse=1),
        _verdict_line(t0 + timedelta(seconds=30), "sess-b", "memory-index-line-budget"),
        _verdict_line(t0 + timedelta(seconds=50), "sess-zzz", "protected-zone", test=True),
    ]) + "\n", encoding="utf-8")
    p = go(d)
    res = json.loads(p.stdout or "{}")
    check("(d) matched uses exit 0", p.returncode == 0, f"rc={p.returncode} {p.stdout[:200]}")
    check("(d) 3 spends matched, test-stamped line ignored",
          res.get("matched") == 3 and res.get("uses") == 3, str(res)[:200])
    check("(d) window read from deny-destructive.py (300 + 120 + 60)", res.get("window_s") == 480,
          str(res.get("window_s")))
    check("(d) command text never echoed", marker not in p.stdout + p.stderr)

    # unmatched: no issuance, the assistant wrote the token itself.
    d = case("forged")
    (d / "transcripts" / "sess-c.jsonl").write_text(
        _agent_line(t0, f"echo x > state/policy-confirm.json # {marker}") + "\n",
        encoding="utf-8")
    (d / "verdict" / "day.jsonl").write_text(
        _verdict_line(t0 + timedelta(seconds=20), "sess-c", "protected-zone") + "\n",
        encoding="utf-8")
    p = go(d)
    res = json.loads(p.stdout or "{}")
    um = res.get("unmatched") or [{}]
    check("(d) unmatched use exits 1", p.returncode == 1, f"rc={p.returncode}")
    check("(d) unmatched use flags the assistant touching the token",
          um[0].get("assistant_touched_token") is True, str(um)[:200])

    # unmatched: issuance for a DIFFERENT rule, an expired issuance, a re-use with
    # no first use, and a crafted session id that must not steer the file read.
    d = case("mismatch")
    (d / "transcripts" / "sess-d.jsonl").write_text(
        _issue_line(t0, charon_cmd) + "\n", encoding="utf-8")
    (d / "verdict" / "day.jsonl").write_text("\n".join([
        _verdict_line(t0 + timedelta(seconds=10), "sess-d", "memory-index-total-ceiling"),
        _verdict_line(t0 + timedelta(seconds=2000), "sess-d", "protected-zone"),
        _verdict_line(t0 + timedelta(seconds=5), "sess-e", "protected-zone", reuse=2),
        _verdict_line(t0 + timedelta(seconds=5), "../sess-d", "protected-zone"),
    ]) + "\n", encoding="utf-8")
    p = go(d)
    res = json.loads(p.stdout or "{}")
    check("(d) wrong rule, expired, orphan re-use, crafted session: all unmatched",
          p.returncode == 1 and len(res.get("unmatched") or []) == 4 and res.get("matched") == 0,
          str(res)[:240])
    check("(d) crafted session id rendered inert",
          all("/" not in u["session"] for u in res.get("unmatched") or []))

    # human-readable mode, and --help
    p2 = run([str(checker), "--verdict-dir", str(d / "verdict"), "--transcripts",
              str(d / "transcripts"), "--deny-destructive", deny])
    check("(d) text mode prints UNMATCHED lines, exit 1",
          p2.returncode == 1 and "UNMATCHED" in p2.stdout, p2.stdout[:160])
    p = run([str(checker), "--help"])
    check("(d) --help exits 0", p.returncode == 0)

    # The scheduled audit reports it: through its real function, with the checker's
    # DEFAULT paths (verdict log via _verdict.py, transcripts via harness_paths),
    # which the hermetic env points into the temp folder.
    audit = load_module("w1_audit", SCRIPTS / "scheduled-audit.py")
    vdir = paths["project"] / "state" / "verdict"
    vdir.mkdir(parents=True, exist_ok=True)
    (vdir / "day.jsonl").write_text(
        _verdict_line(t0 + timedelta(seconds=5), "sess-f", "protected-zone") + "\n",
        encoding="utf-8")
    audit.PROVENANCE_CHECK = checker
    status, unmatched = audit.confirm_token_provenance()
    check("(d) scheduled-audit runs the check and gets the unmatched spend",
          status == "unmatched" and len(unmatched) == 1, f"{status} {unmatched}")
    report = audit.render_report(datetime.now().date(), "ok", [], "h", "h", [], [], True, [],
                                 (status, unmatched))
    check("(d) audit report carries section 7 and counts it as an issue",
          "## 7. Confirm-token provenance" in report and "**1 check(s)**" in report)
    (vdir / "day.jsonl").unlink()
    status, unmatched = audit.confirm_token_provenance()
    report = audit.render_report(datetime.now().date(), "ok", [], "h", "h", [], [], True, [],
                                 (status, unmatched))
    check("(d) no spends: audit section passes", status == "ok"
          and "All seven deterministic checks **passed**" in report, status)
    audit.PROVENANCE_CHECK = tmp / "missing.py"
    status, _ = audit.confirm_token_provenance()
    check("(d) a missing checker is reported, never a pass", status.startswith("error"), status)


# --------------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--staged", help="flat folder holding staged copies of "
                                     + ", ".join(STAGEABLE))
    args = ap.parse_args()
    base, located = locate(args.staged)
    missing = [str(p) for p in located.values() if not p.is_file()]
    print("W1 security tests")
    print(f"  hook/check copies from: "
          f"{base.relative_to(REPO).as_posix() + '/ (staged)' if base else 'real locations'}")
    if missing:
        print("  FAIL: missing " + ", ".join(missing))
        return 1

    with tempfile.TemporaryDirectory(prefix="w1sec-") as td:
        tmp = Path(td)
        paths = hermetic_env(tmp)
        for fn, fargs in ((test_recover, (paths,)),
                          (test_ssh_hook, (located["ssh-recovery.py"],)),
                          (test_claude_p, (located, tmp)),
                          (test_provenance, (located["confirm_token_provenance.py"], paths, tmp))):
            try:
                fn(*fargs)
            except Exception as exc:  # a crashed section is a failure, never a skip
                check(f"{fn.__name__} ran to completion", False, f"{type(exc).__name__}: {exc}")

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    failed = len(RESULTS) - passed
    print(f"\nSummary: {passed} passed, {failed} failed ({len(RESULTS)} checks)")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
