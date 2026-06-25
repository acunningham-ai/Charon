#!/usr/bin/env python3
"""graph_link_backfill.py — materialise derived-graph edges as `## Related`
[[wikilink]] footers in authored notes, so Obsidian's graph view reflects the
real entity web (not just the few links physically authored in prose).

The vault has two graphs: Obsidian renders only [[wikilinks]] in note bodies,
while the rich web lives in the derived knowledge graph (scripts/lib/graph.py,
the .charon/knowledge-graph.json store). This script writes the derived edges
back into the notes as a delimited footer so the two converge.

Read-side : reads the graph (networkx), groups edges by `source_file`.
Write-side: for each in-scope note, inserts/replaces a marker-delimited
            `## Related` block at the end. FOOTER-ONLY — prose is never touched.

Idempotent: re-runs replace the block between the markers; everything else is
left byte-for-byte. A note that no longer has qualifying edges has its stale
block removed.

Default is --dry-run (no writes). Pass --apply to write.

Scope (generic by design — no folder taxonomy assumed):
  - every note that has extracted graph edges, EXCEPT
  - untrusted captured content (frontmatter `trust: untrusted`),
  - templates / dotfile dirs (.obsidian, .charon, .git, node_modules),
  - any CLAUDE.md.

This is the final stage of the graph-build sequence:
  extract_entities.py  ->  cluster_vault.py  ->  vault_graph_html.py  ->  THIS
so a freshly built/refreshed graph leaves the notes link-rich out of the box.
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.graph import graph_path, is_available, load_nx, normalise_name  # noqa: E402
from lib.harness_paths import vault_root  # noqa: E402

START_MARKER = "<!-- graph-backfill:start -->"
END_MARKER = "<!-- graph-backfill:end -->"

DEFAULT_MIN_CONF = 0.8

# Never touch these regardless of where they sit.
EXCLUDE_FILENAMES = {"CLAUDE.md"}
EXCLUDE_DIR_PARTS = {
    "_captured", "templates", "_templates",
    ".obsidian", ".charon", ".git", "node_modules",
}

# Targets that are file artifacts (code/config/path-like), not real entities.
# These get extracted as graph nodes but make meaningless faded Obsidian nodes.
_FILEISH = re.compile(
    r"(/|\.(md|py|json|js|mjs|ts|txt|bat|ps1|sh|ya?ml|html|csv|toml|ini|cfg|lock))$",
    re.I,
)
# Detect `trust: untrusted` in YAML frontmatter (captured, untrusted content).
_UNTRUSTED = re.compile(r"^trust:\s*untrusted\s*$", re.I | re.M)


def is_fileish(display: str) -> bool:
    return bool(_FILEISH.search(display.strip()))


def is_excluded_path(rel_path: str) -> bool:
    """rel_path is POSIX-style, relative to the vault root."""
    parts = rel_path.split("/")
    if Path(rel_path).name in EXCLUDE_FILENAMES:
        return True
    return any(p in EXCLUDE_DIR_PARTS for p in parts)


def is_untrusted(text: str) -> bool:
    """True if the note's frontmatter marks it as untrusted captured content.

    Only inspect a leading frontmatter block so a passing mention of the string
    in prose can't accidentally exclude an authored note."""
    if not text.startswith("---"):
        return False
    end = text.find("\n---", 3)
    front = text[: end if end != -1 else 400]
    return bool(_UNTRUSTED.search(front))


def load_graph_edges():
    """Read all edges from the networkx graph.

    Returns {source_file: {to_norm: {display, rels:set, conf}}}. We follow the
    backfill spec: for a note N, link the `to` endpoints of edges whose
    source_file == N."""
    g = load_nx()
    by_file: dict[str, dict[str, dict]] = defaultdict(dict)
    for _u, v, d in g.edges(data=True):
        src = d.get("source_file", "")
        if not src:
            continue
        try:
            conf = float(d.get("confidence", 1.0) or 1.0)
        except (TypeError, ValueError):
            conf = 1.0
        to_display = g.nodes[v].get("display_name", v)
        slot = by_file[src].setdefault(
            v, {"display": to_display or v, "rels": set(), "conf": conf}
        )
        slot["rels"].add(d.get("relationship") or "MENTIONS")
        slot["conf"] = max(slot["conf"], conf)
    return by_file


def build_block(note_stem_norm: str, targets: dict[str, dict],
                min_conf: float, keep_fileish: bool = False) -> str:
    """Render the marker-delimited footer. Skips self-links, sub-threshold
    edges, and (by default) file-artifact targets that aren't real entities."""
    rows = []
    for to_norm, info in targets.items():
        if info["conf"] < min_conf:
            continue
        if to_norm == note_stem_norm or normalise_name(info["display"]) == note_stem_norm:
            continue
        if not keep_fileish and is_fileish(info["display"]):
            continue
        rels = "/".join(sorted(info["rels"]))
        rows.append((info["display"], f"- [[{info['display']}]] ({rels})"))
    if not rows:
        return ""
    rows.sort(key=lambda r: r[0].lower())
    body = "\n".join(r[1] for r in rows)
    return f"{START_MARKER}\n## Related\n{body}\n{END_MARKER}"


def splice(text: str, block: str) -> str:
    """Insert or replace the backfill block. Returns new text (footer-only)."""
    start = text.find(START_MARKER)
    if start != -1:
        end = text.find(END_MARKER, start)
        if end != -1:
            end += len(END_MARKER)
            before, after = text[:start], text[end:]
            if not block:  # stale block, no links anymore -> remove it
                return before.rstrip() + ("\n" if after.strip() else "") + after.lstrip("\n")
            return before + block + after
    if not block:
        return text  # nothing to add, no existing block
    return text.rstrip("\n") + "\n\n" + block + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--apply", action="store_true", help="write changes (default: dry-run)")
    ap.add_argument("--min-conf", type=float, default=DEFAULT_MIN_CONF)
    ap.add_argument("--keep-fileish", action="store_true",
                    help="keep file-path/extension targets (default: drop them as noise)")
    ap.add_argument("--limit", type=int, default=0, help="cap files processed (0 = no cap)")
    ap.add_argument("--sample", type=int, default=3, help="dry-run: show N rendered blocks")
    args = ap.parse_args()

    ok, reason = is_available()
    if not ok:
        print(f"graph backend unavailable: {reason}", file=sys.stderr)
        return 1
    if not graph_path().exists():
        print(f"no graph at {graph_path()} — run scripts/extract_entities.py first",
              file=sys.stderr)
        return 1

    root = vault_root()
    by_file = load_graph_edges()
    if not by_file:
        print("graph has no edges — nothing to backfill", file=sys.stderr)
        return 1

    # Group source_file keys by resolved physical path and MERGE their link
    # sets. One note can carry several source_file keys — case variants (on a
    # case-insensitive filesystem) and stale paths from a note moving folder.
    # Without this merge the loop writes one file repeatedly and the last
    # (often sparser) key clobbers the richer one.
    groups: dict[str, dict] = {}
    skipped_missing = skipped_excluded = skipped_untrusted = 0
    for src in sorted(by_file):
        if is_excluded_path(src):
            skipped_excluded += 1
            continue
        path = root / src
        if not path.exists():
            skipped_missing += 1
            continue
        gkey = str(path.resolve()).lower()
        grp = groups.setdefault(gkey, {"path": path, "targets": {}})
        for to_norm, info in by_file[src].items():
            slot = grp["targets"].setdefault(
                to_norm, {"display": info["display"], "rels": set(), "conf": 0.0}
            )
            slot["rels"] |= info["rels"]
            slot["conf"] = max(slot["conf"], info["conf"])

    items = list(groups.values())
    if args.limit:
        items = items[: args.limit]

    scanned = changed = links_total = removed = 0
    samples = []

    for grp in items:
        path = grp["path"]
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as e:
            print(f"  ! could not read {path}: {e}", file=sys.stderr)
            continue
        if is_untrusted(text):
            skipped_untrusted += 1
            continue
        scanned += 1
        stem_norm = normalise_name(path.stem)
        block = build_block(stem_norm, grp["targets"], args.min_conf,
                            keep_fileish=args.keep_fileish)
        new_text = splice(text, block)
        if new_text == text:
            continue
        if block:
            links_total += block.count("\n- [[")
            changed += 1
        else:
            removed += 1
        if not args.apply and len(samples) < args.sample and block:
            try:
                rel = str(path.relative_to(root))
            except ValueError:
                rel = path.name
            samples.append((rel, block))
        if args.apply:
            path.write_text(new_text, encoding="utf-8")

    mode = "APPLIED" if args.apply else "DRY-RUN (no files written)"
    print(f"\n=== graph link-backfill — {mode} ===")
    print(f"min confidence   : {args.min_conf}")
    print(f"unique notes     : {len(items)}")
    print(f"notes written    : {scanned}  (missing: {skipped_missing}, "
          f"excluded: {skipped_excluded}, untrusted: {skipped_untrusted})")
    print(f"notes changed    : {changed}")
    print(f"stale blocks rm  : {removed}")
    print(f"links written    : {links_total}")
    if samples:
        print("\n--- sample blocks ---")
        for rel, block in samples:
            print(f"\n# {rel}\n{block}")
    if not args.apply:
        print("\nRe-run with --apply to write.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
