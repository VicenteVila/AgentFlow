"""Layout algorithms for positioning nodes in a flow graph.

Provides two layout modes:
- hierarchical: HORIZONTAL layout (left→right) with visual grouping by category.
- phased: VERTICAL layout (top→bottom) with phase boxes (FASE 1, 2, 3).
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
    phase: int = 0  # Phase index (1, 2, 3) for phased layout


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
class PhaseBox:
    """A phase background rectangle (FASE 1, 2, 3)."""
    phase: int
    label: str
    x: float
    y: float
    width: float
    height: float
    background: str
    stroke: str


@dataclass
class FeedbackArrow:
    """A feedback arrow (e.g., budget→reason, revert→budget)."""
    source_id: str
    target_id: str
    label: str = ""
    style: str = "dashed"
    color: str = "#1971c2"


@dataclass
class LayoutResult:
    positioned: list[PositionedNode]
    width: float
    height: float
    groups: dict[str, list[str]] = field(default_factory=dict)
    group_boxes: list[GroupBox] = field(default_factory=list)
    phase_boxes: list[PhaseBox] = field(default_factory=list)
    feedback_arrows: list[FeedbackArrow] = field(default_factory=list)


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

# ── Phase definitions (for phased vertical layout) ────────────────────

PHASE_DEFS = {
    1: {
        "label": "FASE 1 · PREPARACIÓN",
        "background": "#f8f9fa",
        "stroke": "#868e96",
    },
    2: {
        "label": "FASE 2 · LOOP DE EVOLUCIÓN (H1…Hn)",
        "background": "#fff9db",
        "stroke": "#868e96",
    },
    3: {
        "label": "FASE 3 · CIERRE",
        "background": "#ebfbee",
        "stroke": "#868e96",
    },
}

# Node ID patterns → phase assignment
_PHASE_PATTERNS: dict[str, int] = {
    "start": 1,
    "init": 1,
    "seed": 1,
    "decision_url": 1,
    "fetch_url": 1,
    "main_loop": 2,
    "render": 2,
    "llm": 2,
    "budget": 2,
    "generate": 2,
    "audit": 2,
    "truth": 2,
    "revert": 2,
    "vlm": 2,
    "creative": 2,
    "lesson": 2,
    "auto_lesson": 2,
    "subtask_lesson": 2,
    "content_lesson": 2,
    "truth_audit": 2,
    "visual_audit": 2,
    "novelty": 2,
    "compact": 2,
    "snapshot": 2,  # snapshot_workspace is inside the loop
    "select": 3,
    "export": 3,
    "final": 3,
    "end": 3,
    "meta": 3,
    "harm": 3,
    "summary": 3,
}

# Phased layout constants
PHASE_H_GAP = 40     # Horizontal gap between nodes in same row
PHASE_V_GAP = 30     # Vertical gap between rows within a phase
PHASE_ROW_H = 130    # Height per row (node + gap)
PHASE_PAD = 40       # Padding inside phase boxes
PHASE_GAP = 60       # Gap between phase boxes
PHASE_TOP = 80       # Starting Y position
PHASE_CENTER_X = 500 # Center X for main flow
PHASE_SIDE_X = 120   # X for side branches (left)
PHASE_TOOL_X = 780   # X for tool branches (right)


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


def phased_layout(graph: FlowGraph, **kwargs) -> LayoutResult:
    """Vertical phased layout: nodes flow top→bottom, grouped into FASE 1/2/3 boxes.

    Main flow runs down the center. Tools branch to the right. Evolution
    feeds back upward. Matches the reference hand-crafted Excalidraw style.
    """
    if not graph.nodes:
        return LayoutResult([], 0, 0)

    # 1. Assign nodes to phases
    phase_groups: dict[int, list[str]] = {1: [], 2: [], 3: []}
    for node in graph.nodes:
        phase = _assign_phase(node)
        phase_groups[phase].append(node.id)

    # 2. Topological order within each phase
    for phase in phase_groups:
        phase_groups[phase] = _topo_order_filtered(graph, phase_groups[phase])

    # 3. Separate main flow from side branches per phase
    positioned: list[PositionedNode] = []
    y_cursor = float(PHASE_TOP)

    for phase in [1, 2, 3]:
        node_ids = phase_groups[phase]
        if not node_ids:
            continue

        main_nodes, side_nodes, evo_nodes = _classify_phase_nodes(graph, node_ids)

        # Position main flow nodes down the center
        phase_y = y_cursor
        for nid in main_nodes:
            node = graph.get_node(nid)
            if node is None:
                continue
            w = NODE_WIDTHS.get(node.node_type, 300)
            h = NODE_HEIGHTS.get(node.node_type, 84)
            x = PHASE_CENTER_X - w / 2
            positioned.append(PositionedNode(
                node=node, x=x, y=phase_y, width=w, height=h,
                group_id="main", phase=phase,
            ))
            phase_y += h + PHASE_V_GAP

        # Position side nodes (tools) to the right
        side_y = y_cursor + 60
        for nid in side_nodes:
            node = graph.get_node(nid)
            if node is None:
                continue
            w = NODE_WIDTHS.get(node.node_type, 280)
            h = NODE_HEIGHTS.get(node.node_type, 84)
            positioned.append(PositionedNode(
                node=node, x=PHASE_TOOL_X, y=side_y, width=w, height=h,
                group_id="tools", phase=phase,
            ))
            side_y += h + PHASE_V_GAP

        # Position evolution nodes to the left
        evo_y = y_cursor + 60
        for nid in evo_nodes:
            node = graph.get_node(nid)
            if node is None:
                continue
            w = NODE_WIDTHS.get(node.node_type, 280)
            h = NODE_HEIGHTS.get(node.node_type, 84)
            positioned.append(PositionedNode(
                node=node, x=PHASE_SIDE_X, y=evo_y, width=w, height=h,
                group_id="evolution", phase=phase,
            ))
            evo_y += h + PHASE_V_GAP

        # Update y_cursor to after this phase's tallest column
        max_phase_y = max(
            phase_y,
            side_y if side_nodes else 0,
            evo_y if evo_nodes else 0,
        )
        y_cursor = max_phase_y + PHASE_GAP

    # 4. Compute phase boxes
    phase_boxes = _compute_phase_boxes(positioned)

    # 5. Identify feedback arrows
    feedback = _identify_feedback_arrows(graph, positioned)

    max_x = max((p.x + p.width for p in positioned), default=0)
    max_y = max((p.y + p.height for p in positioned), default=0)

    return LayoutResult(
        positioned=positioned,
        width=max_x + 80,
        height=max_y + 80,
        phase_boxes=phase_boxes,
        feedback_arrows=feedback,
    )


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


def _assign_phase(node: Node) -> int:
    """Assign a node to a phase (1=init, 2=loop, 3=close)."""
    nid = node.id.lower()
    label = node.label.lower()

    # Check exact matches first
    for pattern, phase in _PHASE_PATTERNS.items():
        if pattern in nid:
            return phase

    # Check label matches
    for pattern, phase in _PHASE_PATTERNS.items():
        if pattern in label:
            return phase

    # Default: use node type
    if node.node_type == NodeType.START:
        return 1
    if node.node_type == NodeType.END:
        return 3
    if node.node_type in (NodeType.TOOL, NodeType.SUBPROCESS):
        return 2  # Tools are in the loop phase
    if node.node_type == NodeType.EVOLUTION:
        return 2  # Evolution is in the loop phase

    return 2  # Default to loop phase


def _classify_phase_nodes(
    graph: FlowGraph, node_ids: list[str]
) -> tuple[list[str], list[str], list[str]]:
    """Classify nodes within a phase into main flow, side branches, and evolution."""
    main: list[str] = []
    side: list[str] = []
    evo: list[str] = []

    for nid in node_ids:
        node = graph.get_node(nid)
        if node is None:
            continue
        if node.node_type in (NodeType.TOOL, NodeType.SUBPROCESS):
            side.append(nid)
        elif node.node_type == NodeType.EVOLUTION:
            evo.append(nid)
        else:
            main.append(nid)

    return main, side, evo


def _topo_order_filtered(graph: FlowGraph, node_ids: list[str]) -> list[str]:
    """Return topological order filtered to only the given node_ids."""
    full_order = _topological_sort(graph)
    id_set = set(node_ids)
    return [nid for nid in full_order if nid in id_set]


def _compute_phase_boxes(positioned: list[PositionedNode]) -> list[PhaseBox]:
    """Compute background rectangles for each phase."""
    boxes: list[PhaseBox] = []
    by_phase: dict[int, list[PositionedNode]] = defaultdict(list)

    for p in positioned:
        by_phase[p.phase].append(p)

    for phase in sorted(by_phase.keys()):
        nodes = by_phase[phase]
        if not nodes:
            continue

        defs = PHASE_DEFS.get(phase, PHASE_DEFS[2])
        min_x = min(n.x for n in nodes) - PHASE_PAD
        min_y = min(n.y for n in nodes) - PHASE_PAD
        max_x = max(n.x + n.width for n in nodes) + PHASE_PAD
        max_y = max(n.y + n.height for n in nodes) + PHASE_PAD

        boxes.append(PhaseBox(
            phase=phase,
            label=defs["label"],
            x=min_x,
            y=min_y,
            width=max_x - min_x,
            height=max_y - min_y,
            background=defs["background"],
            stroke=defs["stroke"],
        ))

    return boxes


def _identify_feedback_arrows(
    graph: FlowGraph, positioned: list[PositionedNode]
) -> list[FeedbackArrow]:
    """Identify feedback arrows (edges that go upward in the layout)."""
    pos_lookup = {p.node.id: p for p in positioned}
    feedback: list[FeedbackArrow] = []

    for edge in graph.edges:
        if edge.source in pos_lookup and edge.target in pos_lookup:
            src = pos_lookup[edge.source]
            tgt = pos_lookup[edge.target]
            # Feedback = target is above source (going upward)
            if tgt.y < src.y - 50:
                feedback.append(FeedbackArrow(
                    source_id=edge.source,
                    target_id=edge.target,
                    label=edge.label,
                    style="dashed",
                    color="#1971c2",
                ))

    return feedback


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
