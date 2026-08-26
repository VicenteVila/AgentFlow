"""Render a FlowGraph as Unicode box-drawing ASCII art.

The output is plain text suitable for terminal display or ``--format ascii``.

Diff status is shown as [+]/[-]/[~] prefixes; semantic edge colors are
represented as YES (green) / NO (red) labels.
"""

from __future__ import annotations

from pathlib import Path

from agentflow.layouts import with_detail_level
from agentflow.models import FlowGraph

_DIFF_PREFIX = {
    "added": "[+]",
    "removed": "[-]",
    "changed": "[~]",
    "unchanged": "   ",
    "": "   ",
}

_NODE_TYPE_LABEL = {
    "start": "START",
    "end": "END",
    "process": "PROCESS",
    "decision": "DECISION",
    "subprocess": "SUBPROC",
    "tool": "TOOL",
    "loop": "LOOP",
    "evolution": "EVOLVE",
}


def _node_line(node, detail_level: str) -> str:
    prefix = _DIFF_PREFIX.get(node.diff_status, "   ")
    tlabel = _NODE_TYPE_LABEL.get(node.node_type.value, node.node_type.value.upper())
    # Detail handling already done via with_detail_level, but keep fallback
    if node.detail and detail_level != "low":
        # Show detail as second line indented, but for single-line summary use first line
        detail_first = node.detail.split("\n")[0]
        return f"{prefix} [{tlabel}] {node.label} — {detail_first}"
    return f"{prefix} [{tlabel}] {node.label}"


def to_ascii(
    graph: FlowGraph,
    detail: str = "high",
    _layout: str = "hierarchical",  # accepted for CLI compatibility, unused
) -> str:
    """Render *graph* as indented ASCII flowchart."""
    if detail != "high":
        graph = with_detail_level(graph, detail)

    lines: list[str] = []
    lines.append(f"Flow: {graph.title}")
    lines.append("=" * max(len(graph.title) + 6, 40))
    lines.append(f"Nodes: {graph.node_count}  Edges: {graph.edge_count}")
    lines.append("")

    # Build adjacency for traversal
    from collections import defaultdict

    outgoing: dict[str, list] = defaultdict(list)
    for e in graph.edges:
        outgoing[e.source].append(e)
    incoming: dict[str, int] = {n.id: 0 for n in graph.nodes}
    for e in graph.edges:
        if e.target in incoming:
            incoming[e.target] += 1

    # Topological-ish order: start nodes first, then BFS
    visited: set[str] = set()
    # Find start nodes (in_degree 0)
    queue = [n.id for n in graph.nodes if incoming.get(n.id, 0) == 0]
    if not queue:
        queue = [graph.nodes[0].id] if graph.nodes else []
    order: list[str] = []
    while queue:
        nid = queue.pop(0)
        if nid in visited:
            continue
        visited.add(nid)
        order.append(nid)
        for e in outgoing.get(nid, []):
            if e.target not in visited and e.target not in queue:
                queue.append(e.target)
    # Add any isolated nodes not visited
    for n in graph.nodes:
        if n.id not in visited:
            order.append(n.id)

    id_to_node = {n.id: n for n in graph.nodes}

    for nid in order:
        node = id_to_node.get(nid)
        if not node:
            continue
        lines.append(_node_line(node, detail))
        outs = outgoing.get(nid, [])
        if not outs:
            continue
        # Group by label for compact display
        if len(outs) == 1:
            e = outs[0]
            target = id_to_node.get(e.target)
            tlabel = target.label if target else e.target
            diff_m = f" [{e.diff_status}]" if e.diff_status and e.diff_status != "unchanged" else ""
            label_part = f" -- {e.label} -->" if e.label else " ──▶"
            lines.append(f"     {label_part} {tlabel}{diff_m}")
        else:
            for e in outs:
                target = id_to_node.get(e.target)
                tlabel = target.label if target else e.target
                diff_m = f" [{e.diff_status}]" if e.diff_status and e.diff_status != "unchanged" else ""
                # Semantic prefix for YES/NO
                prefix = "├─" if e is not outs[-1] else "└─"
                if e.label == "YES":
                    prefix += " YES ─▶"
                elif e.label == "NO":
                    prefix += " NO  ─▶"
                elif e.label:
                    prefix += f" {e.label} ─▶"
                else:
                    prefix += " ──▶"
                lines.append(f"     {prefix} {tlabel}{diff_m}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def save_ascii(
    graph: FlowGraph,
    output_path: str | Path,
    detail: str = "high",
    layout: str = "hierarchical",
) -> Path:
    """Save ASCII rendering to *output_path*."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_ascii(graph, detail=detail, _layout=layout), encoding="utf-8")
    return path
