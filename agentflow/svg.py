"""Render a FlowGraph as standalone SVG.

Reuses the layout algorithms and arrow-routing geometry from the
Excalidraw pipeline, producing a self-contained .svg file with no
external dependencies.
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape

from agentflow.geometry import (
    assign_feedback_slots,
    feedback_route,
    node_text_block,
    resolve_edges,
    routed_points,
)
from agentflow.layouts import (
    DETAIL_FONT,
    EDGE_SEMANTIC_COLORS,
    LABEL_FONT,
    PositionedNode,
    get_theme,
    grid_layout,
    hierarchical_layout,
    phased_horizontal_layout,
    phased_layout,
    radial_layout,
    with_detail_level,
)
from agentflow.models import FlowGraph, NodeType

_DIFF_NODE_COLORS = {
    "added": {"background": "#a7f3d0", "stroke": "#065f46"},
    "removed": {"background": "#fecaca", "stroke": "#991b1b"},
    "changed": {"background": "#fef3c7", "stroke": "#92400e"},
}
_DIFF_EDGE_COLORS = {
    "added": "#065f46",
    "removed": "#991b1b",
    "changed": "#92400e",
}

FONT_STACK = "'Comic Shanns','Virgil','Segoe UI',system-ui,sans-serif"


def _fmt(v: float) -> str:
    """Compact number formatting for SVG coordinates."""
    return f"{v:.1f}".rstrip("0").rstrip(".")


def _poly_points(points: list[list[float]], ox: float, oy: float) -> str:
    return " ".join(f"{_fmt(ox + px)},{_fmt(oy + py)}" for px, py in points)


def _shape_svg(pos: PositionedNode, pal: dict) -> str:
    """SVG shape for a node, without its text."""
    diff = pos.node.diff_status
    if diff in _DIFF_NODE_COLORS:
        colors = _DIFF_NODE_COLORS[diff]
    else:
        colors = pal["node_colors"].get(
            pos.node.node_type, {"background": "#e9ecef", "stroke": "#495057"}
        )
    fill = colors["background"]
    stroke = colors["stroke"]
    diff_stroke_dash = ' stroke-dasharray="7 5"' if diff == "removed" else ""
    # Removed nodes: dashed stroke, lower opacity handled via shape style
    t = pos.node.node_type

    if t == NodeType.EVOLUTION:
        common = (
            f'fill="{fill}" stroke="{stroke}" stroke-width="3" '
            'stroke-dasharray="7 5"'
        )
    else:
        common = f'fill="{fill}" stroke="{stroke}" stroke-width="2"'

    if t in (NodeType.START, NodeType.END):
        rx, ry = pos.width / 2, pos.height / 2
        cx, cy = pos.x + rx, pos.y + ry
        return f'<ellipse cx="{_fmt(cx)}" cy="{_fmt(cy)}" rx="{_fmt(rx)}" ry="{_fmt(ry)}" {common}{diff_stroke_dash}/>'

    if t == NodeType.DECISION:
        cx, cy = pos.x + pos.width / 2, pos.y + pos.height / 2
        pts = (
            f"{_fmt(cx)},{_fmt(pos.y)} {_fmt(pos.x + pos.width)},{_fmt(cy)} "
            f"{_fmt(cx)},{_fmt(pos.y + pos.height)} {_fmt(pos.x)},{_fmt(cy)}"
        )
        return f'<polygon points="{pts}" {common}{diff_stroke_dash}/>'

    return (
        f'<rect x="{_fmt(pos.x)}" y="{_fmt(pos.y)}" '
        f'width="{_fmt(pos.width)}" height="{_fmt(pos.height)}" rx="8" {common}{diff_stroke_dash}/>'
    )


def _text_svg(x: float, y: float, text: str, size: int, color: str,
              align: str = "middle") -> str:
    """Multi-line SVG text anchored at (x, y) center."""
    lines = text.split("\n")
    line_h = size * 1.25
    total_h = len(lines) * line_h
    first_y = y - total_h / 2 + size * 0.9

    anchor = "text-anchor='start'" if align == "start" else "text-anchor='middle'"
    tspans = "".join(
        f'<tspan x="{_fmt(x)}" y="{_fmt(first_y + i * line_h)}">{escape(line)}</tspan>'
        for i, line in enumerate(lines)
    )
    return (
        f"<text {anchor} "
        f"font-family=\"{FONT_STACK}\" font-size=\"{size}\" fill=\"{color}\">{tspans}</text>"
    )


def _arrow_path(points: list[list[float]], ox: float, oy: float,
                color: str, dashed: bool) -> str:
    d = "M " + " L ".join(f"{_fmt(ox + px)} {_fmt(oy + py)}" for px, py in points)
    dash = ' stroke-dasharray="6 4"' if dashed else ""
    return (
        f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2"{dash} '
        f'marker-end="url(#arrow-{color.lstrip("#")})"/>'
    )


def _legend_svg(x: float, y: float, pal: dict) -> list[str]:
    items = [
        (NodeType.START, "Start"),
        (NodeType.END, "End"),
        (NodeType.PROCESS, "Process"),
        (NodeType.DECISION, "Decision"),
        (NodeType.TOOL, "Tool call"),
        (NodeType.SUBPROCESS, "Subprocess"),
        (NodeType.LOOP, "Loop"),
        (NodeType.EVOLUTION, "Self-evolution"),
    ]
    parts = [_text_svg(x + 40, y + 8, "LEGEND", 14, pal["title"], align="middle")]
    for i, (nt, label) in enumerate(items):
        colors = pal["node_colors"].get(nt, {"background": "#e9ecef", "stroke": "#495057"})
        row_y = y + 25 + i * 30
        dash = ' stroke-dasharray="4 3"' if nt == NodeType.EVOLUTION else ""
        parts.append(
            f'<rect x="{_fmt(x)}" y="{_fmt(row_y)}" width="20" height="20" rx="4" '
            f'fill="{colors["background"]}" stroke="{colors["stroke"]}"'
            f' stroke-width="1"{dash}/>'
        )
        parts.append(_text_svg(x + 28, row_y + 10, label, 14, pal["text"], align="start"))
    return parts


def to_svg(
    graph: FlowGraph,
    layout: str = "hierarchical",
    theme: str = "light",
    legend: bool = True,
    detail: str = "high",
) -> str:
    """Render a FlowGraph as a standalone SVG string."""
    if detail != "high":
        graph = with_detail_level(graph, detail)
    pal = get_theme(theme)

    if layout == "grid":
        result = grid_layout(graph, theme=theme)
    elif layout == "phased":
        result = phased_layout(graph, theme=theme)
    elif layout == "phased-horizontal":
        result = phased_horizontal_layout(graph, theme=theme)
    elif layout == "radial":
        result = radial_layout(graph, theme=theme)
    else:
        result = hierarchical_layout(graph, theme=theme)

    content_w = result.width
    legend_x = content_w + 60
    total_w = legend_x + 160 if legend else content_w + 20
    total_h = max(result.height, 300 if legend else 0) + 20

    parts: list[str] = []

    # Phase / group background boxes
    for pb in result.phase_boxes:
        parts.append(
            f'<rect x="{_fmt(pb.x)}" y="{_fmt(pb.y)}" width="{_fmt(pb.width)}" '
            f'height="{_fmt(pb.height)}" rx="12" fill="{pb.background}" '
            f'stroke="{pb.stroke}" stroke-width="2" stroke-dasharray="8 5" '
            f'data-phase="{pb.phase}"/>'
        )
        parts.append(_text_svg(pb.x + 120, pb.y + 24, pb.label, 22,
                               pal["phase_label"], align="start"))

    for gb in result.group_boxes:
        parts.append(
            f'<rect x="{_fmt(gb.x)}" y="{_fmt(gb.y)}" width="{_fmt(gb.width)}" '
            f'height="{_fmt(gb.height)}" rx="12" fill="{gb.background}" '
            f'stroke="{gb.stroke}" stroke-width="1" stroke-opacity="0.6" '
            f'stroke-dasharray="8 5" data-group="{escape(gb.group_id)}"/>'
        )
        parts.append(_text_svg(gb.x + 70, gb.y + 14, gb.label, 12,
                               gb.stroke, align="start"))

    for lb in result.lane_boxes:
        parts.append(
            f'<rect x="{_fmt(lb.x)}" y="{_fmt(lb.y)}" width="{_fmt(lb.width)}" '
            f'height="{_fmt(lb.height)}" rx="12" fill="{lb.background}" '
            f'stroke="{lb.stroke}" stroke-width="1" stroke-opacity="0.6" '
            f'stroke-dasharray="8 5" data-group="{escape(lb.lane_id)}" data-lane="{escape(lb.lane_id)}"/>'
        )
        parts.append(_text_svg(lb.x + 70, lb.y + 14, lb.label, 12,
                               lb.stroke, align="start"))

    # Title
    parts.append(_text_svg(80, 30, graph.title, 24, pal["title"], align="start"))

    # Edges first (under nodes), same shared policy as the Excalidraw renderer
    pos_lookup = {p.node.id: p for p in result.positioned}
    edges_by_pair = resolve_edges(graph, result)

    for key, edge in edges_by_pair.items():
        sx, sy, pts = routed_points(pos_lookup[key[0]], pos_lookup[key[1]])
        if edge.diff_status in _DIFF_EDGE_COLORS:
            edge_color = _DIFF_EDGE_COLORS[edge.diff_status]
        elif edge.label in EDGE_SEMANTIC_COLORS:
            edge_color = EDGE_SEMANTIC_COLORS[edge.label]
        else:
            edge_color = pal["arrow"]
        is_dashed = edge.diff_status == "removed" or edge.style == "dashed" or edge.label == "loop"
        ap = _arrow_path(pts, sx, sy, edge_color, dashed=is_dashed)
        ap = ap.replace("/>", f' data-source="{escape(edge.source)}" data-target="{escape(edge.target)}" />')
        parts.append(ap)
        if edge.label:
            mx = sx + (pts[-1][0]) / 2
            my = sy + (pts[-1][1]) / 2 - 12
            parts.append(_text_svg(mx, my, edge.label, 11, pal["detail_text"]))

    fb_slots = assign_feedback_slots(result.feedback_arrows, pos_lookup, result.width)
    for fb_idx, fb in enumerate(result.feedback_arrows):
        if fb.source_id not in pos_lookup or fb.target_id not in pos_lookup:
            continue
        sx, sy, pts = feedback_route(pos_lookup[fb.source_id],
                                     pos_lookup[fb.target_id], result.width,
                                     slot=fb_slots[fb_idx])
        ap_fb = _arrow_path(pts, sx, sy, fb.color, dashed=True)
        ap_fb = ap_fb.replace("/>", f' data-source="{escape(fb.source_id)}" data-target="{escape(fb.target_id)}" data-feedback="true" />')
        parts.append(ap_fb)
        if fb.label:
            mx = sx + pts[-1][0] / 2
            my = sy + pts[-1][1] / 2
            parts.append(_text_svg(mx, my - 12, fb.label, 13, fb.color))

    # Nodes on top of arrows
    for pos in result.positioned:
        extra = f' data-phase="{pos.phase}" data-node-id="{escape(pos.node.id)}" data-node-type="{pos.node.node_type.value}"'
        if pos.group_id:
            extra += f' data-group="{escape(pos.group_id)}"'
        shape = _shape_svg(pos, pal).replace("/>", extra + " />")
        parts.append(shape)
        label_c, detail_c = node_text_block(pos)
        label_svg = _text_svg(label_c[0], label_c[1], pos.node.label, LABEL_FONT, pal["text"])
        label_svg = label_svg.replace("<text ", f'<text data-phase="{pos.phase}" data-node-id="{escape(pos.node.id)}" data-group="{escape(pos.group_id) if pos.group_id else ""}" ', 1)
        parts.append(label_svg)
        if pos.node.detail and detail_c is not None:
            detail_svg = _text_svg(detail_c[0], detail_c[1], pos.node.detail, DETAIL_FONT, pal["detail_text"])
            detail_svg = detail_svg.replace("<text ", f'<text data-phase="{pos.phase}" data-node-id="{escape(pos.node.id)}" data-group="{escape(pos.group_id) if pos.group_id else ""}" ', 1)
            parts.append(detail_svg)

    # Legend
    if legend:
        parts.extend(_legend_svg(legend_x, 30, pal))

    # Arrowhead markers, one per used color
    used_colors = {pal["arrow"]}
    used_colors.update(fb.color for fb in result.feedback_arrows)
    markers = "".join(
        f'<marker id="arrow-{c.lstrip("#")}" viewBox="0 0 10 10" refX="9" refY="5" '
        f'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
        f'<path d="M 0 1 L 9 5 L 0 9 z" fill="{c}"/></marker>'
        for c in sorted(used_colors)
    )

    svg = (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {_fmt(total_w)} {_fmt(total_h)}" '
        f'width="{_fmt(total_w)}" height="{_fmt(total_h)}">'
        f'<rect width="100%" height="100%" fill="{pal["canvas_background"]}"/>'
        f"<defs>{markers}</defs>"
        + "".join(parts)
        + "</svg>"
    )
    return svg


def save_svg(
    graph: FlowGraph,
    output_path: str | Path,
    layout: str = "hierarchical",
    theme: str = "light",
    legend: bool = True,
    detail: str = "high",
) -> Path:
    """Render a FlowGraph and save it as an .svg file."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_svg(graph, layout=layout, theme=theme, legend=legend, detail=detail),
                    encoding="utf-8")
    return path
