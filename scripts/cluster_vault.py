"""cluster_vault.py — CLI for running community detection over the vault graph.

Usage::

    python scripts/cluster_vault.py                # detect + persist to .charon/graph-communities.json
    python scripts/cluster_vault.py --stats        # print summary; don't re-detect
    python scripts/cluster_vault.py --resolution 1.5   # smaller communities
    python scripts/cluster_vault.py --resolution 0.7   # larger communities

Requires the optional kuzu + networkx deps (``pip install -r requirements-graph.txt``).
If either is missing or the vault graph file doesn't exist, prints a clear error
and exits non-zero.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Local import — `scripts/lib/communities.py`
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.communities import (  # noqa: E402
    communities_available,
    communities_path,
    community_summary,
    detect_communities,
    read_communities,
    write_communities,
)


def _configure_stdio_for_unicode() -> None:
    if sys.platform.startswith("win"):
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass


def main() -> int:
    _configure_stdio_for_unicode()
    parser = argparse.ArgumentParser(description="Run Louvain community detection over the Charon vault graph")
    parser.add_argument("--stats", action="store_true", help="Print stats from the existing communities file; don't re-detect")
    parser.add_argument("--resolution", type=float, default=1.0,
                        help="Louvain resolution; >1 favours smaller communities, <1 favours larger (default: 1.0)")
    parser.add_argument("--seed", type=int, default=42, help="Random seed for reproducibility (default: 42)")
    args = parser.parse_args()

    if args.stats:
        data = read_communities()
        if not data:
            sys.stderr.write(f"no communities file at {communities_path()}\n")
            return 1
        print(f"Communities file: {communities_path()}")
        print(f"  algorithm:        {data.get('algorithm', 'unknown')}")
        print(f"  nodes:            {data.get('node_count', 0)}")
        print(f"  communities:      {data.get('community_count', 0)}")
        comms = data.get("communities", {})
        sizes = sorted([c["size"] for c in comms.values()], reverse=True)
        if sizes:
            print(f"  largest size:     {sizes[0]}")
            print(f"  smallest size:    {sizes[-1]}")
        print()
        print("Top 5 communities by size:")
        for cid, comm in sorted(comms.items(), key=lambda kv: -kv[1]["size"])[:5]:
            sample_nodes = comm["nodes"][:6]
            tail = f" + {comm['size'] - 6} more" if comm["size"] > 6 else ""
            print(f"  [{cid}] size={comm['size']:>3}  : {', '.join(sample_nodes)}{tail}")
        return 0

    # Detect
    ok, reason = communities_available()
    if not ok:
        sys.stderr.write(f"communities unavailable: {reason}\n")
        return 1

    print(f"Running Louvain over {communities_path().parent / 'knowledge-graph.kuzu'}...")
    communities = detect_communities(seed=args.seed, resolution=args.resolution)
    if not communities:
        print("No nodes in the graph — run `python scripts/extract_entities.py` first.")
        return 1

    path = write_communities(communities)
    summary = community_summary(communities)
    print(f"  detected {summary['community_count']} communities over {summary['node_count']} nodes")
    print(f"  sizes: largest={summary['largest_size']}, median={summary['median_size']}, smallest={summary['smallest_size']}")
    print(f"  wrote {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
