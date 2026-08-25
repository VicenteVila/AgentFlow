"""Layout algorithms for positioning nodes in a flow graph.

Provides hierarchical (Sugiyama-lite) and grid layout strategies with
modern visual design, proper spacing, and category-based grouping.
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
    group_id: str = ""  # Visual grouping (Excalidraw groupIds)


@dataclass
class LayoutResult:
    positioned: list[PositionedNode]
    width: float
    height: float
    groups: dict[str, list[str]] = field(default_factory=dict)  # group_id -> [node_ids]


# ── BPMN-inspired dimensions ────────────────────────────────────────────

NODE_WIDTHS: dict[NodeType, float] = {
    NodeType.START: 160,       # Oval — wider for readability
    NodeType.END: 160,
    NodeType.PROCESS: 260,     # Rounded rect — generous
    NodeType.DECISION: 200,    # Diamond — needs space for text
    NodeType.SUBPROCESS: 280,  # Double-bordered rect
    NodeType.TOOL: 240,        # Rect with thick left border
    NodeType.LOOP: 240,        # Hexagon-ish (thick border)
    NodeType.EVOLUTION: 240,   # Dashed rect — self-modification
}

NODE_HEIGHTS: dict[NodeType, float] = {
    NodeType.START: 64,
    NodeType.END: 64,
    NodeType.PROCESS: 80,      # Taller for label + detail
    NodeType.DECISION: 100,    # Taller for diamond + detail
    NodeType.SUBPROCESS: 80,
    NodeType.TOOL: 80,         # Taller for label + detail
    NodeType.LOOP: 80,
    NodeType.EVOLUTION: 80,    # Taller for label + detail
}

# ── Modern professional palette ─────────────────────────────────────────
# Inspired by: Linear, Vercel, Stripe dashboard aesthetics

NODE_COLORS: dict[NodeType, dict[str, str]] = {
    NodeType.START:     {"background": "#dcfce7", "stroke": "#16a34a"},  # Emerald
    NodeType.END:       {"background": "#fee2e2", "stroke": "#dc2626"},  # Red
    NodeType.PROCESS:   {"background": "#ede9fe", "stroke": "#7c3aed"},  # Violet
    NodeType.DECISION:  {"background": "#fef9c3", "stroke": "#ca8a04"},  # Amber
    NodeType.SUBPROCESS: {"background": "#dbeafe", "stroke": "#2563eb"}, # Blue
    NodeType.TOOL:      {"background": "#ccfbf1", "stroke": "#0d9488"},  # Teal
    NodeType.LOOP:      {"background": "#fce7f3", "stroke": "#db2777"},  # Pink
    NodeType.EVOLUTION: {"background": "#ffedd5", "stroke": "#ea580c"},  # Orange
}

# ── Category labels for visual grouping ─────────────────────────────────

CATEGORY_LABELS: dict[str, str] = {
    "control": "Control Flow",
    "tools": "Tool Calls",
    "evolution": "Self-Evolution",
    "setup": "Setup & Teardown",
}

CATEGORY_COLORS: dict[str, dict[str, str]] = {
    "control":   {"background": "#f8fafc", "stroke": "#94a3b8"},
    "tools":     {"background": "#f0fdfa", "stroke": "#5eead4"},
    "evolution": {"background": "#fff7ed", "stroke": "#fb923c"},
    "setup":     {"background": "#faf5ff", "stroke": "#c084fc"},
}

# Node type -> category mapping
_NODE_CATEGORIES: dict[NodeType, str] = {
    NodeType.START: "control",
    NodeType.END: "control",
    NodeType.PROCESS: "control",
    NodeType.DECISION: "control",
    NodeType.LOOP: "control",
    NodeType.TOOL: "tools",
    NodeType.SUBPROCESS: "tools",
    NodeType.EVOLUTION: "evolution",
}


def _get_category(node_type: NodeType) -> str:
    return _NODE_CATEGORIES.get(node_type, "control")


# ── Layout spacing constants ────────────────────────────────────────────

COL_SPACING = 340    # Horizontal gap between nodes
ROW_SPACING = 180    # Vertical gap between layers
START_X = 80         # Left margin
START_Y = 100        # Top margin (below title)
CATEGORY_PADDING = 40  # Padding inside category groups
CATEGORY_GAP = 60      # Gap between categories


def grid_layout(
    graph: FlowGraph,
    col_spacing: float = COL_SPACING,
    row_spacing: float = ROW_SPACING,
    start_x: float = START_X,
    start_y: float = START_Y,
) -> LayoutResult:
    """Simple grid layout: assigns nodes in topological order row by row."""
    if not graph.nodes:
        return LayoutResult([], 0, 0)

    order = _topological_sort(graph)
    positioned: list[PositionedNode] = []

    col = 0
    row = 0

    for node_id in order:
        node = graph.get_node(node_id)
        if node is None:
            continue

        w = NODE_WIDTHS.get(node.node_type, 260)
        h = NODE_HEIGHTS.get(node.node_type, 64)

        x = start_x + col * col_spacing
        y = start_y + row * row_spacing

        cat = _get_category(node.node_type)
        positioned.append(PositionedNode(node=node, x=x, y=y, width=w, height=h, group_id=cat))

        if node.node_type == NodeType.DECISION:
            row += 1
            col = 0
        elif node.node_type in (NodeType.LOOP,):
            row += 1
            col = 0
        else:
            col += 1

    max_x = max((p.x + p.width for p in positioned), default=0)
    max_y = max((p.y + p.height for p in positioned), default=0)

    return LayoutResult(positioned=positioned, width=max_x + 100, height=max_y + 100)


def hierarchical_layout(
    graph: FlowGraph,
    col_spacing: float = COL_SPACING,
    row_spacing: float = ROW_SPACING,
    start_x: float = START_X,
    start_y: float = START_Y,
) -> LayoutResult:
    """Sugiyama-lite hierarchical layout with category-based grouping.

    1. Assign layers via longest-path from start nodes.
    2. Within each layer, order nodes to minimize edge crossings.
    3. Group nodes by category and add visual separation.
    4. Center each layer horizontally.
    """
    if not graph.nodes:
        return LayoutResult([], 0, 0)

    layers = _assign_layers(graph)
    ordered_layers = _order_within_layers(graph, layers)

    positioned: list[PositionedNode] = []
    groups: dict[str, list[str]] = defaultdict(list)

    # Find the maximum layer width to center everything
    max_layer_width = max(
        sum(NODE_WIDTHS.get(graph.get_node(nid).node_type, 260) + COL_SPACING
            for nid in layer if graph.get_node(nid))
        for layer in ordered_layers
    ) if ordered_layers else 0

    for row_idx, layer in enumerate(ordered_layers):
        # Calculate actual layer width for centering
        layer_width = sum(
            NODE_WIDTHS.get(graph.get_node(nid).node_type, 260)
            for nid in layer if graph.get_node(nid)
        )
        layer_width += (len(layer) - 1) * COL_SPACING

        # Center the layer
        layer_offset = (max_layer_width - layer_width) / 2

        x_cursor = start_x + layer_offset

        for col_idx, node_id in enumerate(layer):
            node = graph.get_node(node_id)
            if node is None:
                continue

            w = NODE_WIDTHS.get(node.node_type, 260)
            h = NODE_HEIGHTS.get(node.node_type, 64)

            x = x_cursor
            y = start_y + row_idx * row_spacing

            cat = _get_category(node.node_type)
            pos = PositionedNode(node=node, x=x, y=y, width=w, height=h, group_id=cat)
            positioned.append(pos)
            groups[cat].append(node_id)

            x_cursor += w + COL_SPACING

    max_x = max((p.x + p.width for p in positioned), default=0)
    max_y = max((p.y + p.height for p in positioned), default=0)

    return LayoutResult(
        positioned=positioned,
        width=max_x + 100,
        height=max_y + 100,
        groups=dict(groups),
    )


# ── Internal helpers ──────────────────────────────────────────────────


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


def _assign_layers(graph: FlowGraph) -> dict[str, int]:
    """Assign each node to a layer using longest-path from roots."""
    adj: dict[str, list[str]] = {n.id: [] for n in graph.nodes}
    for e in graph.edges:
        if e.source in adj:
            adj[e.source].append(e.target)

    layer_of: dict[str, int] = {}
    _visiting: set[str] = set()

    def dfs(node_id: str) -> int:
        if node_id in layer_of:
            return layer_of[node_id]
        if node_id in _visiting:
            layer_of[node_id] = 0
            return 0
        _visiting.add(node_id)
        children = adj.get(node_id, [])
        if not children:
            layer_of[node_id] = 0
        else:
            max_child = max((dfs(c) for c in children), default=0)
            layer_of[node_id] = max_child + 1
        _visiting.discard(node_id)
        return layer_of[node_id]

    incoming = {e.target for e in graph.edges}
    roots = [n.id for n in graph.nodes if n.id not in incoming]

    if not roots and graph.nodes:
        roots = [graph.nodes[0].id]

    for root in roots:
        dfs(root)

    for n in graph.nodes:
        if n.id not in layer_of:
            dfs(n.id)

    if layer_of:
        max_layer = max(layer_of.values())
        layer_of = {k: max_layer - v for k, v in layer_of.items()}

    return layer_of


def _order_within_layers(
    graph: FlowGraph, layers: dict[str, int]
) -> list[list[str]]:
    """Group nodes by layer, preserving a reasonable order."""
    grouped: dict[int, list[str]] = defaultdict(list)
    for node in graph.nodes:
        layer = layers.get(node.id, 0)
        grouped[layer].append(node.id)

    max_layer = max(grouped.keys()) if grouped else 0
    result: list[list[str]] = []
    for i in range(max_layer + 1):
        result.append(grouped.get(i, []))

    return result
