"""Render a FlowGraph as Mermaid flowchart syntax.

Output is a ``flowchart TD`` string that renders natively on GitHub,
GitLab, Notion, etc. No external dependencies.

Usage:
    text = to_mermaid(graph, layout="phased", detail="high")
"""

from __future__ import annotations

import re
from pathlib import Path

from agentflow.layouts import (
    grid_layout,
    hierarchical_layout,
    phased_layout,
    with_detail_level,
)
from agentflow.models import FlowGraph, NodeType

_MERMAID_SHAPES = {
    NodeType.START: ("([", "])"),
    NodeType.END: ("([", "])"),
    NodeType.DECISION: ("{", "}"),
    NodeType.SUBPROCESS: ("[[", "]]"),
}

_DEFAULT_SHAPE = ('[', ']')


_MERMAID_RESERVED = frozenset(
    {"graph", "flowchart", "subgraph", "end", "start", "click", "classDef", "class", "style", "linkStyle", "interpolate"}
)


def _sanitize_id(raw: str) -> str:
    """Mermaid node IDs must be alphanum + underscore, not start with digit, not reserved."""
    sanitized = re.sub(r"[^A-Za-z0-9_]", "_", raw)
    if sanitized and sanitized[0].isdigit():
        sanitized = "n_" + sanitized
    if sanitized in _MERMAID_RESERVED:
        sanitized = "n_" + sanitized
    return sanitized or "node"


def _escape_label(text: str) -> str:
    """Escape text for inside Mermaid brackets."""
    # Replace characters that would break bracket parsing
    replacements = {
        '"': "'",
        '[': '(',
        ']': ')',
        '{': '(',
        '}': ')',
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
    # Newlines become <br>
    text = text.replace("\n", "<br>")
    # Mermaid comment marker
    text = text.replace("--", "—")
    return text.strip()


def _node_label(node) -> str:
    parts = [node.label]
    if node.detail:
        parts.append(node.detail)
    combined = "<br><i>".join(_escape_label(p) for p in parts if p)
    # Close italic if detail present
    if node.detail:
        combined += "</i>"
    # Truncate extremely long labels for Mermaid readability
    if len(combined) > 200:
        combined = combined[:197] + "..."
    return combined


def _node_definition(node) -> str:
    nid = _sanitize_id(node.id)
    label = _node_label(node)
    l_brace, r_brace = _MERMAID_SHAPES.get(node.node_type, _DEFAULT_SHAPE)
    if node.diff_status in ("added", "removed", "changed"):
        suffix = f":::{node.diff_status}"
    elif node.node_type == NodeType.EVOLUTION:
        suffix = ":::evolution"
    else:
        suffix = ""
    return f'    {nid}{l_brace}"{label}"{r_brace}{suffix}'


def _edge_line(source: str, target: str, label: str, dashed: bool) -> str:
    s = _sanitize_id(source)
    t = _sanitize_id(target)
    if label:
        safe = _escape_label(label).replace('"', "'")
        if dashed:
            return f'    {s} -. "{safe}" .-> {t}'
        return f'    {s} -- "{safe}" --> {t}'
    if dashed:
        return f'    {s} -.-> {t}'
    return f'    {s} --> {t}'


def to_mermaid(
    graph: FlowGraph,
    layout: str = "hierarchical",
    detail: str = "high",
    links: dict[str, str] | None = None,
    title: str | None = None,
) -> str:
    """Render *graph* as Mermaid ``flowchart TD`` text.

    *links* maps node IDs to relative ``.mmd``/``.html`` URLs.
    For each linked node a ``click <id> href "<url>"`` directive is appended,
    enabling interactive drill-down in viewers that support
    ``securityLevel: loose`` (e.g. mermaid.live, HTML+mermaid.js wrapper).
    """
    if detail != "high":
        graph = with_detail_level(graph, detail)

    if layout == "grid":
        result = grid_layout(graph)
    elif layout == "phased":
        result = phased_layout(graph)
    elif layout == "swimlane":
        from agentflow.layouts import swimlane_layout
        result = swimlane_layout(graph)
    else:
        result = hierarchical_layout(graph)

    lines: list[str] = []
    lines.append(f"%% {title or graph.title}")
    if links:
        lines.append("%%{init: {'securityLevel':'loose'}}%%")
    lines.append("flowchart TD")

    # Class for evolution nodes (dashed)
    lines.append("    classDef evolution fill:#ffedd5,stroke:#ea580c,stroke-dasharray: 5 5")
    lines.append("    classDef added fill:#a7f3d0,stroke:#065f46")
    lines.append("    classDef removed fill:#fecaca,stroke:#991b1b,stroke-dasharray: 5 5")
    lines.append("    classDef changed fill:#fde68a,stroke:#92400e")

    # Phase / group / lane subgraphs
    if layout == "phased":
        boxes = result.phase_boxes
    elif layout == "swimlane":
        boxes = result.lane_boxes
    else:
        boxes = result.group_boxes
    # Map phase/group/lane to node ids for subgraph containment
    if boxes:
        # Build lookup
        from collections import defaultdict
        by_box: dict[str, list[str]] = defaultdict(list)
        # For phased, use phase number; for hierarchical/swimlane, use group_id/lane_id
        if layout == "phased":
            for p in result.positioned:
                by_box[str(p.phase)].append(p.node.id)
            for pb in result.phase_boxes:
                key = str(pb.phase)
                members = by_box.get(key, [])
                if not members:
                    continue
                safe_label = _escape_label(pb.label)
                lines.append(f'    subgraph { _sanitize_id(key) } ["{safe_label}"]')
                for nid in members:
                    # Node definitions inside subgraph
                    node = next((x.node for x in result.positioned if x.node.id == nid), None)
                    if node:
                        lines.append(_node_definition(node))
                lines.append("    end")
        else:
            for p in result.positioned:
                # For swimlane, group_id is lane; for hierarchical, same
                by_box[p.group_id].append(p.node.id)
            # Choose correct box list
            box_list = result.lane_boxes if layout == "swimlane" else result.group_boxes
            for box in box_list:
                # LaneBox has lane_id, GroupBox has group_id
                bid = getattr(box, "lane_id", getattr(box, "group_id", ""))
                members = by_box.get(bid, [])
                if not members:
                    continue
                safe_label = _escape_label(box.label)
                lines.append(f'    subgraph { _sanitize_id(bid) } ["{safe_label}"]')
                for nid in members:
                    node = next((x.node for x in result.positioned if x.node.id == nid), None)
                    if node:
                        lines.append(_node_definition(node))
                lines.append("    end")
        # Nodes not in any box (fallback, should not happen)
        boxed_ids = {nid for ids in by_box.values() for nid in ids}
        for p in result.positioned:
            if p.node.id not in boxed_ids:
                lines.append(_node_definition(p.node))
    else:
        for p in result.positioned:
            lines.append(_node_definition(p.node))

    # Edges (deduplicated via geometry policy)
    from agentflow.geometry import resolve_edges
    edges_by_pair = resolve_edges(graph, result)
    for edge in edges_by_pair.values():
        dashed = edge.style == "dashed" or edge.diff_status == "removed"
        lines.append(_edge_line(edge.source, edge.target, edge.label, dashed))
    for fb in result.feedback_arrows:
        lines.append(_edge_line(fb.source_id, fb.target_id, fb.label, dashed=True))

    # Click directives for interactive drill-down
    if links:
        for nid, url in links.items():
            sid = _sanitize_id(nid)
            lines.append(f'    click {sid} href "{url}" "Abrir detalle"')

    return "\n".join(lines) + "\n"


def save_mermaid(
    graph: FlowGraph,
    output_path: str | Path,
    layout: str = "hierarchical",
    detail: str = "high",
    links: dict[str, str] | None = None,
    title: str | None = None,
) -> Path:
    """Render *graph* and save as ``.mmd`` file."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        to_mermaid(graph, layout=layout, detail=detail, links=links, title=title),
        encoding="utf-8",
    )
    return path


_MERMAID_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <style>
    body {{ margin: 0; padding: 24px; font-family: system-ui,-apple-system,sans-serif; background: #f8fafc; }}
    h1 {{ font-size: 1.2rem; color: #334155; margin: 0 0 8px 0; }}
    .note {{ font-size: 0.8rem; color: #94a3b8; margin: 0 0 16px 0; }}
    #diagram {{ background: #fff; border: 1px solid #e2e8f0; border-radius: 8px; padding: 24px; overflow: auto; }}
    .mermaid {{ display: flex; justify-content: center; }}
    #diagram pre.mermaid {{ margin: 0; background: transparent; }}
  </style>
</head>
<body>
  <h1>{title}</h1>
  <p class="note">Click en los modulos con cursor mano para drill-down.</p>
  <div id="diagram"><pre class="mermaid">
{mmd_content}
  </pre></div>
  <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
  <script>mermaid.initialize({{startOnLoad:true,securityLevel:'loose',theme:'default',flowchart:{{useMaxWidth:false,htmlLabels:true,curve:'basis'}}}});</script>
</body>
</html>
"""


def to_mermaid_html(
    graph: FlowGraph,
    layout: str = "phased",
    detail: str = "high",
    links: dict[str, str] | None = None,
    title: str | None = None,
) -> str:
    """Wrap ``to_mermaid`` output in a standalone HTML with mermaid.js CDN."""
    mmd = to_mermaid(graph, layout=layout, detail=detail, links=links, title=title)
    resolved_title = title or graph.title
    return _MERMAID_HTML_TEMPLATE.format(title=resolved_title, mmd_content=mmd)


def save_mermaid_html(
    graph: FlowGraph,
    output_path: str | Path,
    layout: str = "phased",
    detail: str = "high",
    links: dict[str, str] | None = None,
    title: str | None = None,
) -> Path:
    """Save mermaid HTML wrapper (CDN + loose) to *output_path*."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        to_mermaid_html(graph, layout=layout, detail=detail, links=links, title=title),
        encoding="utf-8",
    )
    return path
