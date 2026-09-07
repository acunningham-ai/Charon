#!/usr/bin/env python3
"""
UserPromptSubmit hook: scan the submitted prompt for injection/poisoning
markers. SHADOW mode — logs an `observe` verdict when markers are found; never
blocks, never alters the prompt.

Why UserPromptSubmit: it's the choke point where untrusted content enters the
model — captured email/Teams text pasted in, or content a skill folds into the
prompt. Catches instruction-shaped attacks the secret-scan misses.

────────────────────────────────────────────────────────────────────────────
RE-SCOPED — scan untrusted spans, not the whole prompt.

The original wiring scanned the WHOLE prompt, which meant it scanned **your own
typed words**. If your work touches security at all — describing prompt
injection, exfiltration, or agentic abuse — you trip an injection detector
continuously just by doing your job. In the reference deployment every one of
the 43 shadow fires was this class, including a high-severity fire raised by a
discussion of acquisition security.

The category error: the hook was watching the one input source that **cannot be
an attacker**. Poisoning detection belongs on untrusted input.

Now: scan only the parts of the prompt carrying UNTRUSTED provenance —
recognised capture wrappers, quoted capture blocks, or fetched/tool-returned
content folded in by a skill. A prompt that is purely you typing is skipped
before the detector ever runs.

⚠️ Deliberately NOT using a describes-vs-contains discriminator here. On
untrusted content that check is an evasion surface (wrap the payload in
backticks and walk straight through), so provenance — not phrasing — decides
whether the detector runs.

Promotion path (later, after a clean shadow window on this scope): on high
severity, surface a warning (ask) rather than silently observe. Detection logic
lives in _poisoning.py; this hook is just the wiring.

Privacy: logs categories + score + severity ONLY — never the matched text
(untrusted content may itself contain secrets; verdict-vocabulary rule #4).

Exit 0 always (shadow). Own failures never block.
"""
import json
import re
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

# Markers that a span of the prompt did NOT come from your keyboard. Kept
# narrow and provenance-based: each is a wrapper the harness itself emits around
# untrusted material, or an unmistakable tool-return envelope.
UNTRUSTED_MARKERS = (
    "untrusted captured content",
    "trust: untrusted",
    "trust: derived-untrusted",
    "derived from untrusted input",
    "<untrusted>",
    "00-inbox/_captured",
    "system-reminder",
    "tool_result",
    "<function_results>",
)

# Minimum length for a quoted block to be treated as pasted-in foreign content
# rather than you quoting a phrase mid-sentence.
PASTED_BLOCK_CHARS = 400


def untrusted_spans(prompt: str) -> str:
    """
    Return only the parts of the prompt with untrusted provenance.

    Empty string ⇒ nothing untrusted ⇒ the detector is not run at all. This is
    the fix for the false-positive class described above: describing an attack
    is not an attack.

    Conservative on error: returns the whole prompt, i.e. behaves exactly as the
    unscoped hook did. A bug here must never silently disable detection.
    """
    try:
        low = prompt.lower()
        if any(m in low for m in UNTRUSTED_MARKERS):
            return prompt  # carries a harness untrusted-provenance wrapper
        # Long fenced/quoted blocks are pasted foreign content in practice;
        # short ones are you quoting a phrase mid-sentence.
        blocks = re.findall(r"```.*?```|^>.*(?:\n>.*)*", prompt, re.DOTALL | re.MULTILINE)
        big = [b for b in blocks if len(b) >= PASTED_BLOCK_CHARS]
        return "\n".join(big)
    except Exception:
        return prompt


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
    # Scan ONLY untrusted-provenance spans — see the re-scoping note above.
    target = untrusted_spans(prompt)
    if not target.strip():
        return 0  # nothing untrusted here; you typing is not a threat
    try:
        result = scan(target)
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
