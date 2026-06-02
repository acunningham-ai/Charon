#!/usr/bin/env python3
"""
PostToolUse hook: voice-anchor verbatim-lift detector for voice-content drafts.

When Claude writes or edits a draft under `08-Projects/LinkedIn-Agent/drafts/`,
scans the new content for verbatim N-word runs that appear in any
voice-example file. The `voice-content.md` rule says source content is
PREMISE not COPY — this hook catches lifts deterministically so the bad
attempt never reaches the user.

Talk anchors (frontmatter `type: speaker-talk` or `type: talk`) are flagged
as a HARD violation. Other voice-examples (the user's prior published posts)
are flagged as soft violations — don't republish your own past prose.

The path convention (`08-Projects/LinkedIn-Agent/drafts/`,
`voice-examples/` sibling) matches `draft-linkedin.md`. If your voice-anchor
directory lives elsewhere, adjust DRAFTS_GLOB and VOICE_EXAMPLES_DIRNAME.

Exit codes:
  0 = clean (no verbatim lifts) or non-applicable
  2 = block; stderr is fed back to Claude with source file + lifted phrase

Failures during the hook itself never block — exits 0 silently.
"""
import json
import re
import sys
from pathlib import Path

DRAFTS_GLOB = "**/08-Projects/LinkedIn-Agent/drafts/**/*.md"
VOICE_EXAMPLES_DIRNAME = "voice-examples"
WINDOW = 10           # word-count threshold for "verbatim lift"
MAX_REPORT = 5        # cap reported lifts per call to keep stderr readable

try:
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


SMART_TO_PLAIN = str.maketrans({
    "‘": "'", "’": "'", "“": '"', "”": '"',
    "–": "-", "—": "-", "…": "...",
})


def normalize(s: str) -> str:
    s = s.lower().translate(SMART_TO_PLAIN)
    return re.sub(r"\s+", " ", s).strip()


def strip_frontmatter(text: str) -> str:
    m = re.match(r"^---\r?\n.*?\r?\n---\r?\n", text, re.S)
    return text[m.end():] if m else text


def strip_code_fences(text: str) -> str:
    return re.sub(r"```.*?```", " ", text, flags=re.S)


def tokenize(text: str) -> list:
    return re.findall(r"\S+", normalize(text))


def windows(tokens: list, n: int):
    for i in range(len(tokens) - n + 1):
        yield " ".join(tokens[i:i + n])


def glob_to_regex(glob: str) -> str:
    g = glob.replace("\\", "/")
    out = []
    i = 0
    while i < len(g):
        if g[i:i + 3] == "**/":
            out.append("(?:.*/)?"); i += 3
        elif g[i:i + 3] == "/**":
            out.append("(?:/.*)?"); i += 3
        elif g[i:i + 2] == "**":
            out.append(".*"); i += 2
        elif g[i] == "*":
            out.append("[^/]*"); i += 1
        elif g[i] == "?":
            out.append("[^/]"); i += 1
        else:
            out.append(re.escape(g[i])); i += 1
    return "^" + "".join(out) + "$"


def matches_glob(glob: str, path: str) -> bool:
    return re.fullmatch(glob_to_regex(glob), path.replace("\\", "/")) is not None


def is_talk_anchor(path: Path) -> bool:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except Exception:
        return False
    m = re.match(r"^---\r?\n(.*?)\r?\n---", text, re.S)
    if not m:
        return False
    fm = m.group(1)
    return bool(re.search(r"^\s*type\s*:\s*(speaker-talk|talk)\b", fm, re.M))


def build_phrase_index(voice_dir: Path) -> dict:
    """Map normalized N-word phrase -> (filename, is_talk_anchor)."""
    index: dict = {}
    if not voice_dir.is_dir():
        return index
    for f in sorted(voice_dir.glob("*.md")):
        if f.name.lower() == "readme.md":
            continue
        try:
            text = f.read_text(encoding="utf-8-sig")
        except Exception:
            continue
        is_talk = is_talk_anchor(f)
        body = strip_code_fences(strip_frontmatter(text))
        for w in windows(tokenize(body), WINDOW):
            if w not in index:
                index[w] = (f.name, is_talk)
    return index


def find_voice_dir(draft_path_str: str) -> Path | None:
    """Locate voice-examples by walking up from the draft path."""
    norm = draft_path_str.replace("\\", "/")
    idx = norm.rfind("/drafts/")
    if idx == -1:
        return None
    base = norm[:idx]
    return Path(base) / VOICE_EXAMPLES_DIRNAME


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except Exception:
        return 0
    tool_input = data.get("tool_input", {}) or {}
    file_path = tool_input.get("file_path", "")
    if not file_path or not matches_glob(DRAFTS_GLOB, file_path):
        return 0

    draft_path = Path(file_path)
    if not draft_path.exists():
        return 0
    try:
        draft_text = draft_path.read_text(encoding="utf-8-sig")
    except Exception:
        return 0

    voice_dir = find_voice_dir(file_path)
    if voice_dir is None:
        return 0
    index = build_phrase_index(voice_dir)
    if not index:
        return 0

    draft_body = strip_code_fences(strip_frontmatter(draft_text))
    draft_tokens = tokenize(draft_body)

    seen: set = set()
    lifts: list = []
    for w in windows(draft_tokens, WINDOW):
        if w in index:
            src, is_talk = index[w]
            key = (src, w)
            if key in seen:
                continue
            seen.add(key)
            lifts.append((src, w, is_talk))
            if len(lifts) >= MAX_REPORT:
                break

    if not lifts:
        return 0

    talk_lifts = [x for x in lifts if x[2]]
    soft_lifts = [x for x in lifts if not x[2]]

    sys.stderr.write(
        "VOICE-ANCHOR HOOK TRIGGERED - verbatim lift detected\n"
        f"  Draft: {draft_path.name}\n"
        f"  Threshold: {WINDOW}+ word run, normalized comparison\n\n"
    )
    if talk_lifts:
        sys.stderr.write(
            "TALK-ANCHOR lifts (HARD violation - per the voice-content "
            "rule, source content is PREMISE not COPY):\n"
        )
        for src, w, _ in talk_lifts:
            preview = w if len(w) <= 140 else w[:140] + "..."
            sys.stderr.write(f"  - From `{src}`: \"{preview}\"\n")
        sys.stderr.write("\n")
    if soft_lifts:
        sys.stderr.write(
            "PUBLISHED-POST lifts (republishing your own past prose - "
            "voice-examples are style models, not source text):\n"
        )
        for src, w, _ in soft_lifts:
            preview = w if len(w) <= 140 else w[:140] + "..."
            sys.stderr.write(f"  - From `{src}`: \"{preview}\"\n")
        sys.stderr.write("\n")

    sys.stderr.write(
        "Rewrite from PRINCIPLE not COPY. Keep the underlying thinking "
        "but use fresh wording. Do not signal callbacks to talks the "
        "audience hasn't seen.\n"
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
