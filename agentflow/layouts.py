"""Layout algorithms for positioning nodes in a flow graph.

Provides a HORIZONTAL layout (left→right) with visual grouping by category.
Main control flow runs left to right. Tools branch below. Evolution feeds back.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from typing import Optional

from agentflow.models import Edge, FlowGraph, Node, NodeType


@dataclass
class PositionedNode:
    node: Node
    x: float
    y: float
    width: float
    height: float
    group_id: str = ""


@dataclass
class GroupBox:
    """A visual background rectangle behind a group of nodes."""
    group_id: str
    label: str
    x: float
    y: float
    width: float
    height: float
    background: str
    stroke: str


@dataclass
class LayoutResult:
    positioned: list[PositionedNode]
    width: float
    height: float
    groups: dict[str, list[str]] = field(default_factory=dict)
    group_boxes: list[GroupBox] = field(default_factory=list)


# ── Dimensions per node type ───────────────────────────────────────────

NODE_WIDTHS: dict[NodeType, float] = {
    NodeType.START: 180,
    NodeType.END: 180,
    NodeType.PROCESS: 300,
    NodeType.DECISION: 220,
    NodeType.SUBPROCESS: 300,
    NodeType.TOOL: 280,
    NodeType.LOOP: 280,
    NodeType.EVOLUTION: 280,
}

NODE_HEIGHTS: dict[NodeType, float] = {
    NodeType.START: 70,
    NodeType.END: 70,
    NodeType.PROCESS: 84,
    NodeType.DECISION: 100,
    NodeType.SUBPROCESS: 84,
    NodeType.TOOL: 84,
    NodeType.LOOP: 84,
    NodeType.EVOLUTION: 84,
}

# ── Modern palette ─────────────────────────────────────────────────────

NODE_COLORS: dict[NodeType, dict[str, str]] = {
    NodeType.START:     {"background": "#dcfce7", "stroke": "#16a34a"},
    NodeType.END:       {"background": "#fee2e2", "stroke": "#dc2626"},
    NodeType.PROCESS:   {"background": "#ede9fe", "stroke": "#7c3aed"},
    NodeType.DECISION:  {"background": "#fef9c3", "stroke": "#ca8a04"},
    NodeType.SUBPROCESS: {"background": "#dbeafe", "stroke": "#2563eb"},
    NodeType.TOOL:      {"background": "#ccfbf1", "stroke": "#0d9488"},
    NodeType.LOOP:      {"background": "#fce7f3", "stroke": "#db2777"},
    NodeType.EVOLUTION: {"background": "#ffedd5", "stroke": "#ea580c"},
}

# ── Category definitions ───────────────────────────────────────────────

CATEGORY_STYLES: dict[str, dict[str, str]] = {
    "init":     {"background": "#f0fdf4", "stroke": "#86efac", "label": "INIT"},
    "loop":     {"background": "#fdf2f8", "stroke": "#f9a8d4", "label": "MAIN LOOP"},
    "dispatch": {"background": "#f5f3ff", "stroke": "#c4b5fd", "label": "DISPATCH & EVALUATE"},
    "tools":    {"background": "#f0fdfa", "stroke": "#5eead4", "label": "TOOLS"},
    "evolution":{"background": "#fff7ed", "stroke": "#fdba74", "label": "SELF-EVOLUTION"},
    "teardown": {"background": "#fef2f2", "stroke": "#fca5a5", "label": "TEARDOWN"},
}

# Node type -> default category
_NODE_CATEGORIES: dict[NodeType, str] = {
    NodeType.START: "init",
    NodeType.END: "teardown",
    NodeType.PROCESS: "loop",
    NodeType.DECISION: "dispatch",
    NodeType.LOOP: "loop",
    NodeType.TOOL: "tools",
    NodeType.SUBPROCESS: "tools",
    NodeType.EVOLUTION: "evolution",
}

# ── Spacing constants ──────────────────────────────────────────────────

H_GAP = 60        # Horizontal gap between nodes in same row
V_GAP = 40        # Vertical gap between rows
ROW_HEIGHT = 140  # Height per row (node + gap)
GROUP_PAD = 30    # Padding inside group boxes
GROUP_GAP = 50    # Gap between group boxes


def hierarchical_layout(
    graph: FlowGraph,
    **kwargs,
) -> LayoutResult:
    """Horizontal layout: main flow left→right, tools below, evolution as feedback."""
    if not graph.nodes:
        return LayoutResult([], 0, 0)

    # 1. Assign nodes to rows and categories
    main_row, tool_row, evo_row = _assign_rows(graph)

    # 2. Position main flow horizontally
    positioned: list[PositionedNode] = []
    x_cursor = 80.0

    # Main flow (row 0): start → init → loop → decisions → end
    for node_id in main_row:
        node = graph.get_node(node_id)
        if node is None:
            continue
        w = NODE_WIDTHS.get(node.node_type, 300)
        h = NODE_HEIGHTS.get(node.node_type, 84)
        y = 80.0  # Fixed Y for main row
        positioned.append(PositionedNode(node=node, x=x_cursor, y=y, width=w, height=h, group_id=_NODE_CATEGORIES.get(node.node_type, "loop")))
        x_cursor += w + H_GAP

    main_width = x_cursor

    # Tool row (row 1): tools positioned below main flow
    tool_x = 80.0
    for node_id in tool_row:
        node = graph.get_node(node_id)
        if node is None:
            continue
        w = NODE_WIDTHS.get(node.node_type, 280)
        h = NODE_HEIGHTS.get(node.node_type, 84)
        y = 80.0 + ROW_HEIGHT + V_GAP  # Below main row
        positioned.append(PositionedNode(node=node, x=tool_x, y=y, width=w, height=h, group_id="tools"))
        tool_x += w + H_GAP

    # Evolution row (row 2): evolution nodes at bottom
    evo_x = 80.0
    for node_id in evo_row:
        node = graph.get_node(node_id)
        if node is None:
            continue
        w = NODE_WIDTHS.get(node.node_type, 280)
        h = NODE_HEIGHTS.get(node.node_type, 84)
        y = 80.0 + 2 * (ROW_HEIGHT + V_GAP)  # Below tools
        positioned.append(PositionedNode(node=node, x=evo_x, y=y, width=w, height=h, group_id="evolution"))
        evo_x += w + H_GAP

    # 3. Compute group boxes
    group_boxes = _compute_group_boxes(positioned, main_width)

    max_x = max((p.x + p.width for p in positioned), default=0)
    max_y = max((p.y + p.height for p in positioned), default=0)

    return LayoutResult(
        positioned=positioned,
        width=max_x + 80,
        height=max_y + 80,
        group_boxes=group_boxes,
    )


# ── Grid layout (fallback) ────────────────────────────────────────────


def grid_layout(graph: FlowGraph, **kwargs) -> LayoutResult:
    """Simple grid layout for non-agent graphs."""
    return hierarchical_layout(graph, **kwargs)


# ── Internal helpers ──────────────────────────────────────────────────


def _assign_rows(graph: FlowGraph) -> tuple[list[str], list[str], list[str]]:
    """Assign nodes to main row, tool row, or evolution row."""
    main_row: list[str] = []
    tool_row: list[str] = []
    evo_row: list[str] = []

    # Topological order for main flow
    order = _topological_sort(graph)

    for node_id in order:
        node = graph.get_node(node_id)
        if node is None:
            continue

        cat = _NODE_CATEGORIES.get(node.node_type, "loop")

        if node.node_type in (NodeType.TOOL, NodeType.SUBPROCESS):
            tool_row.append(node_id)
        elif node.node_type == NodeType.EVOLUTION:
            evo_row.append(node_id)
        else:
            main_row.append(node_id)

    return main_row, tool_row, evo_row


def _compute_group_boxes(positioned: list[PositionedNode], main_width: float) -> list[GroupBox]:
    """Compute background rectangles for each category group."""
    boxes: list[GroupBox] = []

    # Group by category and Y position
    by_group: dict[str, list[PositionedNode]] = defaultdict(list)
    for p in positioned:
        by_group[p.group_id].append(p)

    for group_id, nodes in by_group.items():
        if not nodes:
            continue

        style = CATEGORY_STYLES.get(group_id, CATEGORY_STYLES["loop"])

        min_x = min(n.x for n in nodes) - GROUP_PAD
        min_y = min(n.y for n in nodes) - GROUP_PAD
        max_x = max(n.x + n.width for n in nodes) + GROUP_PAD
        max_y = max(n.y + n.height for n in nodes) + GROUP_PAD

        boxes.append(GroupBox(
            group_id=group_id,
            label=style["label"],
            x=min_x,
            y=min_y,
            width=max_x - min_x,
            height=max_y - min_y,
            background=style["background"],
            stroke=style["stroke"],
        ))

    return boxes


def _topological_sort(graph: FlowGraph) -> list[str]:
    """Kahn's algorithm for topological ordering."""
    in_degree: dict[str, int] = {n.id: 0 for n in graph.nodes}
    adj: dict[str, list[str]] = {n.id: [] for n in graph.nodes}

    for e in graph.edges:
        if e.target in in_degree:
            in_degree[e.target] += 1
        if e.source in adj:
            adj[e.source].append(e.target)

    queue = [nid for nid, deg in in_degree.items() if deg == 0]
    order: list[str] = []

    while queue:
        nid = queue.pop(0)
        order.append(nid)
        for neighbor in adj.get(nid, []):
            in_degree[neighbor] -= 1
            if in_degree[neighbor] == 0:
                queue.append(neighbor)

    for n in graph.nodes:
        if n.id not in order:
            order.append(n.id)

    return order
