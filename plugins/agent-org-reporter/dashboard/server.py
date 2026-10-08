#!/usr/bin/env python3
"""
Agent Org dashboard — the local webpage (design draft step 2 + section 4).

Shows what the harness is doing right now: which agents are running, every tool
call as it happens, hook-gate verdicts, and the queued work waiting on you. It
exists so nothing happens out of sight ("nothing is truly
happening in the background — you can see what it is doing").

READ-ONLY. It reads state files and serves them; it writes nothing except its own
`state/agent-org/web.json` (port + pid, so a second launch reuses the running one).

Security baseline (see SECURITY.md):
  - binds 127.0.0.1 only; requests whose Host header is not this loopback
    address are refused (blocks DNS-rebinding from a web page);
  - fixed routes, no path from the request ever reaches the filesystem;
  - strict CSP (no inline script, no network beyond itself), nosniff, no-store;
  - no credentials, no prompt/answer/tool-input text exists in the source files;
  - description / deny / reason text is UNTRUSTED: the page renders it with
    textContent only, never as HTML. Capped again here as a second layer.
  - stdlib only (Charon dependency aversion); no network calls.

Lifecycle: `--launch` starts a detached server (or reuses a live one) and opens
the browser, then returns at once (the Claude Code mod calls it via
$.process.run, which waits for the child). The server exits by itself once no
page has polled it for IDLE_EXIT_S, so closing the tab stops it.

Usage:
  python server.py --launch     # start or reuse, open browser, return
  python server.py --serve      # run in the foreground (debugging)
  python server.py --dump       # print /api/state once and exit (testing)
  add --demo to any of these    # sample org from demo.py, no state read (screenshots)

Demo mode (Charon port plan W1) serves invented data only, on its own port and
web-demo.json, so it never answers for (or reuses) the real dashboard.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _is_vault(p: Path) -> bool:
    # Same marker as the mod (hooks/shared.ts): true of any Charon clone, even before
    # state/ exists, and of the author's vault.
    return (p / ".claude").is_dir() and (p / "scripts" / "load-rules.py").is_file()


def _vault_root() -> Path:
    for name in ("HARNESS_VAULT_ROOT", "CLAUDE_PROJECT_DIR"):
        env = os.environ.get(name)
        if env and _is_vault(Path(env)):
            return Path(env)
    for cand in [HERE, *HERE.parents]:
        if _is_vault(cand):
            return cand
    return HERE.parents[2]


VAULT = _vault_root()
STATE = VAULT / "state"
ORG = STATE / "agent-org"
AGENTS_DIR = VAULT / ".claude" / "agents"
# Optional: the capture pipeline may not be installed,
# and the backlog panel then says so instead of failing.
PIPELINE = Path(os.environ.get("HARNESS_CAPTURE_ROOT")
                or os.environ.get("CAPTURE_PIPELINE_DIR")
                or Path.home() / "capture-pipeline")
REVIEW_QUEUE = PIPELINE / "state" / "review-queue.jsonl"
WEB_INFO = ORG / "web.json"

HOST = "127.0.0.1"
PREFERRED_PORT = 8765
IDLE_EXIT_S = 120          # no poll for this long after the first one -> exit
FIRST_POLL_GRACE_S = 300   # time allowed for the browser to open the page at all
FEED_LIMIT = 200
TEXT_CAP = 160
MARKER = "agent-org-dashboard"  # /api/ping answer, so a reused port is really us
DEMO = False  # set by --demo: build_state() serves demo.py's sample org instead

STATIC = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/app.css": ("app.css", "text/css; charset=utf-8"),
}

CSP = ("default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
       "img-src 'self' data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")


# ---------------------------------------------------------------- reading ---

_cache: dict[str, tuple[float, int, object]] = {}


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _jsonl(path: Path) -> list[dict]:
    """Parse a JSONL file, cached on (mtime, size). Bad lines are skipped."""
    try:
        st = path.stat()
    except OSError:
        return []
    key = str(path)
    hit = _cache.get(key)
    if hit and hit[0] == st.st_mtime and hit[1] == st.st_size:
        return hit[2]  # type: ignore[return-value]
    rows = []
    for line in _read_text(path).splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    _cache[key] = (st.st_mtime, st.st_size, rows)
    return rows


def _json(path: Path):
    try:
        return json.loads(_read_text(path))
    except ValueError:
        return None


def _parse_ts(value) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _cap(value, n: int = TEXT_CAP):
    if value is None:
        return None
    s = str(value)
    return s if len(s) <= n else s[:n] + "…"


def _safe_name(s: str) -> str:
    return "".join(ch for ch in s if ch.isalnum() or ch in "-_")[:80]


def _local_midnight(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _recent_day_dirs(base: Path, days: int = 2) -> list[Path]:
    """Day-named subfolders/files covering the window. Files may be named by UTC
    (older logs, and the verdict log until its fix lands) or by local date, so
    take the last `days + 1` names and filter on each line's own `ts`."""
    if not base.is_dir():
        return []
    names = sorted(p.name for p in base.iterdir() if p.name[:4].isdigit())
    return [base / n for n in names[-(days + 1):]]


# ------------------------------------------------------------- the model ---

def seats() -> list[dict]:
    out = []
    if AGENTS_DIR.is_dir():
        for p in sorted(AGENTS_DIR.glob("*.md")):
            name = p.stem
            for line in _read_text(p).splitlines()[:15]:
                if line.startswith("name:"):
                    name = line.split(":", 1)[1].strip().strip("\"'") or name
                    break
            out.append({"name": _safe_name(name) or p.stem})
    return out


def sessions_and_agents(now: datetime) -> tuple[list[dict], dict[str, dict]]:
    """Status files -> sessions with their agents, active in the last 24h."""
    status_dir = ORG / "status"
    cutoff = now - timedelta(hours=24)
    sessions, by_agent = [], {}
    if not status_dir.is_dir():
        return sessions, by_agent
    for sdir in status_dir.iterdir():
        if not sdir.is_dir():
            continue
        agents = []
        for f in sdir.glob("*.json"):
            s = _json(f)
            if not isinstance(s, dict):
                continue
            last = _parse_ts(s.get("lastActivity"))
            if not last:
                continue
            tok = s.get("tokens") or {}
            a = {
                "key": _safe_name(str(s.get("key") or f.stem)),
                "agentId": _safe_name(str(s.get("agentId") or "")) or None,
                "type": _cap(s.get("subagentType") or "unknown", 60),
                "description": _cap(s.get("description") or "", 120),
                "state": _cap(s.get("state") or "unknown", 20),
                "background": bool(s.get("background")),
                "startedAt": s.get("startedAt"),
                "lastActivity": s.get("lastActivity"),
                "toolCalls": int(s.get("toolCalls") or 0),
                "toolErrors": int(s.get("toolErrors") or 0),
                "toolDenies": int(s.get("toolDenies") or 0),
                "turns": int(s.get("turns") or 0),
                "model": _cap(s.get("model"), 60),
                "tokensOut": int(tok.get("output") or 0),
                "tokensIn": int((tok.get("input") or 0) + (tok.get("cacheRead") or 0)
                                + (tok.get("cacheWrite") or 0)),
                "deniedBy": _cap(s.get("deniedBy")),
                # live-agents panel: tool NAMES and times only (privacy baseline)
                "parentAgentId": _safe_name(str(s.get("parentAgentId") or "")) or None,
                "currentTool": _cap(s.get("currentTool"), 60),
                "currentSince": s.get("currentSince") if isinstance(s.get("currentSince"), str) else None,
                "lastTool": _cap(s.get("lastTool"), 60),
                "finishedAt": s.get("finishedAt") if isinstance(s.get("finishedAt"), str) else None,
                "callTimes": [t for t in (s.get("callTimes") or []) if isinstance(t, (int, float))][-40:],
                "_last": last,
            }
            if a["agentId"]:
                by_agent[a["agentId"]] = a
            agents.append(a)
        if not agents:
            continue
        last = max(a["_last"] for a in agents)
        if last < cutoff:
            continue
        main = next((a for a in agents if a["key"] == "main"), None)
        ended = bool(main and main["state"] == "finished")
        live = (not ended) and (now - last) < timedelta(minutes=15)
        agents.sort(key=lambda a: (a["key"] != "main", -a["_last"].timestamp()))
        sessions.append({
            "id": _safe_name(sdir.name),
            "short": _safe_name(sdir.name)[:8],
            "live": live,
            "ended": ended,
            "lastActivity": last.isoformat(),
            "agents": [{k: v for k, v in a.items() if k != "_last"} for a in agents],
        })
    sessions.sort(key=lambda s: s["lastActivity"], reverse=True)
    return sessions, by_agent


def feed_and_totals(now: datetime, by_agent: dict) -> tuple[list[dict], dict, list[int]]:
    midnight = _local_midnight(now)
    window = now - timedelta(hours=24)
    events = []
    hourly = [0] * 24  # tool calls per hour, oldest first, last bucket = this hour
    totals = {"toolCalls": 0, "spawned": 0, "denied": 0, "errors": 0, "tokensOut": 0}
    for day in _recent_day_dirs(ORG / "audit"):
        if not day.is_dir():
            continue
        for f in day.glob("*.jsonl"):
            sess = _safe_name(f.name.split(".")[0])
            for e in _jsonl(f):
                ts = _parse_ts(e.get("ts"))
                if not ts or ts < window:
                    continue
                kind = e.get("kind")
                aid = _safe_name(str(e.get("agentId") or "")) or None
                agent = by_agent.get(aid) if aid else None
                label = "main" if not aid else (agent["type"] if agent else "subagent")
                today = ts >= midnight
                if kind == "tool.call":
                    h = int((now - ts).total_seconds() // 3600)
                    if 0 <= h < 24:
                        hourly[23 - h] += 1
                    if today:
                        totals["toolCalls"] += 1
                        totals["denied"] += 1 if e.get("denied") else 0
                        totals["errors"] += 1 if e.get("isError") else 0
                elif kind == "agent.spawn" and today:
                    totals["spawned"] += 1
                elif kind == "turn.complete" and today:
                    totals["tokensOut"] += int(((e.get("usage") or {}).get("output")) or 0)
                events.append({
                    "ts": ts.isoformat(),
                    "session": sess[:8],
                    "kind": _cap(kind, 30),
                    "agent": _cap(label if kind != "agent.spawn" else (e.get("subagentType") or "subagent"), 40),
                    "agentId": aid,
                    "tool": _cap(e.get("tool"), 60),
                    "denied": bool(e.get("denied")),
                    "isError": bool(e.get("isError")),
                    "reason": _cap(e.get("reason"), 30),
                    "durationMs": e.get("durationMs") if isinstance(e.get("durationMs"), (int, float)) else None,
                    "description": _cap(e.get("description"), 120),
                    "deny": _cap(e.get("deny")),
                })
    events.sort(key=lambda x: x["ts"], reverse=True)
    return events[:FEED_LIMIT], totals, hourly


def gates(now: datetime) -> dict:
    midnight = _local_midnight(now)
    counts = {"allow": 0, "ask": 0, "deny": 0, "observe": 0}
    by_hook: dict[str, dict[str, int]] = {}
    fell_open = 0
    notable = []
    for f in _recent_day_dirs(STATE / "verdict", days=1):
        if not f.is_file():
            continue
        for e in _jsonl(f):
            if e.get("test"):
                continue
            ts = _parse_ts(e.get("ts"))
            if not ts or ts < midnight:
                continue
            eff = e.get("effective")
            if eff in counts:
                counts[eff] += 1
            hook = _safe_name(str(e.get("hook") or "?")) or "?"
            hk = by_hook.setdefault(hook, {"allow": 0, "ask": 0, "deny": 0, "observe": 0})
            if eff in hk:
                hk[eff] += 1
            if e.get("decided") is False:
                fell_open += 1
            if eff in ("ask", "deny") or e.get("decided") is False:
                notable.append({
                    "ts": ts.isoformat(), "hook": hook, "rule": _cap(e.get("rule"), 60),
                    "verdict": eff if e.get("decided") is not False else "fell open",
                    "reason": _cap(e.get("reason")),
                })
    notable.sort(key=lambda x: x["ts"], reverse=True)
    hooks = sorted(by_hook.items(), key=lambda kv: -sum(kv[1].values()))[:8]
    return {"counts": counts, "fellOpen": fell_open,
            "byHook": [{"hook": h, **c} for h, c in hooks], "notable": notable[:20]}


def backlog(now: datetime) -> dict:
    out: dict = {"reviewQueue": None, "commitments": None}
    if REVIEW_QUEUE.parent.is_dir():
        rows = _jsonl(REVIEW_QUEUE)
        ages, by_bat = [], {}
        for r in rows:
            bat = _safe_name(str(r.get("bat") or "?")) or "?"
            by_bat[bat] = by_bat.get(bat, 0) + 1
            ts = _parse_ts(r.get("ts"))
            if ts:
                ages.append((now - ts).days)
        out["reviewQueue"] = {
            "depth": len(rows), "oldestDays": max(ages) if ages else 0,
            "byAutomation": [{"name": k, "count": v}
                             for k, v in sorted(by_bat.items(), key=lambda kv: -kv[1])[:5]],
        }
    # The commitments register itself (same schema in every vault); overdue is
    # computed here rather than read from a vault-only export.
    c = _json(STATE / "commitments.json")
    if isinstance(c, dict) and isinstance(c.get("commitments"), list):
        items = [x for x in c["commitments"] if isinstance(x, dict) and not x.get("done")]
        today = now.date().isoformat()
        overdue = [x for x in items if isinstance(x.get("due"), str) and len(x["due"]) == 10 and x["due"] < today]
        overdue.sort(key=lambda x: str(x.get("due") or ""))
        out["commitments"] = {
            "open": len(items), "overdue": len(overdue),
            "generated": None,
            "top": [{"id": _safe_name(str(x.get("id") or "")), "what": _cap(x.get("what"), 110),
                     "due": _cap(x.get("due"), 10)} for x in overdue[:6]],
        }
    return out


def specialists(now: datetime) -> list[dict]:
    """Specialist proposals with the user's decision, newest first (A2, security review):
    the dashboard shows the FULL brief Zeus wrote, so an approval is made on what the
    specialist will actually be told. Read-only; text is untrusted and capped."""
    spec_dir = ORG / "specialists"
    if not spec_dir.is_dir():
        return []
    approvals = (_json(ORG / "approvals.json") or {}).get("approvals") or {}
    out = []
    for f in spec_dir.glob("*.json"):
        p = _json(f)
        if not isinstance(p, dict) or not isinstance(p.get("id"), str):
            continue
        a = approvals.get(p["id"]) if isinstance(approvals, dict) else None
        status = (a or {}).get("status") or "pending"
        if status == "approved":
            sb = _parse_ts((a or {}).get("startBy"))
            if sb and sb < now:
                status = "lapsed"
        out.append({
            "id": _safe_name(p["id"]),
            "title": _cap(p.get("title"), 80),
            "purpose": _cap(p.get("purpose"), 300),
            "task": _cap(p.get("task"), 600),
            "tools": [_cap(t, 30) for t in (p.get("tools") or []) if isinstance(t, str)][:8],
            "maxMinutes": p.get("maxMinutes") if isinstance(p.get("maxMinutes"), int) else None,
            "brief": _cap(p.get("prompt"), 4000),
            "proposedBy": _cap(p.get("proposedBy"), 30),
            "proposedAt": p.get("proposedAt") if isinstance(p.get("proposedAt"), str) else None,
            "status": _cap(status, 20),
            "decidedVia": _cap((a or {}).get("decidedVia"), 20),
        })
    out.sort(key=lambda x: x.get("proposedAt") or "", reverse=True)
    return out[:20]


def build_state() -> dict:
    if DEMO:
        from demo import demo_state  # dashboard/demo.py, next to this file
        return demo_state()
    now = datetime.now().astimezone()
    sessions, by_agent = sessions_and_agents(now)
    feed, totals, hourly = feed_and_totals(now, by_agent)
    totals["liveSessions"] = sum(1 for s in sessions if s["live"])
    running = [a for s in sessions if s["live"] for a in s["agents"]
               if a["state"] == "running" and a["key"] != "main"]
    totals["runningAgents"] = len(running)
    return {
        "generated": now.isoformat(timespec="seconds"),
        "tz": now.tzname(),
        "seats": seats(),
        "sessions": sessions,
        "feed": feed,
        "hourly": hourly,
        "totals": totals,
        "gates": gates(now),
        "backlog": backlog(now),
        "specialists": specialists(now),
    }


# ---------------------------------------------------------------- server ---

class State:
    last_poll: float | None = None
    started = time.time()


class Handler(BaseHTTPRequestHandler):
    server_version = "agent-org"
    sys_version = ""

    def log_message(self, fmt, *args):  # quiet: no request log to a console
        return

    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").lower()
        port = self.server.server_address[1]
        return host in (f"127.0.0.1:{port}", f"localhost:{port}")

    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("Content-Security-Policy", CSP)
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self._host_ok():
            return self._send(421, b"wrong host", "text/plain; charset=utf-8")
        path = self.path.split("?", 1)[0]
        if path == "/api/state":
            State.last_poll = time.time()
            try:
                body = json.dumps(build_state(), ensure_ascii=False).encode("utf-8")
            except Exception as exc:  # surface, never a silent blank page
                body = json.dumps({"error": f"could not read state: {type(exc).__name__}"}).encode()
                return self._send(500, body, "application/json; charset=utf-8")
            return self._send(200, body, "application/json; charset=utf-8")
        if path == "/api/ping":
            return self._send(200, MARKER.encode(), "text/plain; charset=utf-8")
        if path in STATIC:
            name, ctype = STATIC[path]
            try:
                body = (HERE / name).read_bytes()
            except OSError:
                return self._send(404, b"missing", "text/plain; charset=utf-8")
            return self._send(200, body, ctype)
        return self._send(404, b"not found", "text/plain; charset=utf-8")

    def do_POST(self):  # read-only surface
        self._send(405, b"read-only", "text/plain; charset=utf-8")

    do_PUT = do_DELETE = do_PATCH = do_POST


def _idle_watch(httpd: ThreadingHTTPServer):
    while True:
        time.sleep(5)
        now = time.time()
        if State.last_poll is None:
            if now - State.started > FIRST_POLL_GRACE_S:
                break
        elif now - State.last_poll > IDLE_EXIT_S:
            break
    httpd.shutdown()


class ExclusiveServer(ThreadingHTTPServer):
    """No port sharing. HTTPServer turns SO_REUSEADDR on by default, and on Windows
    that lets a SECOND process bind the same port and take requests meant for this
    one (found 2026-10-08: two dashboards answering on 8765). Exclusive use instead:
    a port already taken fails to bind, and we move to the next one."""
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        import socket
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):  # Windows
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def _bind() -> ThreadingHTTPServer:
    for port in (PREFERRED_PORT, PREFERRED_PORT + 1, PREFERRED_PORT + 2, 0):
        try:
            return ExclusiveServer((HOST, port), Handler)
        except OSError:
            continue
    raise OSError("no free loopback port")


def serve() -> int:
    httpd = _bind()
    port = httpd.server_address[1]
    try:
        ORG.mkdir(parents=True, exist_ok=True)
        WEB_INFO.write_text(json.dumps({"port": port, "pid": os.getpid(),
                                        "started": datetime.now().astimezone().isoformat(timespec="seconds")}),
                            encoding="utf-8")
    except OSError:
        pass
    threading.Thread(target=_idle_watch, args=(httpd,), daemon=True).start()
    try:
        httpd.serve_forever(poll_interval=0.5)
    finally:
        httpd.server_close()
        try:
            info = _json(WEB_INFO)
            if isinstance(info, dict) and info.get("pid") == os.getpid():
                WEB_INFO.unlink()
        except OSError:
            pass
    return 0


def _live_port() -> int | None:
    info = _json(WEB_INFO)
    if not isinstance(info, dict) or not isinstance(info.get("port"), int):
        return None
    port = info["port"]
    try:
        with urllib.request.urlopen(f"http://{HOST}:{port}/api/ping", timeout=1.5) as r:
            if r.read().decode("utf-8", "replace") == MARKER:
                return port
    except Exception:
        return None
    return None


def launch() -> int:
    port = _live_port()
    if port is None:
        flags = 0
        if os.name == "nt":
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        exe = sys.executable
        if os.name == "nt":  # pythonw has no console window to flash or close
            w = Path(exe).with_name("pythonw.exe")
            if w.exists():
                exe = str(w)
        subprocess.Popen([exe, str(Path(__file__).resolve()), "--serve", *(["--demo"] if DEMO else [])],
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, close_fds=True, creationflags=flags,
                         start_new_session=(os.name != "nt"))
        for _ in range(40):
            time.sleep(0.25)
            port = _live_port()
            if port:
                break
    if not port:
        print("agent-org dashboard: server did not start", file=sys.stderr)
        return 1
    url = f"http://{HOST}:{port}/"
    try:
        webbrowser.open(url)
    except Exception:
        pass
    print(url)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--launch", action="store_true")
    g.add_argument("--serve", action="store_true")
    g.add_argument("--dump", action="store_true")
    ap.add_argument("--demo", action="store_true", help="serve the sample org (no real data)")
    a = ap.parse_args()
    if a.demo:
        global DEMO, MARKER, WEB_INFO, PREFERRED_PORT
        DEMO = True
        MARKER = "agent-org-dashboard-demo"
        WEB_INFO = ORG / "web-demo.json"
        PREFERRED_PORT = 8775
        sys.path.insert(0, str(HERE))
    try:  # Windows consoles default to cp1252; never let '…' crash or mangle output
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if a.dump:
        print(json.dumps(build_state(), indent=1, ensure_ascii=False))
        return 0
    if a.serve:
        return serve()
    return launch()


if __name__ == "__main__":
    sys.exit(main())
