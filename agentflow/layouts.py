"""Layout algorithms for positioning nodes in a flow graph.

Provides two layout modes:
- hierarchical: HORIZONTAL layout (left→right) with visual grouping by category.
- phased: VERTICAL layout (top→bottom) with phase boxes (FASE 1, 2, 3).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from agentflow.models import FlowGraph, Node, NodeType

# ── Text measurement ──────────────────────────────────────────────────

LABEL_FONT = 14
DETAIL_FONT = 10
LINE_H = 1.25      # Excalidraw lineHeight
NODE_PAD_X = 32.0  # horizontal padding inside a node
NODE_PAD_Y = 28.0  # vertical padding inside a node
DIAMOND_FIT = 2.0  # diamonds need bbox ≈ 2× text so it fits the inscribed area
DETAIL_GAP = 8.0   # vertical gap between label and detail text

# Per-character em-widths calibrated for Excalidraw's hand-drawn font.
# Grouped by visual class instead of a flat average for much better fit.
_NARROW_CHARS = set("iljI.,:;'|!()[]{}·-")
_WIDE_CHARS = set("mwMW%@&")


def _char_em_width(ch: str) -> float:
    """Approximate glyph width in em units for the Excalidraw font."""
    if ch in _NARROW_CHARS:
        return 0.34
    if ch in _WIDE_CHARS:
        return 0.95
    if ch.isupper():
        return 0.72
    if ch.isdigit():
        return 0.62
    if ch == " ":
        return 0.30
    return 0.55


def measure_text(text: str, font_size: int = 16) -> tuple[float, float]:
    """Estimate rendered text size (width, height) in diagram units."""
    lines = text.split("\n") if text else [""]
    max_em = max(
        (sum(_char_em_width(ch) for ch in line) for line in lines),
        default=1.0,
    )
    width = max(max_em * font_size, 10.0)
    height = len(lines) * font_size * LINE_H
    return round(width, 1), round(height, 1)


def node_size(node: Node) -> tuple[float, float]:
    """Compute node dimensions: fit the text, respecting per-type minimums."""
    t = node.node_type
    min_w = NODE_WIDTHS.get(t, 300)
    min_h = NODE_HEIGHTS.get(t, 84)

    lw, lh = measure_text(node.label, LABEL_FONT)
    dw = dh = 0.0
    if node.detail:
        dw, dh = measure_text(node.detail, DETAIL_FONT)

    inner_h = lh + (dh + DETAIL_GAP if node.detail else 0.0)

    if t == NodeType.DECISION:
        w = max(min_w, lw * DIAMOND_FIT + NODE_PAD_X, dw * DIAMOND_FIT)
        h = max(min_h, inner_h * DIAMOND_FIT + NODE_PAD_Y)
    else:
        w = max(min_w, lw + NODE_PAD_X, dw + NODE_PAD_X)
        h = max(min_h, inner_h + NODE_PAD_Y)
    return round(w, 1), round(h, 1)


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

# ── Phase definitions (light) ─────────────────────────────────────────

PHASE_DEFS: dict[int, dict[str, str]] = {
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

# ── Themes ─────────────────────────────────────────────────────────────

CATEGORY_STYLES_DARK: dict[str, dict[str, str]] = {
    "init":     {"background": "#052e16", "stroke": "#22c55e", "label": "INIT"},
    "loop":     {"background": "#500724", "stroke": "#db2777", "label": "MAIN LOOP"},
    "dispatch": {"background": "#2e1065", "stroke": "#8b5cf6", "label": "DISPATCH & EVALUATE"},
    "tools":    {"background": "#042f2e", "stroke": "#14b8a6", "label": "TOOLS"},
    "evolution":{"background": "#431407", "stroke": "#f97316", "label": "SELF-EVOLUTION"},
    "teardown": {"background": "#450a0a", "stroke": "#ef4444", "label": "TEARDOWN"},
}

PHASE_DEFS_DARK: dict[int, dict[str, str]] = {
    1: {"label": "FASE 1 · PREPARACIÓN", "background": "#1a1d21", "stroke": "#495057"},
    2: {"label": "FASE 2 · LOOP DE EVOLUCIÓN (H1…Hn)", "background": "#2b2717", "stroke": "#495057"},
    3: {"label": "FASE 3 · CIERRE", "background": "#15291a", "stroke": "#495057"},
}

THEMES: dict[str, dict] = {
    "light": {
        "arrow": "#495057",
        "feedback_arrow": "#1971c2",
        "text": "#1e1e1e",
        "detail_text": "#666666",
        "title": "#1e1e1e",
        "phase_label": "#343a40",
        "canvas_background": "#ffffff",
        "node_colors": NODE_COLORS,
        "category_styles": CATEGORY_STYLES,
        "phase_defs": PHASE_DEFS,
    },
    "dark": {
        "arrow": "#ced4da",
        "feedback_arrow": "#4dabf7",
        "text": "#f1f3f5",
        "detail_text": "#adb5bd",
        "title": "#f8f9fa",
        "phase_label": "#dee2e6",
        "canvas_background": "#111111",
        "node_colors": {
            NodeType.START:      {"background": "#14532d", "stroke": "#4ade80"},
            NodeType.END:        {"background": "#7f1d1d", "stroke": "#f87171"},
            NodeType.PROCESS:    {"background": "#4c1d95", "stroke": "#a78bfa"},
            NodeType.DECISION:   {"background": "#713f12", "stroke": "#facc15"},
            NodeType.SUBPROCESS: {"background": "#1e3a8a", "stroke": "#60a5fa"},
            NodeType.TOOL:       {"background": "#134e4a", "stroke": "#2dd4bf"},
            NodeType.LOOP:       {"background": "#831843", "stroke": "#f472b6"},
            NodeType.EVOLUTION:  {"background": "#7c2d12", "stroke": "#fb923c"},
        },
        "category_styles": CATEGORY_STYLES_DARK,
        "phase_defs": PHASE_DEFS_DARK,
    },
}


def get_theme(name: str) -> dict:
    """Return the palette for a theme name ('light' or 'dark')."""
    return THEMES.get(name, THEMES["light"])

# ── Spacing constants ──────────────────────────────────────────────────

H_GAP = 60        # Horizontal gap between nodes in same row
V_GAP = 40        # Vertical gap between rows
ROW_HEIGHT = 140  # Height per row (node + gap)
GROUP_PAD = 30    # Padding inside group boxes
GROUP_GAP = 50    # Gap between group boxes

# ── Phase definitions (for phased vertical layout) ────────────────────

# Phased layout constants
PHASE_H_GAP = 40     # Horizontal gap between nodes in same row
PHASE_V_GAP = 30     # Vertical gap between rows within a phase
PHASE_ROW_H = 130    # Height per row (node + gap)
PHASE_PAD = 40       # Padding inside phase boxes
PHASE_GAP = 60       # Gap between phase boxes
PHASE_TOP = 80       # Starting Y position
PHASE_SIDE_X = 120   # X for evolution column (left); center/tools derive from content


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
        w, h = node_size(node)
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
        w, h = node_size(node)
        y = 80.0 + ROW_HEIGHT + V_GAP  # Below main row
        positioned.append(PositionedNode(node=node, x=tool_x, y=y, width=w, height=h, group_id="tools"))
        tool_x += w + H_GAP

    # Evolution row (row 2): evolution nodes at bottom
    evo_x = 80.0
    for node_id in evo_row:
        node = graph.get_node(node_id)
        if node is None:
            continue
        w, h = node_size(node)
        y = 80.0 + 2 * (ROW_HEIGHT + V_GAP)  # Below tools
        positioned.append(PositionedNode(node=node, x=evo_x, y=y, width=w, height=h, group_id="evolution"))
        evo_x += w + H_GAP

    # 3. Compute group boxes
    pal = get_theme(kwargs.get("theme", "light"))
    group_boxes = _compute_group_boxes(positioned, main_width, pal["category_styles"])

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
    phase_groups = _phase_groups(graph)

    # 2. Topological order within each phase
    for phase in phase_groups:
        phase_groups[phase] = _topo_order_filtered(graph, phase_groups[phase])

    # 3. Separate main flow from side branches per phase
    positioned: list[PositionedNode] = []
    y_cursor = float(PHASE_TOP)

    # 3a. Adaptive column geometry: derive center X from the widest content
    # in each column so nothing collides regardless of graph size.
    max_main_w = 0.0
    max_side_w = 0.0
    max_evo_w = 0.0
    for node in graph.nodes:
        w, _ = node_size(node)
        if node.node_type in (NodeType.TOOL, NodeType.SUBPROCESS):
            max_side_w = max(max_side_w, w)
        elif node.node_type == NodeType.EVOLUTION:
            max_evo_w = max(max_evo_w, w)
        else:
            max_main_w = max(max_main_w, w)
    col_gap = 120.0
    center_x = PHASE_SIDE_X + max_evo_w + col_gap + max_main_w / 2
    tool_col_x = center_x + max_main_w / 2 + col_gap

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
            w, h = node_size(node)
            x = center_x - w / 2
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
            w, h = node_size(node)
            positioned.append(PositionedNode(
                node=node, x=tool_col_x, y=side_y, width=w, height=h,
                group_id="tools", phase=phase,
            ))
            side_y += h + PHASE_V_GAP

        # Position evolution nodes to the left
        evo_y = y_cursor + 60
        for nid in evo_nodes:
            node = graph.get_node(nid)
            if node is None:
                continue
            w, h = node_size(node)
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
    pal = get_theme(kwargs.get("theme", "light"))
    phase_boxes = _compute_phase_boxes(positioned, pal["phase_defs"])

    # 5. Identify feedback arrows
    feedback = _identify_feedback_arrows(graph, positioned, color=pal["feedback_arrow"])

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

        if node.node_type in (NodeType.TOOL, NodeType.SUBPROCESS):
            tool_row.append(node_id)
        elif node.node_type == NodeType.EVOLUTION:
            evo_row.append(node_id)
        else:
            main_row.append(node_id)

    return main_row, tool_row, evo_row


def _phase_groups(graph: FlowGraph) -> dict[int, list[str]]:
    """Group node ids by phase (1=init, 2=loop, 3=close).

    Uses parser-stamped phase hints when available; otherwise detects
    phases structurally: nodes in cycles → loop phase, their ancestors
    → init phase, the rest → close phase.
    """
    groups: dict[int, list[str]] = {1: [], 2: [], 3: []}

    if any(n.phase for n in graph.nodes):
        for node in graph.nodes:
            groups[node.phase or 2].append(node.id)
        return groups

    return _structural_phase_groups(graph)


def _structural_phase_groups(graph: FlowGraph) -> dict[int, list[str]]:
    """Infer phases from graph topology (works for any agent)."""
    groups: dict[int, list[str]] = {1: [], 2: [], 3: []}
    cyc = _nodes_in_cycles(graph)

    if not cyc:
        # Acyclic graph: single pass — start→1, end→3, rest→2
        for node in graph.nodes:
            groups[_default_phase(node)].append(node.id)
        return groups

    ancestors = _ancestors_of(graph, cyc) - cyc

    for node in graph.nodes:
        if node.id in cyc:
            groups[2].append(node.id)
        elif node.id in ancestors:
            groups[1].append(node.id)
        else:
            groups[3].append(node.id)

    return groups


def _nodes_in_cycles(graph: FlowGraph) -> set[str]:
    """Return ids of nodes that lie on a directed cycle."""
    adj: dict[str, list[str]] = {n.id: [] for n in graph.nodes}
    for e in graph.edges:
        if e.source in adj and e.target in adj:
            adj[e.source].append(e.target)

    cyc: set[str] = set()
    for start, neighbors in adj.items():
        # BFS from successors; cycle iff we can reach `start` again
        stack = list(neighbors)
        seen: set[str] = set()
        while stack and start not in cyc:
            cur = stack.pop()
            if cur == start:
                cyc.add(start)
                break
            if cur in seen:
                continue
            seen.add(cur)
            stack.extend(adj.get(cur, []))
    return cyc


def _ancestors_of(graph: FlowGraph, targets: set[str]) -> set[str]:
    """All nodes that can reach any id in `targets` (excluding targets themselves)."""
    radj: dict[str, list[str]] = {n.id: [] for n in graph.nodes}
    for e in graph.edges:
        if e.source in radj and e.target in radj:
            radj[e.target].append(e.source)

    found: set[str] = set()
    stack = list(targets)
    while stack:
        cur = stack.pop()
        for prev in radj.get(cur, []):
            if prev not in found and prev not in targets:
                found.add(prev)
                stack.append(prev)
    return found


def _default_phase(node: Node) -> int:
    """Type-based phase fallback."""
    if node.node_type == NodeType.START:
        return 1
    if node.node_type == NodeType.END:
        return 3
    return 2


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


def _compute_phase_boxes(
    positioned: list[PositionedNode],
    phase_defs: dict[int, dict[str, str]] | None = None,
) -> list[PhaseBox]:
    """Compute background rectangles for each phase."""
    defs_map = phase_defs or PHASE_DEFS
    boxes: list[PhaseBox] = []
    by_phase: dict[int, list[PositionedNode]] = defaultdict(list)

    for p in positioned:
        by_phase[p.phase].append(p)

    for phase in sorted(by_phase.keys()):
        nodes = by_phase[phase]
        if not nodes:
            continue

        defs = defs_map.get(phase, defs_map[2])
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
    graph: FlowGraph, positioned: list[PositionedNode], color: str = "#1971c2"
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
                    color=color,
                ))

    return feedback


def _compute_group_boxes(
    positioned: list[PositionedNode],
    main_width: float,
    styles: dict[str, dict[str, str]] | None = None,
) -> list[GroupBox]:
    """Compute background rectangles for each category group."""
    style_map = styles or CATEGORY_STYLES
    boxes: list[GroupBox] = []

    # Group by category and Y position
    by_group: dict[str, list[PositionedNode]] = defaultdict(list)
    for p in positioned:
        by_group[p.group_id].append(p)

    for group_id, nodes in by_group.items():
        if not nodes:
            continue

        style = style_map.get(group_id, style_map["loop"])

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
