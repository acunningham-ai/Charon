#!/usr/bin/env python3
"""harness_autoheal.py — human-gated auto-heal (PROPOSE-ONLY).

WHAT: closes the last step of the self-healing loop for a SMALL, pre-approved set
of fixes — detect (harness watch) -> surface -> you approve -> apply (closed allowlist) ->
deterministic post-check -> confirm | rollback+escalate.

STATUS: propose-only stub. `apply()` executes NOTHING while PROPOSE_ONLY=True — it
records the proposal and returns. Real execution stays gated until:
  1. /secure-code-review + /owasp-agentic-review pass (action-capable = highest bar),
  2. a propose-only shadow fortnight is clean,
  3. PROPOSE_ONLY is flipped to False by a deliberate human edit.
KEYSTONE — observe != act: the harness watch (scripts/harness-watch.py)
is read-only and MUST NEVER import or call this module. Auto-heal is reachable
ONLY by an explicit human invocation via /harness-heal <id>. That separation is
what keeps the unattended loop incapable of action.

Never raises into the caller for a missing/broken allowlist — fails closed
(refuses to propose/apply) with a clear message.
"""
import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
# NB: no `import subprocess` in the scaffold — apply() executes nothing while
# PROPOSE_ONLY=True. The live-path build re-adds it inside the apply block, never
# at module top level (keeps execution capability out of the propose-only surface).
# (secure-code-review SCF-1, 2026-07-14.)

# ---- STATUS: PROPOSE-ONLY by design ------------------------------------
# The propose step is HUMAN-TRIGGERED: a scheduled auto-propose would put an
# unattended process inside the apply-capable module and break observe != act.
# So evidence only accrues when you run `/harness-heal <id>` after the watch
# flags a matching rule (e.g. `capture-gap`). Accrue real proposals for a few
# weeks before considering a live apply path, and build that path behind its
# own security review — it is deliberately not implemented here.
PARKED = True

# ---- master safety flag -------------------------------------------------
# The single switch that makes this module action-capable. Do NOT flip without
# the gate above. While True, apply() is a hard no-op regardless of arguments.
PROPOSE_ONLY = True

THIS_DIR = Path(__file__).resolve().parent
HOOKS_DIR = THIS_DIR / "hooks"
sys.path.insert(0, str(HOOKS_DIR))
try:
    from _verdict import emit_verdict  # noqa: E402
except Exception:
    def emit_verdict(*args, **kwargs):  # type: ignore
        return kwargs.get("verdict", "allow")

HOOK_NAME = "harness-autoheal"
ALLOWLIST_PATH = THIS_DIR / "harness-autoheal-allowlist.json"

# ---- hard-coded never-auto deny-list (control #7) -----------------------
# Checked in CODE, not just convention. A remediation whose action or intent
# touches any of these is refused even if it somehow reached the allowlist.
# Substring match against the action path + id, case-insensitive.
NEVER_AUTO_MARKERS = (
    "reauth", "auth", "device-code",        # credential reauth needs a human at a browser
    "systemctl", "restart", "service",       # service restarts
    "secret", ".secrets", "credential",      # secrets
    "payroll", "board",                      # payroll / board-facing data
    "memory", "claude.md", ".claude/rules",  # authored-content / config mutation
)


def _project_dir() -> Path:
    import os
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    return Path(env) if env else THIS_DIR.parent


def _capture_root() -> Path:
    sys.path.insert(0, str(THIS_DIR))
    try:
        from lib.harness_paths import capture_pipeline_root  # noqa: E402
        return capture_pipeline_root()
    except Exception:
        return Path.home() / "capture-pipeline"


def _resolve(rel: str) -> Path:
    """Resolve an allowlist path. capture-pipeline/* resolves to your capture
    install (HARNESS_CAPTURE_ROOT, default ~/capture-pipeline); everything else is
    vault-relative."""
    rel = rel.replace("\\", "/")
    if rel.startswith("capture-pipeline/"):
        return _capture_root() / rel[len("capture-pipeline/"):]
    return _project_dir() / rel


def load_allowlist() -> list:
    """Return the remediation list, or [] on any error (fail-closed)."""
    try:
        cfg = json.loads(ALLOWLIST_PATH.read_text(encoding="utf-8"))
        rems = cfg.get("remediations")
        return rems if isinstance(rems, list) else []
    except Exception:
        return []


def _find(rid: str):
    for r in load_allowlist():
        if r.get("id") == rid:
            return r
    return None


def _never_auto_reason(rem: dict):
    """Return a reason string if this remediation hits the never-auto deny-list, else None."""
    hay = (str(rem.get("id", "")) + " "
           + str((rem.get("action") or {}).get("path", ""))).lower()
    for m in NEVER_AUTO_MARKERS:
        if m in hay:
            return f"action/id matches never-auto marker {m!r}"
    return None


# ---- precondition gate (control #2) -------------------------------------
# Re-verified at apply time, not just when the signal was surfaced. Pure checks
# against machine state; no model judgement.

def _precondition_ok(name: str):
    """Return (ok: bool, detail: str) for a named precondition."""
    if name == "auth_healthy":
        flag = _resolve("capture-pipeline/state/REAUTH-NEEDED.flag")
        return (not flag.exists(), "REAUTH-NEEDED.flag present" if flag.exists() else "no reauth flag")
    if name == "not_running":
        lock = _resolve("capture-pipeline/state/fetch-mail.lock")
        return (not lock.exists(), "fetch-mail.lock held" if lock.exists() else "no lock held")
    if name == "capture_completed_today":
        cap = _resolve("capture-pipeline/state/captured.json")
        try:
            mt = datetime.fromtimestamp(cap.stat().st_mtime, timezone.utc).date()
            today = datetime.now(timezone.utc).date()
            return (mt == today, f"captured.json mtime date={mt}, today={today}")
        except OSError:
            return (False, "captured.json missing")
    return (False, f"unknown precondition {name!r}")


def _check_preconditions(rem: dict):
    """Return (all_ok, [(name, ok, detail), ...])."""
    results = [(p, *_precondition_ok(p)) for p in rem.get("preconditions", [])]
    return (all(ok for _, ok, _ in results), results)


def propose(rid: str) -> dict:
    """Surface a proposal for remediation `rid`: validate it, run the precondition
    gate + never-auto check, emit a verdict, and return a structured proposal.
    Takes NO action. Safe to call anytime."""
    rem = _find(rid)
    if rem is None:
        emit_verdict(hook=HOOK_NAME, rule="unknown-remediation", verdict="deny",
                     reason=f"remediation {rid!r} not in allowlist", context={"id": rid})
        return {"id": rid, "ok": False, "reason": "not in allowlist"}

    na = _never_auto_reason(rem)
    if na:
        emit_verdict(hook=HOOK_NAME, rule="never-auto-blocked", verdict="deny",
                     reason=f"{rid}: {na}", context={"id": rid})
        return {"id": rid, "ok": False, "reason": f"never-auto: {na}"}

    all_ok, checks = _check_preconditions(rem)
    emit_verdict(
        hook=HOOK_NAME, rule="autoheal-proposed", verdict="ask",
        reason=(f"PROPOSE-ONLY: remediation {rid} for trigger {rem.get('trigger_rule')!r}; "
                f"preconditions {'MET' if all_ok else 'NOT met'}"),
        context={"id": rid, "action": rem.get("action"), "preconditions_met": all_ok,
                 "checks": [{"name": n, "ok": ok, "detail": d} for n, ok, d in checks],
                 "propose_only": PROPOSE_ONLY},
    )
    return {"id": rid, "ok": all_ok, "remediation": rem,
            "preconditions": [{"name": n, "ok": ok, "detail": d} for n, ok, d in checks]}


def apply(rid: str, approver: str = "") -> dict:
    """Apply remediation `rid`. In PROPOSE_ONLY mode (default) this executes
    NOTHING — it records that an apply was requested and returns. The real
    apply path (precondition re-gate -> run action -> deterministic post-check
    -> confirm | rollback+escalate -> audit) is intentionally NOT wired until
    the gate in the module docstring is cleared."""
    if PROPOSE_ONLY:
        rem = _find(rid)
        emit_verdict(
            hook=HOOK_NAME, rule="autoheal-apply-suppressed", verdict="observe",
            reason=f"PROPOSE-ONLY stub: apply({rid}) requested but NOT executed (scaffold)",
            context={"id": rid, "approver": approver, "would_run": (rem or {}).get("action"),
                     "propose_only": True},
        )
        return {"id": rid, "applied": False, "reason": "propose-only stub — nothing executed"}

    # --- LIVE PATH (unreachable while PROPOSE_ONLY=True) ------------------
    # Left deliberately unimplemented in the scaffold. Building it out is a
    # separate, review-gated step: precondition re-gate + never-auto re-check +
    # rollback snapshot + run action (bat / run-with-timeout.ps1) + deterministic
    # post-check + audit, with NO blind retry on failure (control #4).
    raise NotImplementedError(
        "Live apply not implemented — flip PROPOSE_ONLY only after the "
        "review gate + propose-only shadow (see module docstring)."
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="Auto-heal (propose-only)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--list", action="store_true", help="list allowlisted remediations")
    g.add_argument("--propose", metavar="ID", help="surface a proposal for remediation ID (no action)")
    g.add_argument("--apply", metavar="ID", help="request apply (no-op while PROPOSE_ONLY)")
    ap.add_argument("--approver", default="", help="who approved (recorded in the audit)")
    args = ap.parse_args()

    if args.list:
        rems = load_allowlist()
        if not rems:
            print("No remediations (allowlist missing or empty).")
            return 1
        print(f"Auto-heal remediations (PROPOSE_ONLY={PROPOSE_ONLY}):")
        for r in rems:
            print(f"  {r['id']:20} trigger={r.get('trigger_rule'):20} "
                  f"action={(r.get('action') or {}).get('path')}")
        return 0

    if args.propose:
        result = propose(args.propose)
        print(json.dumps(result, indent=2, default=str))
        return 0 if result.get("ok") else 1

    if args.apply:
        result = apply(args.apply, approver=args.approver)
        print(json.dumps(result, indent=2, default=str))
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
