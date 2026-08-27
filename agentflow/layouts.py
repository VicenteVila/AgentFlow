"""Layout algorithms for positioning nodes in a flow graph.

Provides the following layouts:
- hierarchical: HORIZONTAL layout (left→right) with visual grouping by category.
- grid: tiled rows of nodes.
- phased: VERTICAL layout (top→bottom) with phase boxes (FASE 1, 2, 3).
- phased-horizontal: phases as COLUMNS left→right, nodes flowing top→bottom.
- radial: circular rings around a central 'agent' node.
- swimlane: vertical lanes keyed by role.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field

from agentflow.models import Edge, FlowGraph, Node, NodeType

# ── Text measurement ──────────────────────────────────────────────────

LABEL_FONT = 14
DETAIL_FONT = 10
LINE_H = 1.25      # Excalidraw lineHeight
NODE_PAD_X = 32.0  # horizontal padding inside a node
NODE_PAD_Y = 28.0  # vertical padding inside a node
DIAMOND_FIT = 2.0  # diamonds need bbox ≈ 2× text so it fits the inscribed area
DIAMOND_MAX_W = 520.0  # cap so verbose decisions never dominate the layout
DIAMOND_MAX_H = 300.0
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


def with_detail_level(graph: FlowGraph, level: str) -> FlowGraph:
    """Return a copy of *graph* with details truncated per *level*.

    - high: unchanged
    - med:  detail truncated to first line
    - low:  detail removed
    """
    if level == "high":
        return graph
    filtered = FlowGraph(title=graph.title)
    for n in graph.nodes:
        if level == "low":
            detail = ""
        elif level == "med":
            detail = n.detail.split("\n")[0] if n.detail else ""
        else:
            detail = n.detail
        filtered.add_node(Node(id=n.id, label=n.label, detail=detail,
                               node_type=n.node_type, line=n.line, phase=n.phase,
                               diff_status=n.diff_status))
    for e in graph.edges:
        filtered.add_edge(Edge(source=e.source, target=e.target, label=e.label,
                               style=e.style, diff_status=e.diff_status))
    return filtered


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
        w = min(
            max(min_w, lw * DIAMOND_FIT + NODE_PAD_X, dw * DIAMOND_FIT),
            DIAMOND_MAX_W,
        )
        h = min(max(min_h, inner_h * DIAMOND_FIT + NODE_PAD_Y), DIAMOND_MAX_H)
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
class LaneBox:
    """A vertical swimlane background rectangle."""
    lane_id: str
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
    lane_boxes: list[LaneBox] = field(default_factory=list)
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

# ── Swimlane layout constants ────────────────────────────────────────

LANE_WIDTH = 380
LANE_GAP = 40
LANE_PAD = 30
LANE_TOP = 80

SWIMLANE_STYLES: dict[str, dict[str, str]] = {
    "orchestrator": {"background": "#f0fdf4", "stroke": "#86efac", "label": "ORCHESTRATOR"},
    "planner":      {"background": "#e0f2fe", "stroke": "#7dd3fc", "label": "PLANNER"},
    "developer":    {"background": "#ede9fe", "stroke": "#c4b5fd", "label": "DEVELOPER"},
    "debugger":     {"background": "#fce7f3", "stroke": "#f9a8d4", "label": "DEBUGGER"},
    "designer":     {"background": "#ffedd5", "stroke": "#fdba74", "label": "DESIGNER"},
    "tools":        {"background": "#f0fdfa", "stroke": "#5eead4", "label": "TOOLS"},
    "evolution":    {"background": "#fff7ed", "stroke": "#fdba74", "label": "MEMORY"},
    "teardown":     {"background": "#fef2f2", "stroke": "#fca5a5", "label": "TEARDOWN"},
}

SWIMLANE_STYLES_DARK: dict[str, dict[str, str]] = {
    "orchestrator": {"background": "#052e16", "stroke": "#22c55e", "label": "ORCHESTRATOR"},
    "planner":      {"background": "#0c4a6e", "stroke": "#38bdf8", "label": "PLANNER"},
    "developer":    {"background": "#2e1065", "stroke": "#8b5cf6", "label": "DEVELOPER"},
    "debugger":     {"background": "#500724", "stroke": "#db2777", "label": "DEBUGGER"},
    "designer":     {"background": "#431407", "stroke": "#f97316", "label": "DESIGNER"},
    "tools":        {"background": "#042f2e", "stroke": "#14b8a6", "label": "TOOLS"},
    "evolution":    {"background": "#431407", "stroke": "#f97316", "label": "MEMORY"},
    "teardown":     {"background": "#450a0a", "stroke": "#ef4444", "label": "TEARDOWN"},
}

LANE_ORDER = ["orchestrator", "planner", "developer", "debugger", "designer", "tools", "evolution", "teardown"]

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
        "swimlane_styles": SWIMLANE_STYLES,
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
        "swimlane_styles": SWIMLANE_STYLES_DARK,
    },
    "pastel": {
        "arrow": "#6b7280",
        "feedback_arrow": "#8b5cf6",
        "text": "#374151",
        "detail_text": "#6b7280",
        "title": "#1f2937",
        "phase_label": "#4b5563",
        "canvas_background": "#fffbeb",
        "node_colors": {
            NodeType.START:      {"background": "#f0fdf4", "stroke": "#86efac"},
            NodeType.END:        {"background": "#fef2f2", "stroke": "#fca5a5"},
            NodeType.PROCESS:    {"background": "#f5f3ff", "stroke": "#c4b5fd"},
            NodeType.DECISION:   {"background": "#fefce8", "stroke": "#fde68a"},
            NodeType.SUBPROCESS: {"background": "#eff6ff", "stroke": "#93c5fd"},
            NodeType.TOOL:       {"background": "#f0fdfa", "stroke": "#5eead4"},
            NodeType.LOOP:       {"background": "#fdf2f8", "stroke": "#f9a8d4"},
            NodeType.EVOLUTION:  {"background": "#fff7ed", "stroke": "#fdba74"},
        },
        "category_styles": CATEGORY_STYLES,
        "phase_defs": PHASE_DEFS,
        "swimlane_styles": SWIMLANE_STYLES,
    },
    "neon": {
        "arrow": "#00ff88",
        "feedback_arrow": "#ff00ff",
        "text": "#e0e0e0",
        "detail_text": "#a0a0a0",
        "title": "#ffffff",
        "phase_label": "#00ff88",
        "canvas_background": "#0a0a0a",
        "node_colors": {
            NodeType.START:      {"background": "#000000", "stroke": "#00ff88"},
            NodeType.END:        {"background": "#000000", "stroke": "#ff0055"},
            NodeType.PROCESS:    {"background": "#000000", "stroke": "#8b5cf6"},
            NodeType.DECISION:   {"background": "#000000", "stroke": "#facc15"},
            NodeType.SUBPROCESS: {"background": "#000000", "stroke": "#00ffff"},
            NodeType.TOOL:       {"background": "#000000", "stroke": "#00ff88"},
            NodeType.LOOP:       {"background": "#000000", "stroke": "#ff00ff"},
            NodeType.EVOLUTION:  {"background": "#000000", "stroke": "#ff8800"},
        },
        "category_styles": {
            "init":     {"background": "#001a0f", "stroke": "#00ff88", "label": "INIT"},
            "loop":     {"background": "#1a001a", "stroke": "#ff00ff", "label": "MAIN LOOP"},
            "dispatch": {"background": "#0f0a1a", "stroke": "#8b5cf6", "label": "DISPATCH & EVALUATE"},
            "tools":    {"background": "#001a1a", "stroke": "#00ffff", "label": "TOOLS"},
            "evolution":{"background": "#1a0f00", "stroke": "#ff8800", "label": "SELF-EVOLUTION"},
            "teardown": {"background": "#1a0005", "stroke": "#ff0055", "label": "TEARDOWN"},
        },
        "phase_defs": {
            1: {"label": "FASE 1 · PREPARACIÓN", "background": "#0a0a0a", "stroke": "#00ff88"},
            2: {"label": "FASE 2 · LOOP DE EVOLUCIÓN (H1…Hn)", "background": "#0a0a0a", "stroke": "#ff00ff"},
            3: {"label": "FASE 3 · CIERRE", "background": "#0a0a0a", "stroke": "#00ff88"},
        },
        "swimlane_styles": {
            "orchestrator": {"background": "#001a0f", "stroke": "#00ff88", "label": "ORCHESTRATOR"},
            "planner":      {"background": "#001a1a", "stroke": "#00ffff", "label": "PLANNER"},
            "developer":    {"background": "#0f0a1a", "stroke": "#8b5cf6", "label": "DEVELOPER"},
            "debugger":     {"background": "#1a001a", "stroke": "#ff00ff", "label": "DEBUGGER"},
            "designer":     {"background": "#1a0f00", "stroke": "#ff8800", "label": "DESIGNER"},
            "tools":        {"background": "#001a1a", "stroke": "#00ffff", "label": "TOOLS"},
            "evolution":    {"background": "#1a0f00", "stroke": "#ff8800", "label": "MEMORY"},
            "teardown":     {"background": "#1a0005", "stroke": "#ff0055", "label": "TEARDOWN"},
        },
    },
    "mono": {
        "arrow": "#475569",
        "feedback_arrow": "#64748b",
        "text": "#1e293b",
        "detail_text": "#64748b",
        "title": "#0f172a",
        "phase_label": "#334155",
        "canvas_background": "#ffffff",
        "node_colors": {
            NodeType.START:      {"background": "#f8fafc", "stroke": "#334155"},
            NodeType.END:        {"background": "#f1f5f9", "stroke": "#475569"},
            NodeType.PROCESS:    {"background": "#f8fafc", "stroke": "#64748b"},
            NodeType.DECISION:   {"background": "#f1f5f9", "stroke": "#475569"},
            NodeType.SUBPROCESS: {"background": "#f8fafc", "stroke": "#475569"},
            NodeType.TOOL:       {"background": "#f1f5f9", "stroke": "#334155"},
            NodeType.LOOP:       {"background": "#f8fafc", "stroke": "#64748b"},
            NodeType.EVOLUTION:  {"background": "#f1f5f9", "stroke": "#475569"},
        },
        "category_styles": {
            "init":     {"background": "#f8fafc", "stroke": "#cbd5e1", "label": "INIT"},
            "loop":     {"background": "#f1f5f9", "stroke": "#94a3b8", "label": "MAIN LOOP"},
            "dispatch": {"background": "#f8fafc", "stroke": "#94a3b8", "label": "DISPATCH & EVALUATE"},
            "tools":    {"background": "#f1f5f9", "stroke": "#cbd5e1", "label": "TOOLS"},
            "evolution":{"background": "#f8fafc", "stroke": "#cbd5e1", "label": "SELF-EVOLUTION"},
            "teardown": {"background": "#f1f5f9", "stroke": "#cbd5e1", "label": "TEARDOWN"},
        },
        "phase_defs": {
            1: {"label": "FASE 1 · PREPARACIÓN", "background": "#f8fafc", "stroke": "#94a3b8"},
            2: {"label": "FASE 2 · LOOP DE EVOLUCIÓN (H1…Hn)", "background": "#f1f5f9", "stroke": "#94a3b8"},
            3: {"label": "FASE 3 · CIERRE", "background": "#f8fafc", "stroke": "#94a3b8"},
        },
        "swimlane_styles": {
            "orchestrator": {"background": "#f8fafc", "stroke": "#cbd5e1", "label": "ORCHESTRATOR"},
            "planner":      {"background": "#f1f5f9", "stroke": "#94a3b8", "label": "PLANNER"},
            "developer":    {"background": "#f8fafc", "stroke": "#94a3b8", "label": "DEVELOPER"},
            "debugger":     {"background": "#f1f5f9", "stroke": "#94a3b8", "label": "DEBUGGER"},
            "designer":     {"background": "#f8fafc", "stroke": "#94a3b8", "label": "DESIGNER"},
            "tools":        {"background": "#f1f5f9", "stroke": "#cbd5e1", "label": "TOOLS"},
            "evolution":    {"background": "#f8fafc", "stroke": "#cbd5e1", "label": "MEMORY"},
            "teardown":     {"background": "#f1f5f9", "stroke": "#cbd5e1", "label": "TEARDOWN"},
        },
    },
    "dungeon": {
        "arrow": "#6d5a3e",
        "feedback_arrow": "#3b5bdb",
        "text": "#3b341f",
        "detail_text": "#6b5f45",
        "title": "#3b341f",
        "phase_label": "#4d4430",
        "canvas_background": "#fbf6de",
        "page_background": "#efe6ce",
        "node_colors": {
            NodeType.START:      {"background": "#eaf3df", "stroke": "#5a7d3d"},
            NodeType.END:        {"background": "#f3dcdc", "stroke": "#a05c5c"},
            NodeType.PROCESS:    {"background": "#efe6d5", "stroke": "#8a6d3b"},
            NodeType.DECISION:   {"background": "#fdf3cf", "stroke": "#c2a13a"},
            NodeType.SUBPROCESS: {"background": "#e0e7f3", "stroke": "#5b6fa8"},
            NodeType.TOOL:       {"background": "#dcefe8", "stroke": "#3f826b"},
            NodeType.LOOP:       {"background": "#f4dce8", "stroke": "#a85b8a"},
            NodeType.EVOLUTION:  {"background": "#f5e0cd", "stroke": "#b06b2d"},
        },
        "category_styles": {
            "init":     {"background": "#f0ead6", "stroke": "#a8b48a", "label": "INIT"},
            "loop":     {"background": "#f6e6ee", "stroke": "#c48aa8", "label": "MAIN LOOP"},
            "dispatch": {"background": "#efe6d5", "stroke": "#c9b26a", "label": "DISPATCH & EVALUATE"},
            "tools":    {"background": "#e6efea", "stroke": "#7cb0a0", "label": "TOOLS"},
            "evolution":{"background": "#f5e0cd", "stroke": "#d9a06b", "label": "SELF-EVOLUTION"},
            "teardown": {"background": "#f5dddd", "stroke": "#d99a9a", "label": "TEARDOWN"},
        },
        "phase_defs": {
            1: {"label": "FASE 1 · PREPARACIÓN", "background": "#f0ead6", "stroke": "#b8a880"},
            2: {"label": "FASE 2 · LOOP DE EVOLUCIÓN (H1…Hn)", "background": "#fbf2d9", "stroke": "#b8a880"},
            3: {"label": "FASE 3 · CIERRE", "background": "#eaf0dd", "stroke": "#b8a880"},
        },
        "swimlane_styles": {
            "orchestrator": {"background": "#f0ead6", "stroke": "#a8b48a", "label": "ORCHESTRATOR"},
            "planner":      {"background": "#e6e0ed", "stroke": "#a598c4", "label": "PLANNER"},
            "developer":    {"background": "#efe6d5", "stroke": "#c9b26a", "label": "DEVELOPER"},
            "debugger":     {"background": "#f6e6ee", "stroke": "#c48aa8", "label": "DEBUGGER"},
            "designer":     {"background": "#f5e0cd", "stroke": "#d9a06b", "label": "DESIGNER"},
            "tools":        {"background": "#e6efea", "stroke": "#7cb0a0", "label": "TOOLS"},
            "evolution":    {"background": "#f5e0cd", "stroke": "#d9a06b", "label": "MEMORY"},
            "teardown":     {"background": "#f5dddd", "stroke": "#d99a9a", "label": "TEARDOWN"},
        },
    },
    "violet": {
        "arrow": "#6b5e8f",
        "feedback_arrow": "#7c3aed",
        "text": "#2b1d3d",
        "detail_text": "#6d5f87",
        "title": "#2b1d3d",
        "phase_label": "#4a3a63",
        "canvas_background": "#faf7ff",
        "page_background": "#e9e0f5",
        "node_colors": {
            NodeType.START:      {"background": "#eaf7ec", "stroke": "#4a9d5a"},
            NodeType.END:        {"background": "#f9e6ea", "stroke": "#b3526a"},
            NodeType.PROCESS:    {"background": "#efe9fb", "stroke": "#7e57c2"},
            NodeType.DECISION:   {"background": "#fdf3e0", "stroke": "#d4a017"},
            NodeType.SUBPROCESS: {"background": "#e3ecfa", "stroke": "#5b8def"},
            NodeType.TOOL:       {"background": "#e6f2f6", "stroke": "#3f9db5"},
            NodeType.LOOP:       {"background": "#f9e6f3", "stroke": "#c04f9e"},
            NodeType.EVOLUTION:  {"background": "#fbeae6", "stroke": "#cc6e4e"},
        },
        "category_styles": {
            "init":     {"background": "#eaf7ec", "stroke": "#a8d3b2", "label": "INIT"},
            "loop":     {"background": "#f9e6f3", "stroke": "#d69ac3", "label": "MAIN LOOP"},
            "dispatch": {"background": "#efe9fb", "stroke": "#bb9fe8", "label": "DISPATCH & EVALUATE"},
            "tools":    {"background": "#e6f2f6", "stroke": "#9ccfdc", "label": "TOOLS"},
            "evolution":{"background": "#fbeae6", "stroke": "#e0a291", "label": "SELF-EVOLUTION"},
            "teardown": {"background": "#f9e6ea", "stroke": "#e0a3b2", "label": "TEARDOWN"},
        },
        "phase_defs": {
            1: {"label": "FASE 1 · PREPARACIÓN", "background": "#f3eefe", "stroke": "#b9a6e0"},
            2: {"label": "FASE 2 · LOOP DE EVOLUCIÓN (H1…Hn)", "background": "#f6ecfb", "stroke": "#b9a6e0"},
            3: {"label": "FASE 3 · CIERRE", "background": "#eef7f1", "stroke": "#b9a6e0"},
        },
        "swimlane_styles": {
            "orchestrator": {"background": "#eaf7ec", "stroke": "#a8d3b2", "label": "ORCHESTRATOR"},
            "planner":      {"background": "#e6ecfa", "stroke": "#9cb8e8", "label": "PLANNER"},
            "developer":    {"background": "#efe9fb", "stroke": "#bb9fe8", "label": "DEVELOPER"},
            "debugger":     {"background": "#f9e6f3", "stroke": "#d69ac3", "label": "DEBUGGER"},
            "designer":     {"background": "#fbeae6", "stroke": "#e0a291", "label": "DESIGNER"},
            "tools":        {"background": "#e6f2f6", "stroke": "#9ccfdc", "label": "TOOLS"},
            "evolution":    {"background": "#fbeae6", "stroke": "#e0a291", "label": "MEMORY"},
            "teardown":     {"background": "#f9e6ea", "stroke": "#e0a3b2", "label": "TEARDOWN"},
        },
    },
    "sandy": {
        "arrow": "#7d6b5a",
        "feedback_arrow": "#c07a1c",
        "text": "#3d2f23",
        "detail_text": "#8a6f55",
        "title": "#3d2f23",
        "phase_label": "#5c4a35",
        "canvas_background": "#f9f1e7",
        "page_background": "#efe2ce",
        "node_colors": {
            NodeType.START:      {"background": "#e9f1df", "stroke": "#6d8f4e"},
            NodeType.END:        {"background": "#f3ded8", "stroke": "#b36a5a"},
            NodeType.PROCESS:    {"background": "#f0e4d0", "stroke": "#a8893f"},
            NodeType.DECISION:   {"background": "#f9ecc8", "stroke": "#d0a63c"},
            NodeType.SUBPROCESS: {"background": "#e0e7e9", "stroke": "#5f8aa0"},
            NodeType.TOOL:       {"background": "#e5eee3", "stroke": "#6f9b67"},
            NodeType.LOOP:       {"background": "#f3e0e2", "stroke": "#b4677b"},
            NodeType.EVOLUTION:  {"background": "#f6e2cd", "stroke": "#c47a2e"},
        },
        "category_styles": {
            "init":     {"background": "#e9f1df", "stroke": "#b9cfa0", "label": "INIT"},
            "loop":     {"background": "#f3e0e2", "stroke": "#d2a3a7", "label": "MAIN LOOP"},
            "dispatch": {"background": "#f0e4d0", "stroke": "#d0bc8a", "label": "DISPATCH & EVALUATE"},
            "tools":    {"background": "#e5eee3", "stroke": "#a3c49a", "label": "TOOLS"},
            "evolution":{"background": "#f6e2cd", "stroke": "#e0b48c", "label": "SELF-EVOLUTION"},
            "teardown": {"background": "#f3ded8", "stroke": "#dca99b", "label": "TEARDOWN"},
        },
        "phase_defs": {
            1: {"label": "FASE 1 · PREPARACIÓN", "background": "#f3e8d4", "stroke": "#cbb194"},
            2: {"label": "FASE 2 · LOOP DE EVOLUCIÓN (H1…Hn)", "background": "#fbf0da", "stroke": "#cbb194"},
            3: {"label": "FASE 3 · CIERRE", "background": "#ecf0e2", "stroke": "#cbb194"},
        },
        "swimlane_styles": {
            "orchestrator": {"background": "#e9f1df", "stroke": "#b9cfa0", "label": "ORCHESTRATOR"},
            "planner":      {"background": "#e4e9e6", "stroke": "#a3bdb0", "label": "PLANNER"},
            "developer":    {"background": "#f0e4d0", "stroke": "#d0bc8a", "label": "DEVELOPER"},
            "debugger":     {"background": "#f3e0e2", "stroke": "#d2a3a7", "label": "DEBUGGER"},
            "designer":     {"background": "#f6e2cd", "stroke": "#e0b48c", "label": "DESIGNER"},
            "tools":        {"background": "#e5eee3", "stroke": "#a3c49a", "label": "TOOLS"},
            "evolution":    {"background": "#f6e2cd", "stroke": "#e0b48c", "label": "MEMORY"},
            "teardown":     {"background": "#f3ded8", "stroke": "#dca99b", "label": "TEARDOWN"},
        },
    },
    "ocean": {
        "arrow": "#4a6b7a",
        "feedback_arrow": "#0ea5e9",
        "text": "#12303a",
        "detail_text": "#5d7d8a",
        "title": "#12303a",
        "phase_label": "#2f5462",
        "canvas_background": "#f0fafb",
        "page_background": "#dceef1",
        "node_colors": {
            NodeType.START:      {"background": "#e3f2e5", "stroke": "#3d8f5f"},
            NodeType.END:        {"background": "#fce4ea", "stroke": "#cf5d7b"},
            NodeType.PROCESS:    {"background": "#e2ecfb", "stroke": "#4678c8"},
            NodeType.DECISION:   {"background": "#fbf0d8", "stroke": "#cf9c1e"},
            NodeType.SUBPROCESS: {"background": "#def2f8", "stroke": "#3b9cc0"},
            NodeType.TOOL:       {"background": "#dcf3ea", "stroke": "#2f9b7a"},
            NodeType.LOOP:       {"background": "#fadbed", "stroke": "#c04d8f"},
            NodeType.EVOLUTION:  {"background": "#fde8d8", "stroke": "#cc7430"},
        },
        "category_styles": {
            "init":     {"background": "#e3f2e5", "stroke": "#a5cfa9", "label": "INIT"},
            "loop":     {"background": "#fadbed", "stroke": "#d294b8", "label": "MAIN LOOP"},
            "dispatch": {"background": "#e2ecfb", "stroke": "#9cb7e8", "label": "DISPATCH & EVALUATE"},
            "tools":    {"background": "#dcf3ea", "stroke": "#8fc9b0", "label": "TOOLS"},
            "evolution":{"background": "#fde8d8", "stroke": "#dfae8c", "label": "SELF-EVOLUTION"},
            "teardown": {"background": "#fce4ea", "stroke": "#dc9db0", "label": "TEARDOWN"},
        },
        "phase_defs": {
            1: {"label": "FASE 1 · PREPARACIÓN", "background": "#e5f2f4", "stroke": "#9cc5cf"},
            2: {"label": "FASE 2 · LOOP DE EVOLUCIÓN (H1…Hn)", "background": "#ecf9fa", "stroke": "#9cc5cf"},
            3: {"label": "FASE 3 · CIERRE", "background": "#e9f0e2", "stroke": "#9cc5cf"},
        },
        "swimlane_styles": {
            "orchestrator": {"background": "#e3f2e5", "stroke": "#a5cfa9", "label": "ORCHESTRATOR"},
            "planner":      {"background": "#e0eef8", "stroke": "#92b8d8", "label": "PLANNER"},
            "developer":    {"background": "#e2ecfb", "stroke": "#9cb7e8", "label": "DEVELOPER"},
            "debugger":     {"background": "#fadbed", "stroke": "#d294b8", "label": "DEBUGGER"},
            "designer":     {"background": "#fde8d8", "stroke": "#dfae8c", "label": "DESIGNER"},
            "tools":        {"background": "#dcf3ea", "stroke": "#8fc9b0", "label": "TOOLS"},
            "evolution":    {"background": "#fde8d8", "stroke": "#dfae8c", "label": "MEMORY"},
            "teardown":     {"background": "#fce4ea", "stroke": "#dc9db0", "label": "TEARDOWN"},
        },
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

# Edge semantic colors (overrides arrow color when label matches)
EDGE_SEMANTIC_COLORS: dict[str, str] = {
    "YES": "#16a34a",
    "NO": "#dc2626",
    "loop": "#2563eb",
    "dispatch": "#7c3aed",
}


def _assign_lane(node: Node) -> str:
    """Heuristic lane assignment based on node content."""
    label = node.label.lower()
    nid = node.id.lower()
    combined = f"{label} {nid}"
    if "planner" in combined:
        return "planner"
    if "developer" in combined or "coder" in combined:
        return "developer"
    if "debugger" in combined or "repair" in combined:
        return "debugger"
    if "designer" in combined or "ui_" in combined:
        return "designer"
    if node.node_type == NodeType.TOOL:
        return "tools"
    if node.node_type == NodeType.EVOLUTION:
        return "evolution"
    if node.node_type == NodeType.SUBPROCESS:
        return "tools"
    if node.node_type == NodeType.START:
        return "orchestrator"
    if node.node_type == NodeType.END:
        return "teardown"
    return "orchestrator"


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


def swimlane_layout(graph: FlowGraph, **kwargs) -> LayoutResult:
    """Vertical swimlane layout: one column per actor/lane, flow top→bottom.

    Lanes are detected heuristically (orchestrator / planner / developer /
    debugger / designer / tools / evolution). Nodes are placed in their
    lane in topological order. Edges between lanes become horizontal.
    """
    if not graph.nodes:
        return LayoutResult([], 0, 0)

    # 1. Assign each node to a lane
    lane_groups: dict[str, list[str]] = defaultdict(list)
    for node in graph.nodes:
        lane = _assign_lane(node)
        lane_groups[lane].append(node.id)

    # Order lanes by LANE_ORDER, extras last
    ordered_lanes = sorted(
        lane_groups.keys(),
        key=lambda x: LANE_ORDER.index(x) if x in LANE_ORDER else 999,
    )

    # 2. Compute lane X positions (adaptive width per lane)
    lane_x: dict[str, float] = {}
    lane_widths: dict[str, float] = {}
    x_cursor = 80.0
    for lane in ordered_lanes:
        max_w = max(
            (node_size(graph.get_node(nid))[0] for nid in lane_groups[lane] if graph.get_node(nid)),
            default=LANE_WIDTH,
        )
        lane_width = max(LANE_WIDTH, max_w + 2 * LANE_PAD)
        lane_x[lane] = x_cursor
        lane_widths[lane] = lane_width
        x_cursor += lane_width + LANE_GAP

    # 3. Place nodes lane by lane in topological order
    positioned: list[PositionedNode] = []
    y_cursors: dict[str, float] = {lane: float(LANE_TOP) for lane in ordered_lanes}
    topo = _topological_sort(graph)
    for nid in topo:
        node = graph.get_node(nid)
        if node is None:
            continue
        lane = _assign_lane(node)
        if lane not in lane_x:
            lane = ordered_lanes[0]
        w, h = node_size(node)
        x = lane_x[lane] + (lane_widths[lane] - w) / 2
        y = y_cursors[lane]
        positioned.append(PositionedNode(node=node, x=x, y=y, width=w, height=h,
                                         group_id=lane, phase=0))
        y_cursors[lane] += h + V_GAP

    # Any nodes not in topo (isolated) — already handled via topo includes all
    # 4. Compute lane boxes
    pal = get_theme(kwargs.get("theme", "light"))
    lane_styles = pal.get("swimlane_styles", SWIMLANE_STYLES)
    lane_boxes: list[LaneBox] = []
    for lane in ordered_lanes:
        nodes_in_lane = [p for p in positioned if p.group_id == lane]
        if not nodes_in_lane:
            continue
        style = lane_styles.get(lane, {"background": "#f8f9fa", "stroke": "#868e96", "label": lane.upper()})
        min_x = min(p.x for p in nodes_in_lane) - LANE_PAD
        min_y = min(p.y for p in nodes_in_lane) - LANE_PAD
        max_x = max(p.x + p.width for p in nodes_in_lane) + LANE_PAD
        max_y = max(p.y + p.height for p in nodes_in_lane) + LANE_PAD
        lane_boxes.append(LaneBox(
            lane_id=lane, label=style["label"],
            x=min_x, y=min_y, width=max_x - min_x, height=max_y - min_y,
            background=style["background"], stroke=style["stroke"],
        ))

    # 5. Feedback arrows (upward edges)
    feedback = _identify_feedback_arrows(graph, positioned, color=pal["feedback_arrow"])

    max_x = max((p.x + p.width for p in positioned), default=0)
    max_y = max((p.y + p.height for p in positioned), default=0)
    return LayoutResult(
        positioned=positioned,
        width=max_x + 80,
        height=max_y + 80,
        lane_boxes=lane_boxes,
        feedback_arrows=feedback,
    )


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
        label = defs["label"]
        lw, _ = measure_text(label, 22)
        min_x = min(n.x for n in nodes) - PHASE_PAD
        min_y = min(n.y for n in nodes) - PHASE_PAD
        max_x = max(n.x + n.width for n in nodes) + PHASE_PAD
        # Ensure box is wide enough for its label
        max_x = max(max_x, min_x + lw + 60)
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


def phased_horizontal_layout(graph: FlowGraph, **kwargs) -> LayoutResult:
    """Horizontal phased layout: FASE 1→2→3 flow left→right as columns.

    Within each phase column, nodes flow top→bottom (main center, tools on the
    right, evolution on the left). Mirrors ``phased_layout`` with the axes
    swapped so wide phase-spanning tools stay legible.
    """
    if not graph.nodes:
        return LayoutResult([], 0, 0)

    phase_groups = _phase_groups(graph)
    for phase in phase_groups:
        phase_groups[phase] = _topo_order_filtered(graph, phase_groups[phase])

    positioned: list[PositionedNode] = []
    x_cursor = float(PHASE_TOP)
    col_gap = 140.0
    inner_gap = PHASE_H_GAP
    col_top = 90.0
    pal = get_theme(kwargs.get("theme", "light"))
    phase_defs = pal["phase_defs"]

    for phase in [1, 2, 3]:
        node_ids = phase_groups[phase]
        if not node_ids:
            continue

        main_nodes, side_nodes, evo_nodes = _classify_phase_nodes(graph, node_ids)

        def _column_metrics(nids: list[str]) -> tuple[float, float]:
            w = 0.0
            h = 0.0
            for nid in nids:
                node = graph.get_node(nid)
                if node is None:
                    continue
                nw, nh = node_size(node)
                w = max(w, nw)
                h += nh
            if nids:
                h += PHASE_V_GAP * (len(nids) - 1)
            return w, h

        main_w, main_h = _column_metrics(main_nodes)
        side_w, side_h = _column_metrics(side_nodes)
        evo_w, evo_h = _column_metrics(evo_nodes)

        col_h = max(main_h, side_h, evo_h, 60.0)

        evo_x = x_cursor
        main_x = evo_x + (evo_w + inner_gap if evo_nodes else 0.0)
        tools_x = main_x + (main_w + inner_gap if main_nodes else 0.0)

        def _place(
            nids: list[str], col_x: float, col_w: float, group: str,
            col_h: float, phase: int,
        ) -> None:
            y = col_top + (col_h - col_w) / 2
            for nid in nids:
                node = graph.get_node(nid)
                if node is None:
                    continue
                w, h = node_size(node)
                positioned.append(PositionedNode(
                    node=node, x=col_x + (col_w - w) / 2, y=y,
                    width=w, height=h, group_id=group, phase=phase,
                ))
                y += h + PHASE_V_GAP

        _place(main_nodes, main_x, main_w, "main", col_h, phase)
        _place(side_nodes, tools_x, side_w, "tools", col_h, phase)
        _place(evo_nodes, evo_x, evo_w, "evolution", col_h, phase)

        xs = [evo_x] if evo_nodes else []
        if main_nodes:
            xs += [main_x, main_x + main_w]
        if side_nodes:
            xs += [tools_x, tools_x + side_w]
        if evo_nodes:
            xs.append(evo_x + evo_w)
        label_w, _ = measure_text(phase_defs[phase]["label"], 22)
        reserve = max((max(xs) - min(xs)) if xs else 0.0, label_w + 60)
        x_cursor = (min(xs) if xs else x_cursor) + reserve + col_gap

    # Compute phase boxes
    phase_boxes = _compute_phase_boxes(positioned, phase_defs)

    max_x = max((p.x + p.width for p in positioned), default=0)
    max_y = max((p.y + p.height for p in positioned), default=0)

    return LayoutResult(
        positioned=positioned,
        width=max_x + 80,
        height=max_y + 80,
        phase_boxes=phase_boxes,
    )


def _radial_center(graph: FlowGraph) -> str:
    """Pick the central node: first START, else the node with max total degree."""
    for node in graph.nodes:
        if node.node_type == NodeType.START:
            return node.id
    deg: dict[str, int] = defaultdict(int)
    for e in graph.edges:
        deg[e.source] += 1
        deg[e.target] += 1
    if graph.nodes:
        return max((n.id for n in graph.nodes), key=lambda nid: deg.get(nid, 0))
    return ""


def _radial_levels(graph: FlowGraph, center_id: str) -> dict[str, int]:
    """BFS distance (undirected) from the center, used for concentric rings."""
    adj: dict[str, list[str]] = defaultdict(list)
    for e in graph.edges:
        adj[e.source].append(e.target)
        adj[e.target].append(e.source)

    levels: dict[str, int] = {}
    queue = [center_id]
    levels[center_id] = 0
    while queue:
        cur = queue.pop(0)
        for nb in adj.get(cur, []):
            if nb not in levels:
                levels[nb] = levels[cur] + 1
                queue.append(nb)
    for node in graph.nodes:
        if node.id not in levels:
            levels[node.id] = 1
    return levels


def radial_layout(graph: FlowGraph, **kwargs) -> LayoutResult:
    """Circular layout: central agent node, others on concentric rings by BFS
    distance. Distances and angles are computed for the exported geometry
    (Excalidraw / SVG); Mermaid ignores the positions and lays out itself.
    """
    if not graph.nodes:
        return LayoutResult([], 0, 0)

    center_id = _radial_center(graph)
    levels = _radial_levels(graph, center_id)

    topo = _topological_sort(graph)
    by_level: dict[int, list[str]] = {}
    for nid, lvl in levels.items():
        by_level.setdefault(lvl, []).append(nid)
    for lvl, nids in by_level.items():
        lset = set(nids)
        by_level[lvl] = [nid for nid in topo if nid in lset]

    origin_x = 500.0
    origin_y = 400.0
    ring_gap = 160.0
    max_level = max(levels.values()) or 1

    positioned: list[PositionedNode] = []
    for level in range(max_level + 1):
        nids = by_level.get(level, [])
        if not nids:
            continue
        radius = ring_gap * level
        count = len(nids)
        for i, nid in enumerate(nids):
            node = graph.get_node(nid)
            if node is None:
                continue
            w, h = node_size(node)
            angle = 2 * math.pi * i / count - math.pi / 2
            x = origin_x + radius * math.cos(angle) - w / 2
            y = origin_y + radius * math.sin(angle) - h / 2
            positioned.append(PositionedNode(
                node=node, x=x, y=y, width=w, height=h,
                group_id=f"ring{level}", phase=1,
            ))

    min_x = min((p.x for p in positioned), default=0)
    min_y = min((p.y for p in positioned), default=0)
    max_x = max((p.x + p.width for p in positioned), default=0)
    max_y = max((p.y + p.height for p in positioned), default=0)

    # Shift so the diagram starts at (margin, margin)
    margin = 60.0
    for p in positioned:
        p.x += margin - min_x
        p.y += margin - min_y

    return LayoutResult(
        positioned=positioned,
        width=max_x - min_x + margin * 2,
        height=max_y - min_y + margin * 2,
    )
