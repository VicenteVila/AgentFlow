"""Diff two FlowGraphs and produce a merged graph annotated with diff_status.

Each node/edge in the result carries ``diff_status``:
- added     — only in new
- removed   — only in old
- changed   — in both but label/detail/type differ (uses new version)
- unchanged — identical in both
"""

from __future__ import annotations

from pathlib import Path

from agentflow.models import Edge, FlowGraph, Node
from agentflow.parser import parse_file


def _node_changed(a: Node, b: Node) -> bool:
    return (
        a.label != b.label
        or a.detail != b.detail
        or a.node_type != b.node_type
        or a.phase != b.phase
    )


def diff_graphs(old: FlowGraph, new: FlowGraph, title: str | None = None) -> FlowGraph:
    """Merge *old* and *new* into a diff-annotated FlowGraph."""
    merged = FlowGraph(title=title or f"Diff: {old.title} → {new.title}")

    old_by_id = {n.id: n for n in old.nodes}
    new_by_id = {n.id: n for n in new.nodes}
    all_ids = sorted(set(old_by_id) | set(new_by_id))

    for nid in all_ids:
        if nid in old_by_id and nid not in new_by_id:
            src = old_by_id[nid]
            merged.add_node(Node(
                id=src.id, label=src.label, detail=src.detail,
                node_type=src.node_type, line=src.line, phase=src.phase,
                diff_status="removed",
            ))
        elif nid in new_by_id and nid not in old_by_id:
            src = new_by_id[nid]
            merged.add_node(Node(
                id=src.id, label=src.label, detail=src.detail,
                node_type=src.node_type, line=src.line, phase=src.phase,
                diff_status="added",
            ))
        else:
            o = old_by_id[nid]
            n = new_by_id[nid]
            status = "changed" if _node_changed(o, n) else "unchanged"
            merged.add_node(Node(
                id=n.id, label=n.label, detail=n.detail,
                node_type=n.node_type, line=n.line, phase=n.phase,
                diff_status=status,
            ))

    # Edges keyed by (source, target, label)
    def edge_key(e: Edge) -> tuple[str, str, str]:
        return (e.source, e.target, e.label)

    old_edges = {edge_key(e): e for e in old.edges}
    new_edges = {edge_key(e): e for e in new.edges}
    all_keys = set(old_edges) | set(new_edges)

    for key in sorted(all_keys):
        if key in old_edges and key not in new_edges:
            e = old_edges[key]
            merged.add_edge(Edge(source=e.source, target=e.target, label=e.label,
                                 style=e.style, diff_status="removed"))
        elif key in new_edges and key not in old_edges:
            e = new_edges[key]
            merged.add_edge(Edge(source=e.source, target=e.target, label=e.label,
                                 style=e.style, diff_status="added"))
        else:
            e = new_edges[key]
            merged.add_edge(Edge(source=e.source, target=e.target, label=e.label,
                                 style=e.style, diff_status="unchanged"))

    return merged


def diff_files(
    old_path: str | Path,
    new_path: str | Path,
    profile: str | object | None = None,
) -> FlowGraph:
    """Parse two files and return their diff graph."""
    old = parse_file(old_path, profile=profile)
    new = parse_file(new_path, profile=profile)
    old.title = str(old_path)
    new.title = str(new_path)
    return diff_graphs(old, new)
