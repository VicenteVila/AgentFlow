"""Render a FlowGraph as Graphviz DOT.

The output can be piped to ``dot -Tsvg`` / ``dot -Tpng`` for conversion.

Diff status is encoded via fillcolor/stroke; edge semantics via color.
"""

from __future__ import annotations

from pathlib import Path

from agentflow.layouts import EDGE_SEMANTIC_COLORS, get_theme, with_detail_level
from agentflow.models import FlowGraph, NodeType

_DOT_SHAPES = {
    NodeType.START: "ellipse",
    NodeType.END: "ellipse",
    NodeType.DECISION: "diamond",
    NodeType.PROCESS: "box",
    NodeType.SUBPROCESS: "box",
    NodeType.TOOL: "box",
    NodeType.LOOP: "box",
    NodeType.EVOLUTION: "box",
}

_DOT_DIFF_FILL = {
    "added": "#a7f3d0",
    "removed": "#fecaca",
    "changed": "#fde68a",
}
_DOT_DIFF_STROKE = {
    "added": "#065f46",
    "removed": "#991b1b",
    "changed": "#92400e",
}

# Light theme node colors (subset, for DOT without full theme handling)
_DOT_NODE_COLORS = {
    NodeType.START: ("#dcfce7", "#16a34a"),
    NodeType.END: ("#fee2e2", "#dc2626"),
    NodeType.PROCESS: ("#ede9fe", "#7c3aed"),
    NodeType.DECISION: ("#fef9c3", "#ca8a04"),
    NodeType.SUBPROCESS: ("#dbeafe", "#2563eb"),
    NodeType.TOOL: ("#ccfbf1", "#0d9488"),
    NodeType.LOOP: ("#fce7f3", "#db2777"),
    NodeType.EVOLUTION: ("#ffedd5", "#ea580c"),
}


def _dot_escape(text: str) -> str:
    return text.replace('"', '\\"').replace("\n", "\\n")


def _node_attrs(node, detail: str, pal: dict | None = None) -> str:
    # Label: label + detail if present
    label = node.label
    if node.detail:
        detail = node.detail.replace("\n", "\\n")
        label = f"{label}\\n{detail}"
    label = _dot_escape(label)
    shape = _DOT_SHAPES.get(node.node_type, "box")
    if node.diff_status in _DOT_DIFF_FILL:
        fill = _DOT_DIFF_FILL[node.diff_status]
        stroke = _DOT_DIFF_STROKE[node.diff_status]
        style = "filled,dashed" if node.diff_status == "removed" else "filled"
        return f'label="{label}", shape={shape}, style="{style}", fillcolor="{fill}", color="{stroke}"'
    if pal is not None:
        colors = pal["node_colors"].get(node.node_type, _DOT_NODE_COLORS.get(node.node_type, ("#ffffff", "#000000")))
        # pal colors are dicts, convert to tuple
        if isinstance(colors, dict):
            fill, stroke = colors["background"], colors["stroke"]
        else:
            fill, stroke = colors
    else:
        fill, stroke = _DOT_NODE_COLORS.get(node.node_type, ("#ffffff", "#000000"))
    style = "filled"
    if node.node_type == NodeType.EVOLUTION:
        style = "filled,dashed"
    extra = ""
    if shape == "box":
        extra = ', rounding=0.2'
    return f'label="{label}", shape={shape}, style="{style}", fillcolor="{fill}", color="{stroke}"{extra}'


def _edge_attrs(label: str, diff_status: str, style: str) -> str:
    attrs: list[str] = []
    if label:
        attrs.append(f'label="{_dot_escape(label)}"')
    # Color by diff or semantic
    if diff_status in ("added", "removed", "changed"):
        color = _DOT_DIFF_STROKE[diff_status]
        attrs.append(f'color="{color}", fontcolor="{color}"')
        if diff_status == "removed":
            attrs.append('style="dashed"')
    elif label in EDGE_SEMANTIC_COLORS:
        color = EDGE_SEMANTIC_COLORS[label]
        attrs.append(f'color="{color}", fontcolor="{color}"')
        if label == "loop":
            attrs.append('style="dashed"')
    elif style == "dashed":
        attrs.append('style="dashed"')
    return ", ".join(attrs)


def to_dot(
    graph: FlowGraph,
    detail: str = "high",
    _layout: str = "hierarchical",
    _theme: str = "light",
    theme: str | None = None,
) -> str:
    """Render *graph* as DOT language."""
    if detail != "high":
        graph = with_detail_level(graph, detail)
    # Theme handling: prefer explicit theme param, fallback to _theme for backward compat
    eff_theme = theme or _theme
    try:
        pal = get_theme(eff_theme)
        dot_colors = pal["node_colors"]
    except Exception:
        dot_colors = _DOT_NODE_COLORS

    lines: list[str] = []
    title = _dot_escape(graph.title)
    lines.append(f'digraph "{title}" {{')
    lines.append("  rankdir=LR;")
    lines.append('  node [fontname="Helvetica", fontsize=10];')
    lines.append('  edge [fontname="Helvetica", fontsize=9];')
    lines.append("")

    for node in graph.nodes:
        attrs = _node_attrs(node, detail, pal if 'pal' in locals() else None)
        lines.append(f'  "{node.id}" [{attrs}];')

    lines.append("")
    for edge in graph.edges:
        attrs = _edge_attrs(edge.label, edge.diff_status, edge.style)
        attr_str = f" [{attrs}]" if attrs else ""
        lines.append(f'  "{edge.source}" -> "{edge.target}"{attr_str};')

    lines.append("}")
    return "\n".join(lines) + "\n"


def save_dot(
    graph: FlowGraph,
    output_path: str | Path,
    detail: str = "high",
    layout: str = "hierarchical",
    theme: str = "light",
) -> Path:
    """Save DOT rendering to *output_path*."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_dot(graph, detail=detail, _layout=layout, theme=theme), encoding="utf-8")
    return path
