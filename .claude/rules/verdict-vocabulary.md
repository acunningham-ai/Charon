---
paths:
  - "scripts/hooks/**"
keywords:
  - "verdict"
  - "PreToolUse"
  - "PostToolUse"
  - "hook authoring"
  - "monitor mode"
  - "HARNESS_MODE"
  - "allow deny ask observe"
  - "shadow rule"
---

# Verdict vocabulary for harness hooks

Auto-loaded when authoring or editing files under `scripts/hooks/**` (path trigger) or when the prompt mentions verdict / PreToolUse / PostToolUse / hook authoring.

Source: Prempti `allow/deny/ask` schema + harness-native `observe` mode.

## The four verdicts

| Verdict | Hook exit code | Semantics | Use when |
|---|---|---|---|
| **allow** | 0 | Proceed silently. No stderr. | Routine in-scope action. |
| **deny** | 2 | Block. stderr explains the rule + reason. | Action should never happen — out-of-scope, protected zone, sensitive path. |
| **ask** | 2 | Block. stderr explains AND invites the user to confirm and retry. | Action is plausibly intentional but warrants explicit confirmation. Distinguishes "you cannot do this" from "you can do this if confirmed". |
| **observe** | 0 | Allow + log. | Shadow-testing a new rule for its first fortnight, OR informational signals where blocking would be wrong. |

**Note on `ask`:** Claude Code's hook protocol has no native "ask" exit code. Semantically, `ask` is a `deny` whose stderr message tells Claude *not to route around it* but to surface the reason to the user and request confirmation. The verdict layer makes this distinction structured (audit log shows `declared: ask` vs `declared: deny`) even though the immediate effect is the same exit code.

## Monitor mode — `HARNESS_MODE=monitor`

Set the env var in the wrapper script to downgrade every `ask` and `deny` to `observe`. Use cases:

- **Shadow-test a new rule** for a fortnight before promoting. New rule ships emitting `ask` or `deny`; running in monitor mode means it logs but doesn't block. After a fortnight of audit-log review for false positives, promote by removing the monitor-mode env var for that automation.
- **Debug a hook misbehaving** without losing other hook protection.
- **Validate an agentic routine** in shadow before its signals become enforcing.

## Module surface — `scripts/hooks/_verdict.py`

```python
from _verdict import emit_verdict, verdict_to_exit_code, write_ask_stderr

effective = emit_verdict(
    hook="my-hook-name",
    rule="rule-id-within-hook",
    verdict="ask",                                    # declared verdict
    reason="<human-readable why>",
    context={"target": path, "matched_glob": glob},  # arbitrary structured context
)

if effective in ("ask", "deny"):
    if effective == "ask":
        write_ask_stderr(rule="rule-id", reason="...", retry_hint="...")
    else:
        sys.stderr.write("BLOCKED: ...\n")

return verdict_to_exit_code(effective)
```

## Conventions for hook authors

1. **Emit a verdict on every non-trivial decision.** Skip for "not our gate" early returns (interactive session, no target path) — those would be log noise.
2. **`rule` is a stable identifier** for the specific check that fired. E.g. `allowlist-match`, `protected-zone`, `published-post-frontmatter`. Stable so the audit log can be grouped/filtered.
3. **`reason` is human-readable**, names the rule context. Goes into the audit log AND can be used in stderr.
4. **`context` is structured.** Used by any downstream audit-log-reading routines to derive notifications. Include the target path, matched pattern, tool name, automation name. **Never put secrets, tokens, credentials, or sensitive captured-content snippets in `context`** — the audit log lives in `<project>/state/verdict/` and may be cloud-synced depending on your setup. If a value is in a secrets store, env vars holding credentials, or anything you'd refuse to paste in chat, redact before passing. Caller is responsible.
5. **Fail-silent on `_verdict.py` errors.** Hooks must keep working if the verdict module is missing or broken. Use the import-guarded pattern from `validate-write-path.py`:
   ```python
   try:
       from _verdict import emit_verdict
   except Exception:
       def emit_verdict(*args, **kwargs):
           return kwargs.get("verdict", "allow")
   ```
6. **Don't emit `observe` for happy-path allows in production hooks.** Reserve `observe` for either (a) new-rule shadow phase or (b) signals where the verdict layer is purely diagnostic.

## Audit log

Path: `<project>/state/verdict/{YYYY-MM-DD}.jsonl`. Daily rotation matches `_telemetry.py`. Append-only. Each line:

```json
{
  "ts": "2026-06-01T05:55:00+00:00",
  "hook": "validate-write-path",
  "rule": "allowlist-match",
  "declared": "allow",
  "effective": "allow",
  "mode": "production",
  "reason": "target matches glob '**/07-References/weekly-digest/*.md'",
  "session_id": "...",
  "context": { ... }
}
```

`declared` and `effective` differ only when `mode == monitor` AND `declared in (ask, deny)` — then `effective == observe`. This makes monitor-mode downgrades searchable.

## When NOT to use the verdict layer

- **Trivially short hooks** with only one allow/deny decision that's already obvious from stderr — verdict logging adds noise without insight.
- **PostToolUse hooks that observe outcomes** — those are observation hooks, not decision hooks. Use `_telemetry.py` instead.
- **Hooks that fail-silent on every error** — adding verdict emission to a hook that should never block means you're using the wrong tool.

## Co-change couplings

- **New verdict added to the vocabulary** → update this rule + `_verdict.py` `ALL_VERDICTS` tuple + `verdict_to_exit_code` mapping
- **New hook author adopts the layer** → cross-check the conventions list above
- **`HARNESS_MODE` env var added to a new wrapper script** → document which automations are in monitor mode in your project notes so review skills know what to surface

## See also

- `_verdict.py` — the implementation module
- `_jsonl_append.py` — concurrent-safe append helper used by the audit-log writer
- `validate-write-path.py` — first hook to adopt the verdict layer
- `_telemetry.py` — adjacent helper for observation-only logging (not decision logging)
- `harness-watch-review.md` skill — promotion-decision skill for shadow-window rules
- `skill-authoring.md` — adjacent path-rule for hook/skill authors
