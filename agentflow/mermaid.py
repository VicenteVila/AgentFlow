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


def _sanitize_id(raw: str) -> str:
    """Mermaid node IDs must be alphanum + underscore, not start with digit."""
    sanitized = re.sub(r"[^A-Za-z0-9_]", "_", raw)
    if sanitized and sanitized[0].isdigit():
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
    # Evolution gets a class for dashed styling
    suffix = ":::evolution" if node.node_type == NodeType.EVOLUTION else ""
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
) -> str:
    """Render *graph* as Mermaid ``flowchart TD`` text."""
    if detail != "high":
        graph = with_detail_level(graph, detail)

    if layout == "grid":
        result = grid_layout(graph)
    elif layout == "phased":
        result = phased_layout(graph)
    else:
        result = hierarchical_layout(graph)

    lines: list[str] = []
    lines.append(f"%% {graph.title}")
    lines.append("flowchart TD")

    # Class for evolution nodes (dashed)
    lines.append("    classDef evolution fill:#ffedd5,stroke:#ea580c,stroke-dasharray: 5 5")

    # Phase / group subgraphs
    boxes = result.phase_boxes if layout == "phased" else result.group_boxes
    # Map phase/group to node ids for subgraph containment
    if boxes:
        # Build lookup phase->node_ids
        from collections import defaultdict
        by_box: dict[str, list[str]] = defaultdict(list)
        # For phased, use phase number; for hierarchical, use group_id
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
                by_box[p.group_id].append(p.node.id)
            for gb in result.group_boxes:
                members = by_box.get(gb.group_id, [])
                if not members:
                    continue
                safe_label = _escape_label(gb.label)
                lines.append(f'    subgraph { _sanitize_id(gb.group_id) } ["{safe_label}"]')
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
        dashed = edge.style == "dashed"
        lines.append(_edge_line(edge.source, edge.target, edge.label, dashed))
    for fb in result.feedback_arrows:
        lines.append(_edge_line(fb.source_id, fb.target_id, fb.label, dashed=True))

    return "\n".join(lines) + "\n"


def save_mermaid(
    graph: FlowGraph,
    output_path: str | Path,
    layout: str = "hierarchical",
    detail: str = "high",
) -> Path:
    """Render *graph* and save as ``.mmd`` file."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_mermaid(graph, layout=layout, detail=detail), encoding="utf-8")
    return path
