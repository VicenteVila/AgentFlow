"""Convert a FlowGraph into valid Excalidraw JSON.

Generates the .excalidraw format with rectangles (processes), diamonds
(decisions), ellipses (start/end), and arrows with proper bindings.
"""

from __future__ import annotations

import json
import random
import string
from pathlib import Path
from typing import Any

from agentflow.layouts import (
    NODE_COLORS,
    LayoutResult,
    PositionedNode,
    hierarchical_layout,
)
from agentflow.models import FlowGraph, NodeType


def _rid() -> str:
    """Generate a random 10-char id for Excalidraw elements."""
    return "".join(random.choices(string.ascii_letters + string.digits, k=10))


def _base_element(pos: PositionedNode, eid: str) -> dict[str, Any]:
    """Common properties for all Excalidraw elements."""
    colors = NODE_COLORS.get(pos.node.node_type, {"background": "#e9ecef", "stroke": "#495057"})
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
        "seed": random.randint(1, 2**31),
        "version": 1,
        "versionNonce": random.randint(1, 2**31),
        "isDeleted": False,
        "boundElements": [],
        "updated": 1,
        "link": None,
        "locked": False,
    }


def _make_shape(pos: PositionedNode, eid: str) -> dict[str, Any]:
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

    el = _base_element(pos, eid)
    el["type"] = el_type
    # EVOLUTION nodes get dashed border to visually distinguish self-modification
    if t == NodeType.EVOLUTION:
        el["strokeStyle"] = "dashed"
        el["strokeWidth"] = 3
    return el


def _estimate_text_size(text: str, font_size: int = 16) -> tuple[float, float]:
    """Estimate text dimensions for Excalidraw rendering.

    Uses a more accurate estimation: ~0.6 * fontSize per character for width,
    and fontSize * 1.25 per line for height (lineHeight factor).
    """
    lines = text.split("\n")
    max_line_len = max(len(line) for line in lines) if lines else 1
    width = max_line_len * font_size * 0.6
    height = len(lines) * font_size * 1.25
    return max(width, 10), max(height, font_size)


def _make_text(x: float, y: float, text: str, eid: str,
               container_id: str | None = None,
               container_width: float = 0, container_height: float = 0,
               font_size: int = 14,
               color: str = "#1e1e1e",
               vertical_offset: float = 0) -> dict[str, Any]:
    """Create a text element, optionally bound to a container.

    When bound to a container, centers the text within the container bounds.
    vertical_offset shifts the text up/down within the container.
    """
    w, h = _estimate_text_size(text, font_size)

    # Center text inside container
    if container_id and container_width > 0 and container_height > 0:
        tx = x + (container_width - w) / 2
        ty = y + (container_height - h) / 2 + vertical_offset
    else:
        tx = x
        ty = y

    el = {
        "id": eid,
        "type": "text",
        "x": tx,
        "y": ty,
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
        "seed": random.randint(1, 2**31),
        "version": 1,
        "versionNonce": random.randint(1, 2**31),
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


def _make_arrow(
    source_pos: PositionedNode,
    target_pos: PositionedNode,
    source_eid: str,
    target_eid: str,
    label: str,
    arrow_id: str,
    label_id: str | None = None,
) -> list[dict[str, Any]]:
    """Create an arrow element with optional label, bound to source and target.
    
    For horizontal layout: arrow goes from right-center of source to left-center of target.
    For vertical layout (fallback): arrow goes from bottom-center of source to top-center of target.
    """
    # Determine if horizontal or vertical based on relative positions
    dx = target_pos.x - source_pos.x
    dy = target_pos.y - source_pos.y

    if abs(dx) > abs(dy):
        # Horizontal: right of source → left of target
        sx = source_pos.x + source_pos.width
        sy = source_pos.y + source_pos.height / 2
        tx = target_pos.x
        ty = target_pos.y + target_pos.height / 2
    else:
        # Vertical: bottom of source → top of target
        sx = source_pos.x + source_pos.width / 2
        sy = source_pos.y + source_pos.height
        tx = target_pos.x + target_pos.width / 2
        ty = target_pos.y

    elements: list[dict[str, Any]] = []

    arrow = {
        "id": arrow_id,
        "type": "arrow",
        "x": sx,
        "y": sy,
        "width": abs(tx - sx) if tx != sx else 1,
        "height": abs(ty - sy) if ty != sy else 1,
        "angle": 0,
        "strokeColor": "#495057",
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
        "seed": random.randint(1, 2**31),
        "version": 1,
        "versionNonce": random.randint(1, 2**31),
        "isDeleted": False,
        "boundElements": [{"id": label_id, "type": "text"}] if label_id else None,
        "updated": 1,
        "link": None,
        "locked": False,
        "points": [[0, 0], [tx - sx, ty - sy]],
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

    # Add arrow label if present
    if label and label_id:
        mid_x = (sx + tx) / 2
        mid_y = (sy + ty) / 2
        lbl = _make_text(mid_x - 20, mid_y - 10, label, label_id, container_id=None)
        lbl["containerId"] = arrow_id
        lbl["textAlign"] = "center"
        lbl["verticalAlign"] = "middle"
        # Update arrow's boundElements to include the label
        arrow["boundElements"] = [{"id": label_id, "type": "text"}]
        elements.append(lbl)

    return elements


def _make_title(title: str, x: float, y: float) -> dict[str, Any]:
    """Create a title text element at the top of the diagram."""
    w, h = _estimate_text_size(title, font_size=24)
    return {
        "id": _rid(),
        "type": "text",
        "x": x,
        "y": y - 40,
        "width": w,
        "height": h,
        "angle": 0,
        "strokeColor": "#1e1e1e",
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
        "seed": random.randint(1, 2**31),
        "version": 1,
        "versionNonce": random.randint(1, 2**31),
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


def to_excalidraw(graph: FlowGraph, layout: str = "hierarchical") -> dict[str, Any]:
    """Convert a FlowGraph to a complete Excalidraw JSON structure.

    Args:
        graph: The flow graph to convert.
        layout: Layout algorithm - "hierarchical" (default) or "grid".

    Returns:
        A dict that can be serialized to .excalidraw JSON.
    """
    from agentflow.layouts import grid_layout

    # Compute layout
    if layout == "grid":
        result = grid_layout(graph)
    else:
        result = hierarchical_layout(graph)

    elements: list[dict[str, Any]] = []
    id_map: dict[str, str] = {}  # node_id -> shape element id
    text_map: dict[str, str] = {}  # node_id -> text element id

    # 0. Group boxes (background rectangles — drawn first so they appear behind)
    for gb in result.group_boxes:
        box_id = _rid()
        # Group label at top-left of the box
        label_id = _rid()
        box = {
            "id": box_id,
            "type": "rectangle",
            "x": gb.x,
            "y": gb.y,
            "width": gb.width,
            "height": gb.height,
            "angle": 0,
            "strokeColor": gb.stroke,
            "backgroundColor": gb.background,
            "fillStyle": "solid",
            "strokeWidth": 1,
            "strokeStyle": "dashed",
            "roughness": 0,
            "opacity": 60,
            "groupIds": [],
            "frameId": None,
            "index": "a0",
            "roundness": {"type": 3},
            "seed": random.randint(1, 2**31),
            "version": 1,
            "versionNonce": random.randint(1, 2**31),
            "isDeleted": False,
            "boundElements": [{"id": label_id, "type": "text"}],
            "updated": 1,
            "link": None,
            "locked": False,
        }
        elements.append(box)
        # Group label
        lbl = {
            "id": label_id,
            "type": "text",
            "x": gb.x + 10,
            "y": gb.y + 6,
            "width": len(gb.label) * 9,
            "height": 16,
            "angle": 0,
            "strokeColor": gb.stroke,
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
            "seed": random.randint(1, 2**31),
            "version": 1,
            "versionNonce": random.randint(1, 2**31),
            "isDeleted": False,
            "boundElements": None,
            "updated": 1,
            "link": None,
            "locked": False,
            "text": gb.label,
            "fontSize": 12,
            "fontFamily": 1,
            "textAlign": "left",
            "verticalAlign": "top",
            "containerId": box_id,
            "originalText": gb.label,
            "autoResize": True,
            "lineHeight": 1.25,
        }
        elements.append(lbl)

    # 1. Title (above the main flow)
    elements.append(_make_title(graph.title, 80, 30))

    # 2. Shape + text for each node
    for pos in result.positioned:
        shape_id = _rid()
        text_id = _rid()
        detail_id = _rid() if pos.node.detail else None
        id_map[pos.node.id] = shape_id
        text_map[pos.node.id] = text_id

        shape = _make_shape(pos, shape_id)

        # Main label — centered in upper portion
        label_text = _make_text(
            pos.x, pos.y, pos.node.label, text_id,
            container_id=shape_id,
            container_width=pos.width, container_height=pos.height,
            font_size=14,
            vertical_offset=-8 if pos.node.detail else 0,
        )

        # Detail subtitle — smaller, gray, in lower portion
        bound = [{"id": text_id, "type": "text"}]
        elements.append(shape)
        elements.append(label_text)

        if pos.node.detail and detail_id:
            detail_text = _make_text(
                pos.x, pos.y, pos.node.detail, detail_id,
                container_id=shape_id,
                container_width=pos.width, container_height=pos.height,
                font_size=10,
                color="#666666",
                vertical_offset=14,
            )
            elements.append(detail_text)
            bound.append({"id": detail_id, "type": "text"})

        shape["boundElements"] = bound

    # 3. Arrows between nodes
    pos_lookup = {p.node.id: p for p in result.positioned}
    label_counts: dict[tuple[str, str], int] = {}

    for edge in graph.edges:
        if edge.source not in pos_lookup or edge.target not in pos_lookup:
            continue

        source_pos = pos_lookup[edge.source]
        target_pos = pos_lookup[edge.target]
        source_eid = id_map[edge.source]
        target_eid = id_map[edge.target]

        key = (edge.source, edge.target)
        label_counts[key] = label_counts.get(key, 0) + 1

        arrow_id = _rid()
        label_id = _rid() if edge.label else None

        arrow_elements = _make_arrow(
            source_pos, target_pos, source_eid, target_eid,
            edge.label, arrow_id, label_id,
        )
        elements.extend(arrow_elements)

        # Add arrow as bound element to source and target shapes
        for el in elements:
            if el["id"] == source_eid:
                be = el.get("boundElements") or []
                be.append({"id": arrow_id, "type": "arrow"})
                el["boundElements"] = be
            if el["id"] == target_eid:
                be = el.get("boundElements") or []
                be.append({"id": arrow_id, "type": "arrow"})
                el["boundElements"] = be

    # 4. Legend (placed to the right of the diagram)
    legend_x = result.width + 80
    legend_y = 30
    elements.extend(_make_legend(legend_x, legend_y))

    # 5. Assemble the Excalidraw document
    doc = {
        "type": "excalidraw",
        "version": 2,
        "source": "https://github.com/VicenteVila/AgentFlow",
        "elements": elements,
        "appState": {
            "gridSize": 20,
            "viewBackgroundColor": "#ffffff",
        },
        "files": {},
    }

    return doc


def _make_legend(x: float, y: float) -> list[dict[str, Any]]:
    """Create a color legend explaining node types."""
    from agentflow.layouts import NODE_COLORS
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
    # Title
    elements.append(_make_text(x, y, "LEGEND", _rid(), font_size=14))
    for i, (nt, label) in enumerate(items):
        colors = NODE_COLORS.get(nt, {"background": "#e9ecef", "stroke": "#495057"})
        row_y = y + 25 + i * 30
        # Color swatch (small rectangle)
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
            "seed": random.randint(1, 2**31),
            "version": 1,
            "versionNonce": random.randint(1, 2**31),
            "isDeleted": False,
            "boundElements": None,
            "updated": 1,
            "link": None,
            "locked": False,
        }
        elements.append(swatch)
        # Label
        elements.append(_make_text(x + 28, row_y + 2, label, _rid(), font_size=14))
    return elements


def save_excalidraw(graph: FlowGraph, output_path: str | Path, layout: str = "hierarchical") -> Path:
    """Generate and save an Excalidraw file from a FlowGraph.

    Args:
        graph: The flow graph to convert.
        output_path: Where to save the .excalidraw file.
        layout: Layout algorithm.

    Returns:
        The Path of the saved file.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    doc = to_excalidraw(graph, layout=layout)
    path.write_text(json.dumps(doc, indent=2, ensure_ascii=False), encoding="utf-8")
    return path
