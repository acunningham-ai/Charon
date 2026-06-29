#!/usr/bin/env python3
"""
UserPromptSubmit hook: scan the submitted prompt for injection/poisoning
markers (AGT borrow #2). SHADOW mode — logs an `observe` verdict when markers
are found; never blocks, never alters the prompt.

Why UserPromptSubmit: it's the choke point where untrusted content enters the
model — captured email/Teams text pasted in, or content a skill folds into the
prompt. Catches instruction-shaped attacks the secret-scan misses.

Promotion path (later, after a clean shadow window): on high severity, surface
a warning to the user (ask) rather than silently observe. Detection logic lives in
_poisoning.py; this hook is just the wiring.

Privacy: logs categories + score + severity ONLY — never the matched text
(untrusted content may itself contain secrets; verdict-vocabulary rule #4).

Exit 0 always (shadow). Own failures never block.
"""
import json
import sys
from pathlib import Path

try:
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

try:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _verdict import emit_verdict  # noqa: E402
except Exception:
    def emit_verdict(*args, **kwargs):  # type: ignore
        return kwargs.get("verdict", "allow")

try:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _poisoning import scan  # noqa: E402
except Exception:
    scan = None

HOOK_NAME = "poisoning-scan"


def main() -> int:
    if scan is None:
        return 0  # detector missing — fail-silent, never block
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    prompt = data.get("prompt") or data.get("user_prompt") or data.get("message") or ""
    if not prompt:
        return 0
    try:
        result = scan(prompt)
    except Exception:
        return 0
    if result["severity"] == "none":
        return 0  # clean — no log noise

    emit_verdict(
        hook=HOOK_NAME,
        rule=f"poisoning-shadow:{result['severity']}",
        verdict="observe",  # shadow: log, never block
        reason=(
            f"prompt shows injection/poisoning markers "
            f"(severity={result['severity']}, score={result['score']}, "
            f"categories={','.join(result['categories'])})"
        ),
        context={
            "severity": result["severity"],
            "score": result["score"],
            "categories": result["categories"],  # NO matched text (privacy)
        },
        session_id=data.get("session_id", ""),
    )
    return 0  # shadow — always allow


if __name__ == "__main__":
    sys.exit(main())
