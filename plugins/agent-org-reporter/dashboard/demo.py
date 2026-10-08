"""
Agent Org dashboard — demo data (`server.py --demo`, Charon port plan W1).

A sample org with believable, moving activity, for screenshots that must contain
NO real data (plan D2). Reads no files: everything is made from the clock, so
the page moves like a live session. Same shape as server.build_state().

The seat names are the ones Charon ships (they are the product, not private
data). Every task, session id, count, hook reason and commitment below is
invented. The pane tells the same story in hooks/demo.ts; keep the two in step.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta

SPEC = "agent-org-reporter:spec-"
SESSION_A = "7f3c21aa-demo-4a1e-9c2b-5d0e8f1a2b3c"
SESSION_B = "c94e0d5b-demo-47d2-8e1f-0a9b8c7d6e5f"
SESSION_C = "2b81f0c4-demo-4c3d-a1b2-3e4f5a6b7c8d"

SEATS = ["athena", "calliope", "cerberus", "helios", "hephaestus", "knowledge-synthesizer",
         "owasp-agentic-reviewer", "owasp-llm-reviewer", "prometheus", "secure-code-reviewer", "zeus"]

# key, agentId, parent, type, description, started (s ago), call every (s), tools, session,
# finished (s ago, or None), limit minutes
LANES = [
    ("main", None, None, "main", "", 52 * 60, 6, ["Agent", "Read", "Bash"], SESSION_A, None, None),
    ("z1", "z1", None, "zeus", "Prepare the weekly security brief", 9 * 60, 7,
     ["Agent", "Read", "Agent", "Grep"], SESSION_A, None, None),
    ("a1", "a1", "z1", "athena", "Find last week's vendor review notes", 4 * 60, 2.1,
     ["Grep", "Read", "Glob", "Read"], SESSION_A, None, None),
    ("p1", "p1", "z1", "prometheus", "Scan this week's advisories for the stack", 7 * 60, 3.3,
     ["WebSearch", "WebFetch", "WebFetch"], SESSION_A, None, None),
    ("s1", "s1", "z1", SPEC + "licence-scan", "Check new dependencies' licences", 6 * 60, 4.2,
     ["Read", "WebFetch"], SESSION_A, None, 15),
    ("c1", "c1", "z1", "calliope", "Draft the summary for the team", 252, 4,
     ["Read", "Write"], SESSION_A, 40, None),
    ("main", None, None, "main", "", 21 * 60, 9, ["Skill", "Read"], SESSION_B, None, None),
    ("h1", "h1", None, "hephaestus", "Weekly harness tune-up", 3 * 60, 5,
     ["Skill", "Read", "Grep"], SESSION_B, None, None),
    ("main", None, None, "main", "", 5 * 3600, 30, ["Read"], SESSION_C, 3 * 3600, None),
]

FEED_SCRIPT = [
    ("athena", "a1", "tool.call", "Grep", False, False),
    ("prometheus", "p1", "tool.call", "WebSearch", False, False),
    ("zeus", "z1", "agent.spawn", None, False, False),
    ("spec-licence-scan", "s1", "tool.call", "WebFetch", False, False),
    ("athena", "a1", "tool.call", "Read", False, False),
    ("main", None, "tool.call", "Read", False, False),
    ("prometheus", "p1", "tool.call", "WebFetch", False, True),
    ("hephaestus", "h1", "tool.call", "Skill", False, False),
    ("zeus", "z1", "agent.spawn.denied", None, True, False),
    ("calliope", "c1", "turn.complete", None, False, False),
    ("athena", "a1", "tool.call", "Glob", False, False),
    ("spec-licence-scan", "s1", "tool.call", "Read", False, False),
]
FEED_STEP_S = 2.5

_epoch = datetime.now().astimezone()


def _noise(i: int) -> float:
    x = (i * 2654435761 + 0x9E3779B9) & 0xFFFFFFFF
    x ^= x >> 13
    x = (x * 0xC2B2AE35) & 0xFFFFFFFF
    x ^= x >> 16
    return x / 4294967296


def _iso(dt: datetime) -> str:
    return dt.isoformat(timespec="seconds")


def _call_times(now: datetime, every: float, seed: int) -> list[int]:
    ms = now.timestamp() * 1000
    step = every * 1000
    end = int(ms // step)
    out = []
    for i in range(end, end - 60, -1):
        if len(out) >= 40:
            break
        if _noise(i * 31 + seed) > 0.3:
            t = int(i * step + _noise(i + seed) * step * 0.6)
            if t <= ms:
                out.insert(0, t)
    return out


def _sessions(now: datetime) -> list[dict]:
    by_sess: dict[str, list[dict]] = {}
    for key, aid, parent, typ, desc, started_s, every, tools, sess, fin_s, limit in LANES:
        if fin_s is not None:
            finished = now - timedelta(seconds=fin_s)
            started = finished - timedelta(seconds=started_s)
        else:
            finished = None
            started = _epoch - timedelta(seconds=started_s)
        times = [] if finished else _call_times(now, every, ord(key[0]))
        tick = int(now.timestamp() // every)
        tool = tools[tick % len(tools)]
        in_tool = not finished and _noise(tick * 7 + len(key)) > 0.25
        calls = max(1, int(((finished or now) - started).total_seconds() / every))
        last = finished or (datetime.fromtimestamp(times[-1] / 1000).astimezone() if times else now)
        by_sess.setdefault(sess, []).append({
            "key": key, "agentId": aid, "type": typ, "description": desc,
            "state": "finished" if finished else "running", "background": False,
            "startedAt": _iso(started), "lastActivity": _iso(last),
            "toolCalls": calls, "toolErrors": 1 if typ == "prometheus" else 0,
            "toolDenies": 1 if typ == "zeus" else 0, "turns": max(1, calls // 9),
            "model": "inherit", "tokensOut": calls * 410, "tokensIn": calls * 5200,
            "deniedBy": None, "parentAgentId": parent,
            "currentTool": tool if in_tool else None,
            "currentSince": _iso(datetime.fromtimestamp(tick * every).astimezone()) if in_tool else None,
            "lastTool": tool, "finishedAt": _iso(finished) if finished else None,
            "callTimes": times,
        })
    out = []
    for sess, agents in by_sess.items():
        last = max(a["lastActivity"] for a in agents)
        main = next(a for a in agents if a["key"] == "main")
        ended = main["state"] == "finished"
        agents.sort(key=lambda a: (a["key"] != "main", a["lastActivity"]), reverse=False)
        out.append({"id": sess, "short": sess[:8], "live": not ended, "ended": ended,
                    "lastActivity": last, "agents": agents})
    out.sort(key=lambda s: s["lastActivity"], reverse=True)
    return out


def _feed(now: datetime) -> list[dict]:
    step = int(now.timestamp() // FEED_STEP_S)
    rows = []
    for k in range(40):
        i = step - k
        agent, aid, kind, tool, denied, err = FEED_SCRIPT[i % len(FEED_SCRIPT)]
        ts = datetime.fromtimestamp(i * FEED_STEP_S).astimezone()
        row = {"ts": _iso(ts), "session": SESSION_A[:8] if agent != "hephaestus" else SESSION_B[:8],
               "kind": "agent.spawn" if kind.startswith("agent.spawn") else kind,
               "agent": agent, "agentId": aid, "tool": tool, "denied": denied, "isError": err,
               "reason": "answer" if kind == "turn.complete" else None,
               "durationMs": 252000 if kind == "turn.complete" else None,
               "description": None, "deny": None}
        if kind == "agent.spawn":
            row.update(agent="athena", description="Find last week's vendor review notes")
        if kind == "agent.spawn.denied":
            row.update(agent="general-purpose", description="Search everything for vendor notes",
                       deny="Zeus may start only roster seats and approved specialists.")
        rows.append(row)
    return rows


def _hourly(now: datetime) -> list[int]:
    h = now.hour
    out = []
    for k in range(24):
        hour = (h - 23 + k) % 24
        work = 8 <= hour <= 18
        v = (60 + 50 * math.sin(hour / 2.0) + _noise(hour) * 45) if work else _noise(hour + 50) * 8
        out.append(max(0, int(v)))
    return out


def demo_state() -> dict:
    now = datetime.now().astimezone()
    sessions = _sessions(now)
    running = [a for s in sessions if s["live"] for a in s["agents"]
               if a["state"] == "running" and a["key"] != "main"]
    run_s = int((now - _epoch).total_seconds())
    return {
        "demo": True,
        "generated": _iso(now),
        "tz": now.tzname(),
        "seats": [{"name": n} for n in SEATS],
        "sessions": sessions,
        "feed": _feed(now),
        "hourly": _hourly(now),
        "totals": {"toolCalls": 1486 + run_s // 3, "spawned": 23, "denied": 2, "errors": 4,
                   "tokensOut": 412300 + run_s * 124, "liveSessions": sum(1 for s in sessions if s["live"]),
                   "runningAgents": len(running)},
        "gates": {
            "counts": {"allow": 612, "ask": 9, "deny": 2, "observe": 148},
            "fellOpen": 0,
            "byHook": [
                {"hook": "validate-write-path", "allow": 288, "ask": 0, "deny": 1, "observe": 0},
                {"hook": "phase-gate", "allow": 171, "ask": 5, "deny": 0, "observe": 0},
                {"hook": "poisoning-scan-read", "allow": 0, "ask": 0, "deny": 0, "observe": 96},
                {"hook": "deny-destructive", "allow": 153, "ask": 4, "deny": 1, "observe": 0},
                {"hook": "save-on-mention", "allow": 0, "ask": 0, "deny": 0, "observe": 52},
            ],
            "notable": [
                {"ts": _iso(now - timedelta(minutes=6)), "hook": "deny-destructive", "rule": "recursive-delete",
                 "verdict": "ask", "reason": "Recursive delete outside the scratch folder needs your OK."},
                {"ts": _iso(now - timedelta(minutes=19)), "hook": "validate-write-path", "rule": "protected-zone",
                 "verdict": "deny", "reason": "Published posts are read-only once posted."},
                {"ts": _iso(now - timedelta(minutes=41)), "hook": "phase-gate", "rule": "plan-before-build",
                 "verdict": "ask", "reason": "Writing code before the plan was confirmed."},
            ],
        },
        "backlog": {
            "reviewQueue": {"depth": 3, "oldestDays": 2,
                            "byAutomation": [{"name": "morning-update", "count": 2},
                                             {"name": "weekly-digest", "count": 1}]},
            "commitments": {"open": 9, "overdue": 2, "generated": _iso(now)[:10],
                            "top": [{"id": "C004", "what": "Send the quarterly access review to the team leads",
                                     "due": (now - timedelta(days=3)).date().isoformat()},
                                    {"id": "C007", "what": "Renew the vendor register review",
                                     "due": (now - timedelta(days=1)).date().isoformat()}]},
        },
        "specialists": [
            {"id": "demo-dpa-check", "title": "Compare a vendor DPA against the data-retention guideline",
             "purpose": "No seat reads contracts clause by clause; this needs one careful pass.",
             "task": "Read the supplied DPA and list every retention clause that is longer than the guideline allows.",
             "tools": ["Read", "WebFetch"], "maxMinutes": 20,
             "brief": ("You are checking one vendor data processing agreement. Read the DPA at the path given, "
                       "then the retention guideline. For each clause about how long data is kept, quote it, "
                       "give the period, and say whether it is within the guideline. Report clause numbers and "
                       "quotes only; do not summarise the contract."),
             "proposedBy": "zeus", "proposedAt": _iso(now - timedelta(minutes=2)),
             "status": "pending", "decidedVia": None},
            {"id": "demo-licence-scan", "title": "Check new dependencies' licences",
             "purpose": "", "task": "", "tools": ["Read", "WebFetch"], "maxMinutes": 15, "brief": "",
             "proposedBy": "zeus", "proposedAt": _iso(now - timedelta(minutes=14)),
             "status": "started", "decidedVia": "pane"},
        ],
    }
