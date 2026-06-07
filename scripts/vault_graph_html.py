"""vault_graph_html.py — interactive HTML graph viewer over the vault graph.

Reads the kuzu vault graph + the optional ``graph-communities.json``
written by ``scripts/cluster_vault.py``, emits a single self-contained
``graph.html`` you can open in any browser. Nodes are coloured by
community, sized by degree centrality, filterable by entity type,
searchable by name. Clicking a node opens a side panel with its
connections + provenance.

Why "borrow from graphify": graphify ships an interactive HTML viewer
out of the box and it's the single biggest UX win in that tool. The
visualisation surfaces structural patterns that linear text queries
miss — clusters, hubs, cross-domain bridges. Charon's existing graph
is queryable via MCP but not browsable. This chunk fixes that.

Output: ``<vault>/.charon/graph.html`` (default) — open in any browser.

Architecture:
- One ``.html`` file. No companion JS / CSS / JSON files.
- Graph data embedded inline as JSON in a ``<script type="application/json">`` tag.
- Vis-network loaded from CDN (~150KB at view time). Requires internet on first open.
  Offline alternative: vendor vis-network locally — documented as future work.
- Pure-Python HTML generation — no Jinja, no templating dep.
"""

from __future__ import annotations

import argparse
import html as _html
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.communities import (  # noqa: E402
    communities_path,
    networkx_is_available,
    read_communities,
)
from lib.graph import graph_path, is_available as kuzu_is_available  # noqa: E402
from lib.harness_paths import vault_root  # noqa: E402


HTML_REL_PATH = ".charon/graph.html"


# ---------- Public API ----------

def html_output_path() -> Path:
    return vault_root() / HTML_REL_PATH


def generate_html_from_data(
    nodes: List[dict],
    edges: List[dict],
    node_to_community: Optional[Dict[str, int]] = None,
    title: str = "Charon vault graph",
) -> str:
    """Pure function: nodes + edges + optional community map → self-contained HTML string.

    Node dict shape (required):
        {"id": str, "label": str, "entity_type": str}
    Edge dict shape:
        {"from": str, "to": str, "label": str (optional)}
    """
    if node_to_community is None:
        node_to_community = {}

    palette = _build_palette(node_to_community)

    vis_nodes: List[dict] = []
    for n in nodes:
        cid = node_to_community.get(n["id"])
        color = palette.get(cid, "#7f8c8d")  # grey fallback for un-clustered
        vis_nodes.append({
            "id": n["id"],
            "label": n.get("label", n["id"]),
            "color": color,
            "title": _node_tooltip(n, cid),
            "group": str(cid) if cid is not None else "ungrouped",
            "entityType": n.get("entity_type", "unknown"),
        })

    vis_edges: List[dict] = []
    for e in edges:
        vis_edges.append({
            "from": e["from"],
            "to": e["to"],
            "label": e.get("label", ""),
            "arrows": "to",
        })

    payload = {
        "title": title,
        "nodes": vis_nodes,
        "edges": vis_edges,
        "communityCount": len(set(node_to_community.values())) if node_to_community else 0,
        "palette": palette,
    }

    return _html_template(payload)


def generate_html_from_kuzu(output_path: Optional[Path] = None) -> Tuple[bool, str]:
    """Read kuzu graph + communities, emit HTML. Returns (ok, message)."""
    if output_path is None:
        output_path = html_output_path()

    ok, reason = kuzu_is_available()
    if not ok:
        return False, reason
    if not graph_path().exists():
        return False, f"vault graph not found at {graph_path()} — run `python scripts/extract_entities.py` first"

    nodes, edges = _load_kuzu_graph()
    if not nodes:
        return False, "vault graph has no entities — nothing to render"

    community_data = read_communities()
    node_to_community = (community_data or {}).get("node_to_community", {})

    html_text = generate_html_from_data(nodes, edges, node_to_community)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html_text, encoding="utf-8")
    return True, f"wrote {output_path} ({len(nodes)} nodes, {len(edges)} edges, {len(set(node_to_community.values()))} communities)"


# ---------- Kuzu → in-memory ----------

def _load_kuzu_graph() -> Tuple[List[dict], List[dict]]:
    import kuzu
    db = kuzu.Database(str(graph_path()))
    conn = kuzu.Connection(db)

    nodes: List[dict] = []
    res = conn.execute("MATCH (e:Entity) RETURN e.name, e.entity_type, e.display_name")
    while res.has_next():
        row = res.get_next()
        nodes.append({
            "id": row[0],
            "label": row[2] or row[0],
            "entity_type": row[1],
        })

    edges: List[dict] = []
    res = conn.execute(
        "MATCH (a:Entity)-[r:Mentions]->(b:Entity) RETURN a.name, b.name, r.relationship"
    )
    while res.has_next():
        row = res.get_next()
        edges.append({"from": row[0], "to": row[1], "label": row[2] or ""})

    return nodes, edges


# ---------- Helpers ----------

# Community colour palette. Stable across runs — seeded by community index.
_PALETTE = [
    "#e74c3c", "#3498db", "#2ecc71", "#9b59b6", "#f39c12",
    "#1abc9c", "#e67e22", "#34495e", "#d35400", "#16a085",
    "#8e44ad", "#27ae60", "#c0392b", "#2980b9", "#f1c40f",
]


def _build_palette(node_to_community: Dict[str, int]) -> Dict[int, str]:
    if not node_to_community:
        return {}
    unique_cids = sorted(set(node_to_community.values()))
    return {cid: _PALETTE[i % len(_PALETTE)] for i, cid in enumerate(unique_cids)}


def _node_tooltip(node: dict, community_id: Optional[int]) -> str:
    """Vis-network supports HTML in tooltips. Build a small one per node."""
    parts = [
        f"<b>{_html.escape(node.get('label', node['id']))}</b>",
        f"type: {_html.escape(node.get('entity_type', 'unknown'))}",
    ]
    if community_id is not None:
        parts.append(f"community: {community_id}")
    return "<br>".join(parts)


# ---------- HTML template ----------

def _html_template(payload: dict) -> str:
    """Generate the full HTML document around the payload JSON."""
    title = _html.escape(payload["title"])
    payload_json = json.dumps(payload)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<script src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
<style>
  body {{ margin: 0; font-family: system-ui, sans-serif; color: #2c3e50; background: #fafafa; }}
  header {{ padding: 12px 20px; background: #2c3e50; color: white; display: flex; align-items: center; gap: 18px; }}
  header h1 {{ font-size: 16px; margin: 0; font-weight: 600; }}
  header .stats {{ font-size: 12px; opacity: 0.85; }}
  #controls {{ padding: 8px 20px; background: #ecf0f1; display: flex; gap: 12px; align-items: center; flex-wrap: wrap; font-size: 13px; }}
  #controls label {{ display: flex; align-items: center; gap: 6px; }}
  #controls input[type="search"] {{ padding: 4px 8px; border: 1px solid #bdc3c7; border-radius: 3px; font: inherit; }}
  #controls select {{ padding: 4px 8px; border: 1px solid #bdc3c7; border-radius: 3px; font: inherit; background: white; }}
  #layout {{ display: flex; height: calc(100vh - 100px); }}
  #graph {{ flex: 1; background: white; border-right: 1px solid #ecf0f1; }}
  #side {{ width: 320px; padding: 16px 20px; overflow-y: auto; }}
  #side h3 {{ font-size: 14px; margin: 0 0 8px; }}
  #side .empty {{ color: #95a5a6; font-style: italic; font-size: 13px; }}
  #side dt {{ font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; color: #7f8c8d; margin-top: 10px; }}
  #side dd {{ margin: 2px 0 0; font-size: 13px; }}
  #side ul {{ padding-left: 16px; margin: 6px 0; font-size: 13px; }}
  #side li {{ margin-bottom: 2px; }}
  .swatch {{ display: inline-block; width: 12px; height: 12px; border-radius: 50%; vertical-align: middle; margin-right: 6px; }}
</style>
</head>
<body>
<header>
  <h1>{title}</h1>
  <span class="stats" id="stats"></span>
</header>
<div id="controls">
  <label>Search: <input type="search" id="search" placeholder="Type a name…" autocomplete="off"></label>
  <label>Entity type:
    <select id="type-filter"><option value="">All</option></select>
  </label>
  <label>Community:
    <select id="community-filter"><option value="">All</option></select>
  </label>
  <label><input type="checkbox" id="physics-toggle" checked> Physics</label>
  <span style="margin-left:auto; color:#95a5a6; font-size:12px">Click a node for details</span>
</div>
<div id="layout">
  <div id="graph"></div>
  <aside id="side"><p class="empty">Click a node to inspect its connections.</p></aside>
</div>

<script type="application/json" id="graph-data">{payload_json}</script>
<script>
(function() {{
  const data = JSON.parse(document.getElementById('graph-data').textContent);
  const nodes = new vis.DataSet(data.nodes);
  const edges = new vis.DataSet(data.edges);

  // Stats
  document.getElementById('stats').textContent =
    `${{data.nodes.length}} nodes · ${{data.edges.length}} edges · ${{data.communityCount}} communities`;

  // Populate filter dropdowns
  const typeFilter = document.getElementById('type-filter');
  const types = new Set(data.nodes.map(n => n.entityType));
  Array.from(types).sort().forEach(t => {{
    const opt = document.createElement('option');
    opt.value = t; opt.textContent = t;
    typeFilter.appendChild(opt);
  }});
  const communityFilter = document.getElementById('community-filter');
  const communities = new Set(data.nodes.map(n => n.group).filter(g => g !== 'ungrouped'));
  Array.from(communities).sort((a, b) => Number(a) - Number(b)).forEach(c => {{
    const opt = document.createElement('option');
    opt.value = c; opt.textContent = 'Community ' + c;
    opt.style.backgroundColor = data.palette[c] || '#7f8c8d';
    communityFilter.appendChild(opt);
  }});

  // Network instance
  const container = document.getElementById('graph');
  const network = new vis.Network(container, {{ nodes, edges }}, {{
    nodes: {{ shape: 'dot', size: 14, font: {{ size: 13 }} }},
    edges: {{ width: 1, color: {{ color: '#bdc3c7', opacity: 0.5 }}, smooth: false }},
    interaction: {{ hover: true, tooltipDelay: 200, multiselect: false }},
    physics: {{ stabilization: {{ iterations: 200 }}, barnesHut: {{ gravitationalConstant: -1500 }} }},
  }});

  // Filter logic
  function applyFilters() {{
    const search = document.getElementById('search').value.toLowerCase().trim();
    const type = typeFilter.value;
    const community = communityFilter.value;
    nodes.forEach(n => {{
      const matchSearch = !search || n.label.toLowerCase().includes(search) || n.id.toLowerCase().includes(search);
      const matchType = !type || n.entityType === type;
      const matchCommunity = !community || n.group === community;
      nodes.update({{ id: n.id, hidden: !(matchSearch && matchType && matchCommunity) }});
    }});
  }}
  document.getElementById('search').addEventListener('input', applyFilters);
  typeFilter.addEventListener('change', applyFilters);
  communityFilter.addEventListener('change', applyFilters);

  // Physics toggle
  document.getElementById('physics-toggle').addEventListener('change', e => {{
    network.setOptions({{ physics: {{ enabled: e.target.checked }} }});
  }});

  // Side panel on click
  network.on('selectNode', params => {{
    const id = params.nodes[0];
    const node = nodes.get(id);
    if (!node) return;
    const connected = network.getConnectedNodes(id).map(nid => nodes.get(nid)).filter(Boolean);
    const side = document.getElementById('side');
    side.innerHTML = `
      <h3><span class="swatch" style="background:${{node.color}}"></span>${{node.label}}</h3>
      <dl>
        <dt>Entity type</dt><dd>${{node.entityType}}</dd>
        <dt>Community</dt><dd>${{node.group}}</dd>
        <dt>Connections (${{connected.length}})</dt>
        <dd><ul>${{connected.map(c => `<li><a href="#" data-target="${{c.id}}">${{c.label}}</a> <span style="color:#95a5a6">(${{c.entityType}})</span></li>`).join('')}}</ul></dd>
      </dl>`;
    side.querySelectorAll('a[data-target]').forEach(a => {{
      a.addEventListener('click', ev => {{
        ev.preventDefault();
        network.selectNodes([ev.target.dataset.target]);
        network.focus(ev.target.dataset.target, {{ scale: 1.2, animation: true }});
        ev.target.dispatchEvent(new MouseEvent('mousedown'));
        network.emit && network.emit('selectNode', {{ nodes: [ev.target.dataset.target] }});
      }});
    }});
  }});
  network.on('deselectNode', () => {{
    document.getElementById('side').innerHTML = '<p class="empty">Click a node to inspect its connections.</p>';
  }});
}})();
</script>
</body>
</html>
"""


# ---------- CLI ----------

def _configure_stdio_for_unicode() -> None:
    if sys.platform.startswith("win"):
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:
                pass


def main() -> int:
    _configure_stdio_for_unicode()
    parser = argparse.ArgumentParser(description="Generate an interactive HTML graph viewer over the Charon vault graph")
    parser.add_argument("--out", type=Path, help="Output HTML path (default: <vault>/.charon/graph.html)")
    args = parser.parse_args()

    output_path = args.out if args.out else html_output_path()
    ok, msg = generate_html_from_kuzu(output_path)
    if not ok:
        sys.stderr.write(f"graph HTML generation failed: {msg}\n")
        return 1
    print(msg)
    print(f"Open in a browser:  file://{output_path.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
