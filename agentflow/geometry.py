"""Shared rendering geometry for AgentFlow output formats.

Single source of truth for arrow routing, text placement inside nodes,
and edge resolution. Both the Excalidraw and SVG renderers consume these
functions; neither imports private helpers from the other.
"""

from __future__ import annotations

from typing import Any

from agentflow.layouts import (
    DETAIL_FONT,
    DETAIL_GAP,
    LABEL_FONT,
    LayoutResult,
    PositionedNode,
    measure_text,
)
from agentflow.models import FlowGraph


def routed_points(
    source_pos: PositionedNode, target_pos: PositionedNode
) -> tuple[float, float, list[list[float]]]:
    """Compute anchor points and waypoint list for an edge.

    Returns (start_x, start_y, relative_points). Uses a straight segment
    when nodes are aligned, otherwise an orthogonal L-shaped route.
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


def feedback_route(
    src: PositionedNode,
    tgt: PositionedNode,
    canvas_width: float,
    slot: int = 0,
) -> tuple[float, float, list[list[float]]]:
    """Lateral route for feedback arrows: up from source top, around the
    outside of both nodes, into the target bottom. Keeps the main column clear.

    Arrows sharing a side are staggered by `slot` so they never overlap.
    """
    base_offset = 70.0
    stagger = 45.0
    offset = base_offset + slot * stagger

    sx = src.x + src.width / 2
    sy_top = src.y
    tx = tgt.x + tgt.width / 2
    ty_bot = tgt.y + tgt.height

    pair_center = (sx + tx) / 2
    route_right = pair_center >= canvas_width / 2

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


def assign_feedback_slots(
    feedback: list[Any],
    pos_lookup: dict[str, PositionedNode],
    canvas_width: float,
) -> dict[int, int]:
    """Assign a non-overlapping lateral slot to each feedback arrow.

    Returns {index_in_feedback_list: slot}. Arrows routed to the same side
    get consecutive slots; arrows on opposite sides share slot 0.
    """
    slots: dict[int, int] = {}
    used: dict[bool, int] = {True: 0, False: 0}

    def side_of(fb: Any) -> bool:
        src = pos_lookup[fb.source_id]
        tgt = pos_lookup[fb.target_id]
        sx = src.x + src.width / 2
        tx = tgt.x + tgt.width / 2
        return (sx + tx) / 2 >= canvas_width / 2

    for i, fb in enumerate(feedback):
        if fb.source_id not in pos_lookup or fb.target_id not in pos_lookup:
            slots[i] = 0
            continue
        s = side_of(fb)
        slots[i] = used[s]
        used[s] += 1
    return slots


def node_text_block(pos: PositionedNode) -> tuple[tuple[float, float], tuple[float, float] | None]:
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


def resolve_edges(graph: FlowGraph, result: LayoutResult) -> dict[tuple[str, str], Any]:
    """Resolve which edges become rendered arrows.

    One arrow per node pair (parallel edges collapse, preferring the one
    carrying a label). Edges already drawn as styled feedback arrows are
    excluded. Both renderers must use this exact same policy.
    """
    pos_lookup = {p.node.id: p for p in result.positioned}
    feedback_keys = {(fb.source_id, fb.target_id) for fb in result.feedback_arrows}

    edges_by_pair: dict[tuple[str, str], Any] = {}
    for edge in graph.edges:
        if edge.source not in pos_lookup or edge.target not in pos_lookup:
            continue
        key = (edge.source, edge.target)
        if key in feedback_keys:
            continue
        existing = edges_by_pair.get(key)
        if existing is None or (not existing.label and edge.label):
            edges_by_pair[key] = edge
    return edges_by_pair
