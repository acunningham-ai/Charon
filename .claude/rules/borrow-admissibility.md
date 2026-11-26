---
name: Borrow admissibility
description: The standing rules a third-party mechanism must clear before it is borrowed, ported or adopted. A mechanism can be real, novel and still inadmissible. Fires when evaluating a third-party repo, framework, plugin or MCP server for adoption or borrowing.
keywords:
  - "borrow"
  - "borrowing"
  - "borrow-scan"
  - "adopt"
  - "adoption"
  - "vendor"
  - "vendoring"
  - "third-party repo"
  - "third party repo"
  - "framework"
  - "install this"
  - "should we use"
---

# Borrow admissibility

A mechanism found in someone else's repo can be genuinely good, genuinely new to
this harness, **and still inadmissible**. Check every candidate against the rules
below *before* it reaches a shortlist. `/borrow-scan` runs this as its Stage 3;
apply it by hand whenever a third-party repo, framework, plugin or MCP server is
being weighed.

Where a mechanism collides with a rule, name the rule and say whether a
**compliant variant** exists. Often one does: take the idea, drop the part that
breaks the rule. If the user's own stated intent conflicts with one of these
rules, **surface both and let the user decide** — never quietly pick.

## The rules

1. **Borrow patterns, don't install frameworks.** The default verdict on any
   third-party agent framework is *"don't install it — identify the 2–4 patterns
   worth having and re-author them here"*. A parallel framework is double the
   maintenance and double the attack surface, and a young category's "zero CVEs"
   is silence, not safety. If a pattern only works inside the framework's own
   runtime, drop it rather than install the framework for one feature. (Tools
   whose value *is* the binary — an EDR agent, say — are the exception; agent
   frameworks are not.)

2. **No `curl | bash`, no hostile delivery.** An install path you can't read
   before it runs is unverifiable supply chain. Reject outright any setup that
   rewrites user config (shell rc, services, registry, `~/.claude/settings.json`),
   demands cloud keys it doesn't need, phones home, or asks for broad OS
   permissions. Clean licence + hostile delivery = reject.

3. **Licence by install-time closure, not the badge.** Read the dependency
   manifests (`requirements*.txt`, `pyproject.toml`, `package.json`, `setup.py`)
   and follow what a plain install actually pulls in. A permissively licensed
   package can hard-depend on a copyleft one. Distinguish what the code does at
   runtime from what lands on disk at install. Flag bundled binaries and any
   package with no declared licence.

4. **Clean-room, never copy.** A borrowed mechanism is re-authored from a spec in
   this harness's conventions, then checked with `scripts/verify_no_copy.py`.
   Licensed data corpora are the exception: copy faithfully, with a `NOTICE`.
   Full method: `clean-room-port.md`.

5. **Prefer in-house to a new dependency.** If the mechanism could be written
   natively against the files it operates on — a parser, a converter, a matcher,
   a heuristic — write it, even at 2–3× the lines of a wrapper. A new dependency
   is a future supply-chain incident; it has to earn its place, and ships as an
   opt-in `requirements-*.txt`, never as a core requirement. Full runtimes,
   cryptography and platform SDKs are legitimate dependency cases.

6. **Local-first, nothing phones home.** Every install is one user on one
   machine. A mechanism that needs a shared server, sends telemetry, or reaches
   the network without the user asking is inadmissible as built.

7. **Don't fragment memory.** The vault is the memory. A mechanism that keeps
   its own canonical store of facts (a separate database, index or vector store
   holding what would otherwise be a note) splits the truth in two. An index
   *over* the vault that holds no canonical state is fine.

8. **Doesn't duplicate what you already have, and the ceremony is worth it.**
   If Claude Code or this harness already does the job, the borrow adds nothing.
   Weigh setup, maintenance and mental overhead against time saved × how often
   it's used; a tool that costs more to keep than it saves is a no. A mechanism
   that needs a persistent background daemon has to justify that cost.

9. **Security posture beats features.** Anything that listens, watches or acts
   continuously without the user present (an always-on microphone, a screen
   watcher, an unattended agent loop) is inadmissible however well built,
   unless the user has explicitly decided to accept that posture. Unattended
   automation also needs the injection and poisoning protections in
   `07-References/security-baselines.md`.

10. **Model stack — Claude-only by default.** By default the harness uses no other
    LLM, *including embedding models*. This is a default, not a law: if the user
    has opted into a mixed stack, record that decision and respect it. Absent that
    decision, a mechanism that needs another model is taken only as a compliant
    variant (e.g. keep a keyword/BM25 arm, drop the embeddings arm).

## See also

- `.claude/commands/borrow-scan.md` — the pipeline this rule is Stage 3 of
- `.claude/rules/clean-room-port.md` — how a taken mechanism is re-authored
- `/cerberus-vet` — the risk gate that runs before any of this
