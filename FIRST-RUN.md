# First-run setup

The first-run wizard captures the user-specific layer that the harness can't provide — your voice, your org structure, your framework, your tool preferences. Without these, the rules can't tailor their output to you; with them, the rules become *yours*.

**Two paths.** A **Quick** path gets you productive in ~2 minutes with sensible defaults for everything that isn't load-bearing on day one; refine any phase later. A **Full** path walks every phase up front — ~20 minutes. The wizard offers you the choice the first time you run it. Both lead to the same harness; the difference is when you answer the questions.

## Quick path — 4–6 questions, ~2 minutes

```bash
python scripts/first-run.py --quick      # or pick option 1 at the interactive prompt
```

Quick mode asks **four** questions always — name, role / position, organisation, and whether to set up email capture — plus **two more** (M365 tenant ID + client ID) if you enable capture. It accepts sensible defaults for everything else:

- **Vault path** defaults to the current working directory.
- **Secrets directory** defaults to `~/.secrets` (created with restricted permissions).
- **Anthropic API key setup** deferred — the save-on-mention hook silently no-ops until you configure it later. Rules + memory still work.
- **Voice / org structure / framework** skipped entirely — the rules that depend on them fall back to their universal defaults (generic audience, no per-unit context, no enforced framework). (Email capture is the one integration Quick mode does offer, since it's load-bearing for the capture pipeline on day one.)

After Quick mode completes, you can refine any phase any time:

```bash
python scripts/first-run.py --phase identity_paths   # vault path, secrets, Anthropic key
python scripts/first-run.py --phase org_framework    # org-units, audience tiers, framework
python scripts/first-run.py --phase voice            # your writing voice (6 short questions)
python scripts/first-run.py --phase workflow         # standing rules + optional integrations
python scripts/first-run.py --phase engines          # research beats / newsletter senders / forums
```

This is the path designed for **non-technical users** and anyone who wants to see the harness work *before* committing to a long setup. Tester feedback (May 2026) showed the full multi-phase wizard felt clunky for users without prior tech literacy — Quick mode is the answer to that feedback.

## Full path — 39 questions, ~20 minutes

```bash
python scripts/first-run.py --full       # or pick option 2 at the interactive prompt
```

Walks every phase up front. Recommended when you already know how you want the harness configured (returning users, fresh laptop with established preferences, etc.).

## Running the wizard (all options)

```bash
python scripts/first-run.py                 # interactive — asks Quick vs Full at the top
python scripts/first-run.py --quick         # express path (4–6 questions)
python scripts/first-run.py --full          # full path (39 questions across 5 phases)
python scripts/first-run.py --phase voice   # re-do a single phase
python scripts/first-run.py --phase engines # seed research beats / newsletter senders / forums
python scripts/first-run.py --dry-run       # show planned writes; don't touch the filesystem
python scripts/first-run.py --logo full     # force full ASCII banner (needs ~200-col terminal)
python scripts/first-run.py --no-logo       # skip banner entirely
```

Questions live in `scripts/first-run-questions.yaml`. Edit that file to add, reword, or reorder questions — the wizard reads it on every run. The schema is documented at the top of the YAML.

State persists at `~/.charon-first-run-state.json` while a run is in progress. Press **Ctrl+C** any time — your answers are saved and the next run resumes where you stopped. On successful completion the state file is removed.

Re-running after completion: every previously-answered question offers **`[k]eep` / `[u]pdate` / `[w]ipe`**.

## Why this exists

The harness ships universal patterns (board-reporting structure, security baseline framework, audience-tailoring discipline). It deliberately does NOT ship:

- Your name, position, or voice profile
- Your org chart, audience tiers, or named personnel
- Your security framework specifics (control list, domain count, calibrations)
- Your dashboard / source-of-truth tool
- Vendor exceptions (the one or two tools you DO standardise on)

These are user-supplied during first-run. The wizard walks you through capturing them.

## What the wizard asks

### 1. Identity

- **Your name** — anchors voice + identity in memory.
- **Your position / role** — drives audience-tailoring (a CISO, a Head of Engineering, a Strategy lead all need different framings).
- **Your org** — short description, used in stakeholder-facing docs.

**Populates:** `<memory-root>/user_role.md`

### 2. Vault path

- **Where does your second-brain live?** — defaults to the repo clone location, but you can point elsewhere.

**Populates:** `HARNESS_VAULT_ROOT` env var + `CLAUDE.md` paths section

### 3. Secrets directory

- **Where do credentials live?** — defaults to `~/.secrets/`. Should be outside any cloud-synced folder.

**Populates:** `HARNESS_SECRETS_DIR` env var

### 4. Org chart

- **Paste or upload your org chart** — positions, audience tiers, reporting lines.
- For each audience tier (e.g. "Group Director", "Board", "Customer", "External Auditor"), capture:
  - Their lens (cross-org consistency? portfolio variance? legal? cost?)
  - What to emphasise when writing to them
  - What to drop (e.g. internal operating-model orientation for insiders who already live it)

**Populates:** `<memory-root>/reference_audience_tiers.md`, `<memory-root>/reference_key_people.md` skeleton

### 5. Org-units (the "BU" abstraction)

The harness uses "org-unit" as a structural primitive. For you it might mean:

- Business units (sub-companies, acquired ISVs, divisions)
- Departments (HR, Engineering, Sales)
- Customer accounts
- Portfolio companies
- Anything structurally meaningful for your work

- **What's your equivalent?**
- **List or paste your org-units** — names, portfolio/sub-group rollup if applicable.

**Populates:** `<memory-root>/reference_org_units.md`

### 6. Framework + critical controls

If you do periodic reporting against a maturity framework:

- **Your framework name** (e.g. "ACME Cyber Maturity Framework v2", "Adapted NIST CSF 2.0")
- **Your domains** (the categories the framework measures — e.g. IAM, Endpoint, Network, etc.)
- **Your critical-control list** — the small set you treat as cross-org-unit baseline (typically 4-6 controls: MFA, backup, EDR, patching, EOL, etc., calibrated to your context)

**Populates:** `<memory-root>/reference_framework.md`, `<memory-root>/reference_critical_controls.md`

### 7. Dashboard / source-of-truth tool

- **Where do your scores / verdicts live?** — GRC platform name, custom dashboard URL, spreadsheet path, whatever.
- **How do you typically paste them?** — table format, exported CSV, snapshot image, etc.

**Populates:** `<memory-root>/feedback_data_accuracy.md` — the rule that says "dashboard is source of truth; never compute"

### 8. Tool exceptions

The harness defaults to "X or similar tool" framing on every vendor recommendation. If your org has standardised on a specific vendor (e.g. an org-wide EDR contract), that's the one exception you can name without "or similar tool".

- **Any named exceptions?** — vendor name + capability covered + why it's standardised
- If none, leave empty.

**Populates:** `<memory-root>/feedback_no_tool_mandate.md` — exception list

### 9. Voice profile

A guided exercise to capture your writing style. The harness asks:

- **Emphasis** — caps for emphasis? italics? em-dashes? parens?
- **Sentence cadence** — uniformly crisp? loose-and-rough? conversational drift?
- **Personality moments** — confessions in parens? wink at the reader? yell words for emphasis?
- **Refrains** — do you use recurring metaphors / refrains across the same piece?
- **Closer style** — reflective? punchy? question? list?
- **What you DON'T want to sound like** — uniformly tight magazine prose? polished aphorisms? brand-voice?

Output: a populated `<memory-root>/user_voice.md` that the `voice-content.md` rule reads on every drafting session.

### 10. Org-specific rules

Anything else you want baked in as a workflow rule:

- "From now on, always X..."
- "Never Y unless Z..."
- "When dealing with W, the right person to escalate to is V..."

Each becomes a `<memory-root>/feedback_*.md` entry indexed in `MEMORY.md`.

### 11. Optional integrations

If you want to wire any of these in:

- **Capture pipeline** — pulls inbox + sent items from your email provider into `00-Inbox/_captured/email/`. The wizard prompts for provider choice (M365 / Gmail / IMAP), per-provider config, and whether to capture sent items. **Read [`EMAIL-PROVIDER-SETUP.md`](EMAIL-PROVIDER-SETUP.md) BEFORE this section** — you need an app registration / OAuth client / app password ready to enter, which can only be created on the provider side.
- **Scheduled tasks** — `linkedin-weekly-drafts.bat` schedule, `scheduled-capture.bat` cadence, `scheduled-audit.py` daily wrapper.
- **MCP servers beyond what ships** — point at additional MCP configs.

**Why sent items?** Inbox-only capture leaves a one-sided view of every conversation. Sent items close the loop: when did you respond, what did you commit to, what threads do you owe a reply on. The `/refresh-todo` and `/triage-inbox` skills surface this. Default is on; you can turn it off if your use case is privacy-constrained.

### 12. Research / writing / forum engines (optional)

Seeds the standing-seat pipeline (`/prometheus`, `/calliope`, `/forum-agenda`) so it isn't empty on day one:

- **Standing research beats** — the themes Prometheus watches (3-6). E.g. "agentic-AI security", "your-sector regulation", "key-vendor platform changes".
- **Newsletter / digest senders** — the email addresses Prometheus reads as its input beat (matched on the `sender:` field). Blank = no email beat.
- **Recurring forums** — `name - cadence - remit` per forum, for the `/forum-agenda` feed.

**Populates:** `00-Inbox/_research/_ledger.md` (beats + sender allowlist) and `<memory-root>/reference_forums.md`. All skippable — add later with `--phase engines`.

## How long does it take?

~20 minutes for the substantive parts (org chart paste, voice exercise, framework specifics). The rest is configuration that takes seconds.

## What if I want to skip something?

Skip-able sections:

- Org chart — falls back to a single "user" audience tier with no per-person lenses
- Framework + critical controls — falls back to "configure later when you have a need"
- Tool exceptions — falls back to "no exceptions" (every vendor mention gets "or similar tool")
- Optional integrations — defer indefinitely

Not skip-able:

- Identity (name + position + org)
- Vault path + secrets directory
- Voice profile (the voice-content rule is non-functional without it)

## How to re-run

You can re-run the wizard at any time — see "Running the wizard" above. The wizard offers `[k]eep / [u]pdate / [w]ipe` for each previously-answered question.

## After first-run

→ [`CONFIGURATION.md`](CONFIGURATION.md) for tuning paths, scheduled tasks, and MCP servers beyond the defaults.
