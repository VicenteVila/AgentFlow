"""Parse Python source code to extract agent control flow.

Uses Python's ast module to analyze the control flow of an agent class
and produce a FlowGraph with nodes (processes, decisions, tools) and
edges (flow connections with labels).

The parser is domain-agnostic: all domain knowledge (known tools,
exhaustive labels, decision hints, phase patterns) comes from a
:class:`agentflow.profiles.Profile`. Labels are EXHAUSTIVE when the
profile provides rich metadata; the generic profile derives labels
directly from the code.
"""

from __future__ import annotations

import ast
from pathlib import Path

from agentflow.models import Edge, FlowGraph, Node, NodeType
from agentflow.profiles import Profile, get_profile


def parse_file(filepath: str | Path, profile: str | Profile | None = None) -> FlowGraph:
    """Parse a Python file and extract the agent flow graph."""
    path = Path(filepath)
    source = path.read_text(encoding="utf-8")
    return parse_source(source, title=f"Flow: {path.stem}", profile=profile)


def parse_source(
    source: str,
    title: str = "Agent Flow",
    profile: str | Profile | None = None,
) -> FlowGraph:
    """Parse Python source code and extract the agent flow graph."""
    prof = get_profile(profile)
    tree = ast.parse(source)
    graph = FlowGraph(title=title)

    graph.add_node(Node(
        id="start", label="Start", detail="Agent.run() invoked\nbudget.start()",
        node_type=NodeType.START,
    ))

    agent_cls = _find_agent_class(tree)
    if agent_cls:
        _parse_agent_class(agent_cls, graph, prof)
    else:
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                _parse_function(node, graph)

    if not any(n.node_type == NodeType.END for n in graph.nodes):
        graph.add_node(Node(
            id="end", label="End",
            detail="db.close()\n_final_summary()",
            node_type=NodeType.END,
        ))

    _apply_phase_patterns(graph, prof)

    return graph


# ── Phase assignment ──────────────────────────────────────────────────


def _apply_phase_patterns(graph: FlowGraph, prof: Profile) -> None:
    """Stamp phase hints (1/2/3) onto nodes from profile patterns.

    Nodes that match nothing keep phase=0; the phased layout then falls
    back to structural detection (cycles → loop phase).
    """
    if not prof.phase_patterns:
        return

    for node in graph.nodes:
        nid = node.id.lower()
        label = node.label.lower()
        matched = 0
        for pattern, phase in prof.phase_patterns.items():
            if pattern in nid or pattern in label:
                matched = phase
                break
        if matched:
            node.phase = matched
        elif node.node_type == NodeType.START:
            node.phase = 1
        elif node.node_type == NodeType.END:
            node.phase = 3


# ── Class/method parsing ──────────────────────────────────────────────


def _find_agent_class(tree: ast.Module) -> ast.ClassDef | None:
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            name_lower = node.name.lower()
            if "agent" in name_lower or any(
                isinstance(item, ast.FunctionDef) and item.name == "run"
                for item in node.body
            ):
                return node
    return None


def _parse_agent_class(cls: ast.ClassDef, graph: FlowGraph, prof: Profile) -> None:
    run_method = None
    init_method = None
    handle_eval = None
    for item in cls.body:
        if isinstance(item, ast.FunctionDef):
            if item.name == "run":
                run_method = item
            elif item.name == "__init__":
                init_method = item
            elif item.name == "_handle_eval_result":
                handle_eval = item

    if init_method:
        _parse_init(init_method, graph, prof)

    if init_method:
        graph.add_edge(Edge(source="start", target="init", label=""))
        prev_node = "init"
    else:
        graph.add_edge(Edge(source="start", target="main_loop", label=""))
        prev_node = "start"

    if run_method:
        _parse_run_method(run_method, graph, prev_node, prof)

        # Also scan _handle_eval_result for tool dispatch patterns
        if handle_eval:
            _scan_handle_eval_for_tools(handle_eval, graph, prof)
    else:
        for item in cls.body:
            if isinstance(item, ast.FunctionDef) and item.name != "__init__":
                _parse_function(item, graph)
                break


def _parse_init(method: ast.FunctionDef, graph: FlowGraph, prof: Profile) -> None:
    setup_steps = []
    for stmt in method.body:
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    setup_steps.append(target.id)
        elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
            func = stmt.value.func
            if isinstance(func, ast.Attribute):
                setup_steps.append(func.attr)

    key_steps = [s for s in setup_steps if not s.startswith("_")][:8]

    label, base_detail = prof.init_label or (
        "Init Agent", "Configura dependencias\nde forma automática"
    )
    detail = base_detail if not key_steps else ", ".join(key_steps[:6])

    graph.add_node(Node(id="init", label=label, detail=detail,
                        node_type=NodeType.PROCESS))


def _parse_run_method(
    method: ast.FunctionDef, graph: FlowGraph, prev_node: str, prof: Profile
) -> None:
    graph.add_node(Node(
        id="main_loop", label="Main Loop",
        detail="while True:\n  turn += 1\n  register_evaluation()\n  budget.done()?",
        node_type=NodeType.LOOP,
    ))
    graph.add_edge(Edge(source=prev_node, target="main_loop"))
    _parse_block(method.body, graph, parent_id="main_loop", prof=prof)


def _parse_block(
    stmts: list[ast.stmt],
    graph: FlowGraph,
    parent_id: str,
    depth: int = 0,
    prof: Profile = None,  # type: ignore[assignment]
) -> str:
    if depth > 10:
        return parent_id
    assert prof is not None

    current = parent_id

    for stmt in stmts:
        if isinstance(stmt, ast.While):
            current = _parse_while(stmt, graph, current, depth, prof)
        elif isinstance(stmt, ast.If):
            current = _parse_if(stmt, graph, current, depth, prof)
        elif isinstance(stmt, ast.For):
            current = _parse_for(stmt, graph, current, depth, prof)
        elif isinstance(stmt, ast.Expr):
            current = _parse_expr_stmt(stmt, graph, current, prof)
        elif isinstance(stmt, ast.Assign):
            current = _parse_assign(stmt, graph, current, prof)
        elif isinstance(stmt, ast.Try):
            current = _parse_try(stmt, graph, current, depth, prof)
        elif isinstance(stmt, ast.FunctionDef):
            current = _parse_local_function(stmt, graph, current)

    return current


def _parse_while(
    stmt: ast.While, graph: FlowGraph, parent_id: str, depth: int, prof: Profile
) -> str:
    loop_id = f"loop_{stmt.lineno}"
    graph.add_node(Node(id=loop_id, label=_while_label(stmt), node_type=NodeType.LOOP))
    graph.add_edge(Edge(source=parent_id, target=loop_id))

    last_in_body = _parse_block(stmt.body, graph, loop_id, depth + 1, prof)

    if last_in_body != loop_id:
        graph.add_edge(Edge(source=last_in_body, target=loop_id, label=prof.loop_edge_label))

    return loop_id


def _parse_if(
    stmt: ast.If, graph: FlowGraph, parent_id: str, depth: int, prof: Profile
) -> str:
    tool_from_dispatch = _detect_tool_dispatch(stmt, prof)

    dec_id = f"dec_{stmt.lineno}"
    label, detail = _if_label_and_detail(stmt, prof)
    graph.add_node(Node(id=dec_id, label=label, detail=detail, node_type=NodeType.DECISION))
    graph.add_edge(Edge(source=parent_id, target=dec_id))

    if tool_from_dispatch:
        tool_id = f"tool_{tool_from_dispatch}_{stmt.lineno}"
        t_label, t_detail = prof.tool_names.get(tool_from_dispatch, (tool_from_dispatch, ""))
        graph.add_node(Node(
            id=tool_id, label=t_label, detail=t_detail,
            node_type=NodeType.TOOL, line=stmt.lineno,
        ))
        graph.add_edge(Edge(source=dec_id, target=tool_id, label="YES"))
    else:
        tool_id = None

    last_yes = _parse_block(
        stmt.body, graph,
        tool_id if tool_from_dispatch else dec_id,
        depth + 1, prof,
    )

    if stmt.orelse:
        if len(stmt.orelse) == 1 and isinstance(stmt.orelse[0], ast.If):
            last_no = _parse_if(stmt.orelse[0], graph, dec_id, depth + 1, prof)
        else:
            last_no = _parse_block(stmt.orelse, graph, dec_id, depth + 1, prof)
            for e in graph.edges:
                if e.source == dec_id and e.target == last_yes and not e.label:
                    e.label = "YES"
                elif e.source == dec_id and e.target == last_no and not e.label:
                    e.label = "NO"

        return last_no
    else:
        return last_yes


def _detect_tool_dispatch(stmt: ast.If, prof: Profile) -> str | None:
    """Detect ``if <obj>.<dispatch_attr> == "<known tool>"`` patterns."""
    test = stmt.test
    if not isinstance(test, ast.Compare):
        return None
    if not isinstance(test.ops[0], ast.Eq):
        return None
    if len(test.comparators) != 1:
        return None

    left = test.left
    if not isinstance(left, ast.Attribute) or left.attr != prof.dispatch_attr:
        return None

    comparator = test.comparators[0]
    if not isinstance(comparator, ast.Constant) or not isinstance(comparator.value, str):
        return None

    tool_name = comparator.value
    if tool_name in prof.tool_names:
        return tool_name
    return None


def _parse_for(
    stmt: ast.For, graph: FlowGraph, parent_id: str, depth: int, prof: Profile
) -> str:
    loop_id = f"loop_{stmt.lineno}"
    target = stmt.target
    if isinstance(target, ast.Name):
        iter_name = ""
        if isinstance(stmt.iter, ast.Name):
            iter_name = stmt.iter.id
        elif isinstance(stmt.iter, ast.Attribute):
            iter_name = stmt.iter.attr
        label = f"For each {target.id}"
        if iter_name:
            label += f" in {iter_name}"
    else:
        label = "For loop"
    graph.add_node(Node(id=loop_id, label=label, node_type=NodeType.LOOP))
    graph.add_edge(Edge(source=parent_id, target=loop_id))

    last_in_body = _parse_block(stmt.body, graph, loop_id, depth + 1, prof)
    if last_in_body != loop_id:
        graph.add_edge(Edge(source=last_in_body, target=loop_id, label=prof.loop_edge_label))

    return loop_id


def _parse_expr_stmt(
    stmt: ast.Expr, graph: FlowGraph, parent_id: str, prof: Profile
) -> str:
    if isinstance(stmt.value, ast.Call):
        call_info = _extract_call_info(stmt.value, prof)
        if call_info:
            node_id, label, node_type, detail = call_info
            graph.add_node(Node(
                id=node_id, label=label, detail=detail,
                node_type=node_type, line=stmt.lineno,
            ))
            graph.add_edge(Edge(source=parent_id, target=node_id))
            return node_id
    return parent_id


def _parse_assign(
    stmt: ast.Assign, graph: FlowGraph, parent_id: str, prof: Profile
) -> str:
    if isinstance(stmt.value, ast.Call):
        call_info = _extract_call_info(stmt.value, prof)
        if call_info:
            node_id, label, node_type, detail = call_info
            if stmt.targets and isinstance(stmt.targets[0], ast.Name):
                var_name = stmt.targets[0].id
                if not var_name.startswith("_"):
                    label = f"{var_name} = {label}"
            graph.add_node(Node(
                id=node_id, label=label, detail=detail,
                node_type=node_type, line=stmt.lineno,
            ))
            graph.add_edge(Edge(source=parent_id, target=node_id))
            return node_id
    return parent_id


def _parse_try(
    stmt: ast.Try, graph: FlowGraph, parent_id: str, depth: int, prof: Profile
) -> str:
    last = _parse_block(stmt.body, graph, parent_id, depth + 1, prof)

    for handler in stmt.handlers:
        last = _parse_block(handler.body, graph, last, depth + 1, prof)

    if stmt.finalbody:
        last = _parse_block(stmt.finalbody, graph, last, depth + 1, prof)

    return last


def _parse_local_function(
    method: ast.FunctionDef, graph: FlowGraph, parent_id: str
) -> str:
    node_id = f"fn_{method.name}_{method.lineno}"
    label = method.name.lstrip("_").replace("_", " ").title()
    # Try to get the docstring for detail
    detail = ""
    if (method.body and isinstance(method.body[0], ast.Expr)
            and isinstance(method.body[0].value, ast.Constant)
            and isinstance(method.body[0].value.value, str)):
        detail = method.body[0].value.value[:120]
    graph.add_node(Node(
        id=node_id, label=label, detail=detail,
        node_type=NodeType.SUBPROCESS, line=method.lineno,
    ))
    graph.add_edge(Edge(source=parent_id, target=node_id))
    return node_id


def _parse_function(method: ast.FunctionDef, graph: FlowGraph) -> None:
    node_id = f"fn_{method.name}"
    label = method.name.lstrip("_").replace("_", " ").title()
    graph.add_node(Node(id=node_id, label=label, node_type=NodeType.SUBPROCESS, line=method.lineno))
    graph.add_edge(Edge(source="start", target=node_id))


def _scan_handle_eval_for_tools(method: ast.FunctionDef, graph: FlowGraph, prof: Profile) -> None:
    """Scan _handle_eval_result for tool dispatch patterns and add tool nodes.

    These are tools dispatched from the for-loop body via if/elif chains.
    We connect them to the for-loop node (loop_*) so they appear in the flow.
    """
    for_loop_id = None
    for n in graph.nodes:
        if n.node_type == NodeType.LOOP and "tool_calls" in n.label.lower():
            for_loop_id = n.id
            break
    if not for_loop_id:
        for_loop_id = "main_loop"

    for node in ast.walk(method):
        if isinstance(node, ast.If):
            tool_name = _detect_tool_dispatch(node, prof)
            if tool_name and not any(n.id.startswith(f"tool_{tool_name}_") for n in graph.nodes):
                tool_id = f"tool_{tool_name}_{node.lineno}"
                label, detail = prof.tool_names.get(tool_name, (tool_name, ""))
                graph.add_node(Node(
                    id=tool_id, label=label, detail=detail,
                    node_type=NodeType.TOOL, line=node.lineno,
                ))
                # Connect from the for-loop (tools are dispatched inside the loop)
                graph.add_edge(Edge(source=for_loop_id, target=tool_id, label="dispatch"))


# ── Label + detail extraction ───────────────────────────────────────


def _extract_call_info(
    call: ast.Call, prof: Profile
) -> tuple[str, str, NodeType, str] | None:
    """Extract (node_id, label, type, detail) from a function call."""
    func = call.func

    if isinstance(func, ast.Attribute):
        method_name = func.attr

        # Known tools — exhaustive labels from the profile
        if method_name in prof.tool_names:
            label, detail = prof.tool_names[method_name]
            return (
                f"tool_{method_name}_{call.lineno}",
                label,
                NodeType.TOOL,
                detail,
            )

        # Auto-evolution methods
        if method_name in prof.evolution_methods:
            label, detail = prof.evolution_methods[method_name]
            return (
                f"evo_{method_name}_{call.lineno}",
                label,
                NodeType.EVOLUTION,
                detail,
            )

        # Special calls (meta-edits, compaction, snapshot, export…)
        if method_name in prof.special_calls:
            label, detail, node_type = prof.special_calls[method_name]
            if not label:
                return None  # explicitly skipped (e.g. budget sync noise)
            prefix = "meta" if node_type == NodeType.EVOLUTION else "special"
            return (
                f"{prefix}_{method_name}_{call.lineno}",
                label,
                node_type,
                detail,
            )

    if isinstance(func, ast.Name) and func.id in prof.special_calls:
        label, detail, node_type = prof.special_calls[func.id]
        if not label:
            return None
        return (
            f"fn_{func.id}_{call.lineno}",
            label,
            node_type,
            detail,
        )

    return None


def _generic_if_label(stmt: ast.If) -> tuple[str, str]:
    """Derive a readable label/detail from an arbitrary condition."""
    try:
        raw = ast.unparse(stmt.test)
    except Exception:  # noqa: BLE001 — unparse fallback is best-effort
        raw = stmt.test.__class__.__name__

    # Split into ≤2 lines of ~28 chars for diamond readability
    words = raw.split()
    lines: list[str] = [""]
    for w in words:
        if len(lines[-1]) + len(w) + 1 > 28 and len(lines) < 2:
            lines.append("")
        if len(lines[-1]) + len(w) + 1 <= 34:
            lines[-1] = (lines[-1] + " " + w).strip()
    while len(lines) < 2:
        lines.append("")
    label = "\n".join(lines[:2]).strip() or "Condition?"

    detail = f"Condición en línea {stmt.lineno}:\n{raw[:60]}"
    return label, detail


def _if_label_and_detail(stmt: ast.If, prof: Profile) -> tuple[str, str]:
    """Generate label + detail for an if statement using profile hints."""
    test = stmt.test

    if (
        isinstance(test, ast.UnaryOp)
        and isinstance(test.op, ast.Not)
        and isinstance(test.operand, ast.Attribute)
    ):
        return (
            f"NOT {test.operand.attr}?",
            f"Niega {test.operand.attr}\npara lógica invertida",
        )

    # Tool dispatch comparisons: call.name == "x" → "Tool: x?"
    if isinstance(test, ast.Compare):
        left = test.left
        if isinstance(left, ast.Attribute) and left.attr == prof.dispatch_attr:
            for comp in test.comparators:
                if isinstance(comp, ast.Constant) and isinstance(comp.value, str):
                    tool_name = comp.value
                    if tool_name in prof.tool_names:
                        label, detail = prof.tool_names[tool_name]
                        single = label.split("\n")[0]
                        return (f"Tool:\n{single}?", detail)
                    return (f"Tool:\n{tool_name}?", f"Dispatch {tool_name}")

    # Profile decision hints: substring match on the AST dump
    try:
        raw = ast.dump(test)
    except Exception:  # noqa: BLE001 — dump fallback is best-effort
        raw = ""
    for needle, label, detail in prof.decision_hints:
        if needle in raw:
            return (label, detail)

    return _generic_if_label(stmt)


def _while_label(stmt: ast.While) -> str:
    test = stmt.test

    if isinstance(test, ast.Constant) and test.value is True:
        return "Main Loop\n(while True)"

    if isinstance(test, ast.Name):
        return f"while {test.id}"

    return "Loop"
