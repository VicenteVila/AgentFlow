"""Convert a FlowGraph into valid Excalidraw JSON.

Generates the .excalidraw format with rectangles (processes), diamonds
(decisions), ellipses (start/end), and arrows with proper bindings.
Supports light/dark themes and orthogonal arrow routing.
"""

from __future__ import annotations

import json
import random
import string
from pathlib import Path
from typing import Any

from agentflow.layouts import (
    DETAIL_FONT,
    DETAIL_GAP,
    LABEL_FONT,
    PositionedNode,
    get_theme,
    hierarchical_layout,
    measure_text,
    phased_layout,
)
from agentflow.models import FlowGraph, NodeType

# Module-level RNG; re-seeded by to_excalidraw(seed=...) for deterministic output
_rng: random.Random = random.Random()


def _set_seed(seed: int | None) -> None:
    """Re-seed the generator; None keeps entropy for non-deterministic output."""
    global _rng
    _rng = random.Random(seed)


def _rid() -> str:
    """Generate a random 10-char id for Excalidraw elements."""
    return "".join(_rng.choices(string.ascii_letters + string.digits, k=10))


def _base_element(pos: PositionedNode, eid: str, pal: dict) -> dict[str, Any]:
    """Common properties for all Excalidraw elements."""
    colors = pal["node_colors"].get(
        pos.node.node_type, {"background": "#e9ecef", "stroke": "#495057"}
    )
    return {
        "id": eid,
        "x": pos.x,
        "y": pos.y,
        "width": pos.width,
        "height": pos.height,
        "angle": 0,
        "strokeColor": colors["stroke"],
        "backgroundColor": colors["background"],
        "fillStyle": "solid",
        "strokeWidth": 2,
        "strokeStyle": "solid",
        "roughness": 1,
        "opacity": 100,
        "groupIds": [],
        "frameId": None,
        "index": None,
        "roundness": {"type": 3},
        "seed": _rng.randint(1, 2**31),
        "version": 1,
        "versionNonce": _rng.randint(1, 2**31),
        "isDeleted": False,
        "boundElements": [],
        "updated": 1,
        "link": None,
        "locked": False,
    }


def _make_shape(pos: PositionedNode, eid: str, pal: dict) -> dict[str, Any]:
    """Create a rectangle, diamond, or ellipse element."""
    t = pos.node.node_type
    if t in (NodeType.START, NodeType.END):
        el_type = "ellipse"
    elif t == NodeType.DECISION:
        el_type = "diamond"
    elif t == NodeType.EVOLUTION:
        el_type = "rectangle"  # rectangle with dashed stroke
    else:
        el_type = "rectangle"

    el = _base_element(pos, eid, pal)
    el["type"] = el_type
    # EVOLUTION nodes get dashed border to visually distinguish self-modification
    if t == NodeType.EVOLUTION:
        el["strokeStyle"] = "dashed"
        el["strokeWidth"] = 3
    return el


def _make_text(x: float, y: float, text: str, eid: str,
               container_id: str | None = None,
               font_size: int = 14,
               color: str | None = None,
               center: tuple[float, float] | None = None) -> dict[str, Any]:
    """Create a text element, optionally bound to a container.

    When `center` is given, positions the text so its midpoint is at (cx, cy).
    Otherwise places the top-left corner at (x, y).
    """
    pal_default = "#1e1e1e"
    w, h = measure_text(text, font_size)

    if center is not None:
        tx = center[0] - w / 2
        ty = center[1] - h / 2
    else:
        tx, ty = x, y

    el = {
        "id": eid,
        "type": "text",
        "x": tx,
        "y": ty,
        "width": w,
        "height": h,
        "angle": 0,
        "strokeColor": color or pal_default,
        "backgroundColor": "transparent",
        "fillStyle": "solid",
        "strokeWidth": 1,
        "strokeStyle": "solid",
        "roughness": 0,
        "opacity": 100,
        "groupIds": [],
        "frameId": None,
        "index": None,
        "roundness": None,
        "seed": _rng.randint(1, 2**31),
        "version": 1,
        "versionNonce": _rng.randint(1, 2**31),
        "isDeleted": False,
        "boundElements": None,
        "updated": 1,
        "link": None,
        "locked": False,
        "text": text,
        "fontSize": font_size,
        "fontFamily": 1,
        "textAlign": "center",
        "verticalAlign": "middle",
        "containerId": container_id,
        "originalText": text,
        "autoResize": True,
        "lineHeight": 1.25,
    }
    return el


def _node_text_block(pos: PositionedNode) -> tuple[tuple[float, float], tuple[float, float] | None]:
    """Compute centered coordinates for (label, detail) inside a node.

    Returns ((label_cx, label_cy), (detail_cx, detail_cy) | None).
    """
    _, lh = measure_text(pos.node.label, LABEL_FONT)
    cy = pos.y + pos.height / 2

    if not pos.node.detail:
        return (pos.x + pos.width / 2, cy), None

    _, dh = measure_text(pos.node.detail, DETAIL_FONT)
    total = lh + DETAIL_GAP + dh
    label_cy = pos.y + (pos.height - total) / 2 + lh / 2
    detail_cy = pos.y + (pos.height + total) / 2 - dh / 2
    cx = pos.x + pos.width / 2
    return (cx, label_cy), (cx, detail_cy)


def _straight_or_routed_points(
    source_pos: PositionedNode, target_pos: PositionedNode
) -> tuple[float, float, list[list[float]]]:
    """Compute anchor points and waypoint list for an edge.

    Returns (start_x, start_y, relative_points). Uses a straight segment
    when nodes are aligned, otherwise an orthogonal L/Z-shaped route.
    """
    scx = source_pos.x + source_pos.width / 2
    scy = source_pos.y + source_pos.height / 2
    tcx = target_pos.x + target_pos.width / 2
    tcy = target_pos.y + target_pos.height / 2

    dx = tcx - scx
    dy = tcy - scy
    # Rows/columns considered aligned when centers fall within half-extents
    row_aligned = abs(dy) <= (source_pos.height + target_pos.height) / 4
    col_aligned = abs(dx) <= (source_pos.width + target_pos.width) / 4

    if row_aligned and abs(dx) > 1:
        # Straight horizontal: right/left edge of source → opposite edge of target
        sx = source_pos.x + source_pos.width if dx > 0 else source_pos.x
        tx = target_pos.x if dx > 0 else target_pos.x + target_pos.width
        return sx, scy, [[0, 0], [tx - sx, 0]]

    if col_aligned and abs(dy) > 1:
        # Straight vertical: bottom/top edge of source → opposite edge of target
        sy = source_pos.y + source_pos.height if dy > 0 else source_pos.y
        ty = target_pos.y if dy > 0 else target_pos.y + target_pos.height
        return scx, sy, [[0, 0], [0, ty - sy]]

    if abs(dx) >= abs(dy):
        # Horizontal-dominant L: exit sideways, cross vertically at mid X
        sx = source_pos.x + source_pos.width if dx > 0 else source_pos.x
        sy = scy
        tx = target_pos.x if dx > 0 else target_pos.x + target_pos.width
        ty = tcy
        mid_x = (sx + tx) / 2
        pts = [
            [0.0, 0.0],
            [mid_x - sx, 0.0],
            [mid_x - sx, ty - sy],
            [tx - sx, ty - sy],
        ]
        return sx, sy, pts

    # Vertical-dominant L: exit top/bottom, cross horizontally at mid Y
    sx = scx
    sy = source_pos.y + source_pos.height if dy > 0 else source_pos.y
    tx = tcx
    ty = target_pos.y if dy > 0 else target_pos.y + target_pos.height
    mid_y = (sy + ty) / 2
    pts = [
        [0.0, 0.0],
        [0.0, mid_y - sy],
        [tx - sx, mid_y - sy],
        [tx - sx, ty - sy],
    ]
    return sx, sy, pts


def _make_arrow(
    source_pos: PositionedNode,
    target_pos: PositionedNode,
    source_eid: str,
    target_eid: str,
    label: str,
    arrow_id: str,
    label_id: str | None = None,
    color: str = "#495057",
) -> list[dict[str, Any]]:
    """Create an arrow element with orthogonal routing and optional label."""
    sx, sy, pts = _straight_or_routed_points(source_pos, target_pos)
    ex = sx + pts[-1][0]
    ey = sy + pts[-1][1]

    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    width = max(xs) - min(xs)
    height = max(ys) - min(ys)

    elements: list[dict[str, Any]] = []

    arrow = {
        "id": arrow_id,
        "type": "arrow",
        "x": sx,
        "y": sy,
        "width": width if width > 0 else 1,
        "height": height if height > 0 else 1,
        "angle": 0,
        "strokeColor": color,
        "backgroundColor": "transparent",
        "fillStyle": "solid",
        "strokeWidth": 2,
        "strokeStyle": "solid",
        "roughness": 1,
        "opacity": 100,
        "groupIds": [],
        "frameId": None,
        "index": None,
        "roundness": {"type": 2},
        "seed": _rng.randint(1, 2**31),
        "version": 1,
        "versionNonce": _rng.randint(1, 2**31),
        "isDeleted": False,
        "boundElements": [{"id": label_id, "type": "text"}] if label_id else None,
        "updated": 1,
        "link": None,
        "locked": False,
        "points": pts,
        "lastCommittedPoint": None,
        "startBinding": {
            "elementId": source_eid,
            "focus": 0,
            "gap": 8,
            "fixedPoint": None,
        },
        "endBinding": {
            "elementId": target_eid,
            "focus": 0,
            "gap": 8,
            "fixedPoint": None,
        },
        "startArrowhead": None,
        "endArrowhead": "arrow",
        "elbowed": False,
    }
    elements.append(arrow)

    # Add arrow label if present (Excalidraw auto-centers labels on arrows)
    if label and label_id:
        lbl = _make_text((sx + ex) / 2 - 20, (sy + ey) / 2 - 10, label, label_id,
                         color=color)
        lbl["containerId"] = arrow_id
        lbl["textAlign"] = "center"
        lbl["verticalAlign"] = "middle"
        arrow["boundElements"] = [{"id": label_id, "type": "text"}]
        elements.append(lbl)

    return elements


def _feedback_points(
    src: PositionedNode, tgt: PositionedNode, canvas_width: float
) -> tuple[float, float, list[list[float]]]:
    """Lateral route for feedback arrows: up from source top, around the
    outside of both nodes, into the target bottom. Keeps the main column clear.
    """
    sx = src.x + src.width / 2
    sy_top = src.y
    tx = tgt.x + tgt.width / 2
    ty_bot = tgt.y + tgt.height

    pair_center = (sx + tx) / 2
    route_right = pair_center >= canvas_width / 2
    offset = 70.0

    if route_right:
        rx = max(src.x + src.width, tgt.x + tgt.width) + offset
    else:
        rx = min(src.x, tgt.x) - offset

    pts = [
        [0.0, 0.0],
        [rx - sx, 0.0],
        [rx - sx, ty_bot - sy_top],
        [tx - sx, ty_bot - sy_top],
    ]
    return sx, sy_top, pts


def _bind_arrow(elements: list[dict[str, Any]], shape_eid: str, arrow_id: str) -> None:
    """Register an arrow in a shape's boundElements."""
    for el in elements:
        if el["id"] == shape_eid:
            be = el.get("boundElements") or []
            be.append({"id": arrow_id, "type": "arrow"})
            el["boundElements"] = be


def _make_title(title: str, x: float, y: float, color: str = "#1e1e1e") -> dict[str, Any]:
    """Create a title text element at the top of the diagram."""
    w, h = measure_text(title, 24)
    return {
        "id": _rid(),
        "type": "text",
        "x": x,
        "y": y - 40,
        "width": w,
        "height": h,
        "angle": 0,
        "strokeColor": color,
        "backgroundColor": "transparent",
        "fillStyle": "solid",
        "strokeWidth": 1,
        "strokeStyle": "solid",
        "roughness": 0,
        "opacity": 100,
        "groupIds": [],
        "frameId": None,
        "index": None,
        "roundness": None,
        "seed": _rng.randint(1, 2**31),
        "version": 1,
        "versionNonce": _rng.randint(1, 2**31),
        "isDeleted": False,
        "boundElements": None,
        "updated": 1,
        "link": None,
        "locked": False,
        "text": title,
        "fontSize": 24,
        "fontFamily": 1,
        "textAlign": "left",
        "verticalAlign": "top",
        "containerId": None,
        "originalText": title,
        "autoResize": True,
        "lineHeight": 1.25,
    }


def _make_box_with_label(
    x: float, y: float, width: float, height: float,
    background: str, stroke: str, label: str, label_color: str,
    label_font_size: int, opacity: int = 100,
) -> list[dict[str, Any]]:
    """Create a background rectangle (phase/group box) with its label."""
    box_id = _rid()
    label_id = _rid()
    lw, lh = measure_text(label, label_font_size)

    box = {
        "id": box_id,
        "type": "rectangle",
        "x": x,
        "y": y,
        "width": width,
        "height": height,
        "angle": 0,
        "strokeColor": stroke,
        "backgroundColor": background,
        "fillStyle": "solid",
        "strokeWidth": 2,
        "strokeStyle": "dashed",
        "roughness": 0,
        "opacity": opacity,
        "groupIds": [],
        "frameId": None,
        "index": "a0",
        "roundness": {"type": 3},
        "seed": _rng.randint(1, 2**31),
        "version": 1,
        "versionNonce": _rng.randint(1, 2**31),
        "isDeleted": False,
        "boundElements": [{"id": label_id, "type": "text"}],
        "updated": 1,
        "link": None,
        "locked": False,
    }
    lbl = {
        "id": label_id,
        "type": "text",
        "x": x + 20,
        "y": y + 15,
        "width": lw,
        "height": lh,
        "angle": 0,
        "strokeColor": label_color,
        "backgroundColor": "transparent",
        "fillStyle": "solid",
        "strokeWidth": 1,
        "strokeStyle": "solid",
        "roughness": 0,
        "opacity": 100,
        "groupIds": [],
        "frameId": None,
        "index": "a1",
        "roundness": None,
        "seed": _rng.randint(1, 2**31),
        "version": 1,
        "versionNonce": _rng.randint(1, 2**31),
        "isDeleted": False,
        "boundElements": None,
        "updated": 1,
        "link": None,
        "locked": False,
        "text": label,
        "fontSize": label_font_size,
        "fontFamily": 1,
        "textAlign": "left",
        "verticalAlign": "top",
        "containerId": box_id,
        "originalText": label,
        "autoResize": True,
        "lineHeight": 1.25,
    }
    return [box, lbl]


def to_excalidraw(
    graph: FlowGraph,
    layout: str = "hierarchical",
    theme: str = "light",
    legend: bool = True,
    seed: int | None = None,
) -> dict[str, Any]:
    """Convert a FlowGraph to a complete Excalidraw JSON structure.

    Args:
        graph: The flow graph to convert.
        layout: Layout algorithm - "hierarchical" (default), "grid", or "phased".
        theme: Color theme - "light" (default) or "dark".
        legend: Whether to draw the node-type legend.
        seed: RNG seed; same input + seed produces byte-identical output.

    Returns:
        A dict that can be serialized to .excalidraw JSON.
    """
    from agentflow.layouts import grid_layout

    _set_seed(seed)
    pal = get_theme(theme)

    # Compute layout
    if layout == "grid":
        result = grid_layout(graph, theme=theme)
    elif layout == "phased":
        result = phased_layout(graph, theme=theme)
    else:
        result = hierarchical_layout(graph, theme=theme)

    elements: list[dict[str, Any]] = []

    # 0. Phase boxes (for phased layout — drawn first so they appear behind)
    for pb in result.phase_boxes:
        elements.extend(_make_box_with_label(
            pb.x, pb.y, pb.width, pb.height,
            background=pb.background, stroke=pb.stroke,
            label=pb.label, label_color=pal["phase_label"],
            label_font_size=22,
        ))

    # 0b. Group boxes (for hierarchical layout — drawn behind everything)
    for gb in result.group_boxes:
        elements.extend(_make_box_with_label(
            gb.x, gb.y, gb.width, gb.height,
            background=gb.background, stroke=gb.stroke,
            label=gb.label, label_color=gb.stroke,
            label_font_size=12, opacity=60,
        ))

    # 1. Title (above the main flow)
    elements.append(_make_title(graph.title, 80, 30, color=pal["title"]))

    # 2. Shape + text for each node
    id_map: dict[str, str] = {}
    for pos in result.positioned:
        shape_id = _rid()
        text_id = _rid()
        id_map[pos.node.id] = shape_id

        shape = _make_shape(pos, shape_id, pal)

        label_center, detail_center = _node_text_block(pos)
        label_text = _make_text(
            pos.x, pos.y, pos.node.label, text_id,
            container_id=shape_id,
            color=pal["text"],
            center=label_center,
        )

        bound = [{"id": text_id, "type": "text"}]
        elements.append(shape)
        elements.append(label_text)

        if pos.node.detail and detail_center is not None:
            detail_id = _rid()
            detail_text = _make_text(
                pos.x, pos.y, pos.node.detail, detail_id,
                container_id=shape_id,
                font_size=DETAIL_FONT,
                color=pal["detail_text"],
                center=detail_center,
            )
            elements.append(detail_text)
            bound.append({"id": detail_id, "type": "text"})

        shape["boundElements"] = bound

    # 3. Arrows between nodes (one per node pair; skip feedback-drawn edges).
    # Parallel edges (same source→target) collapse into a single arrow,
    # preferring the one that carries a label.
    pos_lookup = {p.node.id: p for p in result.positioned}
    feedback_keys = {(fb.source_id, fb.target_id) for fb in result.feedback_arrows}

    edges_by_pair: dict[tuple[str, str], Any] = {}
    for edge in graph.edges:
        if edge.source not in pos_lookup or edge.target not in pos_lookup:
            continue
        key = (edge.source, edge.target)
        existing = edges_by_pair.get(key)
        if existing is None or (not existing.label and edge.label):
            edges_by_pair[key] = edge

    for key, edge in edges_by_pair.items():
        if key in feedback_keys:
            continue

        arrow_id = _rid()
        label_id = _rid() if edge.label else None

        arrow_elements = _make_arrow(
            pos_lookup[edge.source], pos_lookup[edge.target],
            id_map[edge.source], id_map[edge.target],
            edge.label, arrow_id, label_id,
            color=pal["arrow"],
        )
        elements.extend(arrow_elements)
        _bind_arrow(elements, id_map[edge.source], arrow_id)
        _bind_arrow(elements, id_map[edge.target], arrow_id)

    # 3b. Feedback arrows (dashed, routed laterally around the flow)
    for fb in result.feedback_arrows:
        if fb.source_id not in pos_lookup or fb.target_id not in pos_lookup:
            continue
        src_pos = pos_lookup[fb.source_id]
        tgt_pos = pos_lookup[fb.target_id]

        sx, sy, pts = _feedback_points(src_pos, tgt_pos, result.width)
        ex = sx + pts[-1][0]
        ey = sy + pts[-1][1]

        arrow_id = _rid()
        label_id = _rid() if fb.label else None

        xs = [p[0] for p in pts]
        ys = [p[1] for p in pts]

        arrow = {
            "id": arrow_id,
            "type": "arrow",
            "x": sx,
            "y": sy,
            "width": max(max(xs) - min(xs), 1),
            "height": max(max(ys) - min(ys), 1),
            "angle": 0,
            "strokeColor": fb.color,
            "backgroundColor": "transparent",
            "fillStyle": "solid",
            "strokeWidth": 2,
            "strokeStyle": fb.style,
            "roughness": 1,
            "opacity": 100,
            "groupIds": [],
            "frameId": None,
            "index": None,
            "roundness": {"type": 2},
            "seed": _rng.randint(1, 2**31),
            "version": 1,
            "versionNonce": _rng.randint(1, 2**31),
            "isDeleted": False,
            "boundElements": [{"id": label_id, "type": "text"}] if label_id else None,
            "updated": 1,
            "link": None,
            "locked": False,
            "points": pts,
            "lastCommittedPoint": None,
            "startBinding": {
                "elementId": id_map[fb.source_id],
                "focus": 0,
                "gap": 8,
                "fixedPoint": None,
            },
            "endBinding": {
                "elementId": id_map[fb.target_id],
                "focus": 0,
                "gap": 8,
                "fixedPoint": None,
            },
            "startArrowhead": None,
            "endArrowhead": "arrow",
            "elbowed": False,
        }
        elements.append(arrow)

        if fb.label and label_id:
            lbl = _make_text((sx + ex) / 2, (sy + ey) / 2 - 14, fb.label, label_id,
                             font_size=13, color=fb.color)
            lbl["containerId"] = arrow_id
            elements.append(lbl)

        _bind_arrow(elements, id_map[fb.source_id], arrow_id)
        _bind_arrow(elements, id_map[fb.target_id], arrow_id)

    # 4. Legend (placed to the right of the diagram)
    if legend:
        elements.extend(_make_legend(result.width + 80, 30, pal))

    # 5. Assemble the Excalidraw document
    doc = {
        "type": "excalidraw",
        "version": 2,
        "source": "https://github.com/VicenteVila/AgentFlow",
        "elements": elements,
        "appState": {
            "gridSize": 20,
            "viewBackgroundColor": pal["canvas_background"],
        },
        "files": {},
    }

    return doc


def _make_legend(x: float, y: float, pal: dict) -> list[dict[str, Any]]:
    """Create a color legend explaining node types."""
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
    elements: list[dict[str, Any]] = []
    elements.append(_make_text(x, y, "LEGEND", _rid(), font_size=14,
                               color=pal["title"]))
    for i, (nt, label) in enumerate(items):
        colors = pal["node_colors"].get(
            nt, {"background": "#e9ecef", "stroke": "#495057"}
        )
        row_y = y + 25 + i * 30
        swatch = {
            "id": _rid(),
            "type": "rectangle",
            "x": x,
            "y": row_y,
            "width": 20,
            "height": 20,
            "angle": 0,
            "strokeColor": colors["stroke"],
            "backgroundColor": colors["background"],
            "fillStyle": "solid",
            "strokeWidth": 1,
            "strokeStyle": "dashed" if nt == NodeType.EVOLUTION else "solid",
            "roughness": 0,
            "opacity": 100,
            "groupIds": [],
            "frameId": None,
            "index": None,
            "roundness": {"type": 3},
            "seed": _rng.randint(1, 2**31),
            "version": 1,
            "versionNonce": _rng.randint(1, 2**31),
            "isDeleted": False,
            "boundElements": None,
            "updated": 1,
            "link": None,
            "locked": False,
        }
        elements.append(swatch)
        elements.append(_make_text(x + 28, row_y + 2, label, _rid(), font_size=14,
                                   color=pal["text"]))
    return elements


def save_excalidraw(
    graph: FlowGraph,
    output_path: str | Path,
    layout: str = "hierarchical",
    theme: str = "light",
    legend: bool = True,
    seed: int | None = None,
) -> Path:
    """Generate and save an Excalidraw file from a FlowGraph.

    Args:
        graph: The flow graph to convert.
        output_path: Where to save the .excalidraw file.
        layout: Layout algorithm.
        theme: Color theme ("light" or "dark").
        legend: Whether to include the legend.
        seed: RNG seed for deterministic output.

    Returns:
        The Path of the saved file.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    doc = to_excalidraw(graph, layout=layout, theme=theme, legend=legend, seed=seed)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
