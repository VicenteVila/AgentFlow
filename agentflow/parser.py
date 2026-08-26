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

_FUNC_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef)


def _unwrap_call(expr: object):
    """Unwrap Await so async calls are detected like sync ones."""
    import ast as _ast
    if isinstance(expr, _ast.Await):
        return expr.value
    return expr


class ParseContext:
    """Carries the profile and target graph through the parse pipeline."""

    __slots__ = ("prof", "graph")

    def __init__(self, prof: Profile, graph: FlowGraph) -> None:
        self.prof = prof
        self.graph = graph


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

    agent_cls = _find_agent_class(tree, prof)
    if agent_cls:
        _parse_agent_class(agent_cls, ParseContext(prof, graph))
    else:
        # No agent class: treat top-level functions as entry points.
        # Expand the largest function's body so its internal control flow is visible.
        ctx = ParseContext(prof, graph)
        top_funcs = [n for n in tree.body if isinstance(n, _FUNC_TYPES)]
        for fn in top_funcs:
            fid = f"fn_{fn.name}"
            label = fn.name.lstrip("_").replace("_", " ").title()
            graph.add_node(Node(id=fid, label=label, node_type=NodeType.SUBPROCESS, line=fn.lineno))
            graph.add_edge(Edge(source="start", target=fid))
            # Expand each function's body so internal control flow is visible
            if len(fn.body) > 3:
                _parse_block(ctx, fn.body, fid)

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


def _find_agent_class(tree: ast.Module, profile: Profile | None = None) -> ast.ClassDef | None:
    prof_names = set()
    if profile and hasattr(profile, "agent_class_names"):
        prof_names = {k.lower() for k in profile.agent_class_names}

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            name_lower = node.name.lower()
            if (
                "agent" in name_lower
                or node.name in (profile.agent_class_names if profile else {})
                or name_lower in prof_names
                or any(
                    isinstance(item, _FUNC_TYPES) and item.name == "run"
                    for item in node.body
                )
            ):
                return node
    return None


def _parse_agent_class(cls: ast.ClassDef, ctx: ParseContext) -> None:
    run_method = None
    init_method = None
    handle_eval = None
    for item in cls.body:
        if isinstance(item, _FUNC_TYPES):
            if item.name == "run":
                run_method = item
            elif item.name == "__init__":
                init_method = item
            elif item.name == "_handle_eval_result":
                handle_eval = item

    prev_node: str
    if init_method:
        _parse_init(init_method, ctx)
        ctx.graph.add_edge(Edge(source="start", target="init", label=""))
        prev_node = "init"
    else:
        ctx.graph.add_edge(Edge(source="start", target="main_loop", label=""))
        prev_node = "start"

    if run_method:
        _parse_run_method(run_method, ctx, prev_node)
        if handle_eval:
            _scan_handle_eval_for_tools(handle_eval, ctx)
    else:
        # No run() method: expand the largest non-init method as the main flow.
        candidates = [i for i in cls.body if isinstance(i, _FUNC_TYPES) and i.name != "__init__"]
        for item in candidates:
            fid = f"fn_{item.name}_{item.lineno}"
            label = item.name.lstrip("_").replace("_", " ").title()
            detail = ""
            if (item.body and isinstance(item.body[0], ast.Expr)
                    and isinstance(item.body[0].value, ast.Constant)
                    and isinstance(item.body[0].value.value, str)):
                detail = item.body[0].value.value[:120]
            ctx.graph.add_node(Node(id=fid, label=label, detail=detail,
                                    node_type=NodeType.SUBPROCESS, line=item.lineno))
            ctx.graph.add_edge(Edge(source="start", target=fid))
            if len(item.body) > 3:
                _parse_block(ctx, item.body, fid)


def _parse_init(method: ast.FunctionDef | ast.AsyncFunctionDef, ctx: ParseContext) -> None:
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

    label, base_detail = ctx.prof.init_label or (
        "Init Agent", "Configura dependencias\nde forma automática"
    )
    detail = base_detail if not key_steps else ", ".join(key_steps[:6])

    ctx.graph.add_node(Node(id="init", label=label, detail=detail,
                            node_type=NodeType.PROCESS))


def _parse_run_method(method: ast.FunctionDef | ast.AsyncFunctionDef, ctx: ParseContext, prev_node: str) -> None:
    ctx.graph.add_node(Node(
        id="main_loop", label="Main Loop",
        detail="while True:\n  turn += 1\n  register_evaluation()\n  budget.done()?",
        node_type=NodeType.LOOP,
    ))
    ctx.graph.add_edge(Edge(source=prev_node, target="main_loop"))
    _parse_block(ctx, method.body, "main_loop")


def _parse_block(ctx: ParseContext, stmts: list[ast.stmt], parent_id: str,
                 depth: int = 0) -> str:
    if depth > 10:
        return parent_id

    current = parent_id
    for stmt in stmts:
        if isinstance(stmt, ast.While):
            current = _parse_while(ctx, stmt, current, depth)
        elif isinstance(stmt, ast.If):
            current = _parse_if(ctx, stmt, current, depth)
        elif isinstance(stmt, ast.For):
            current = _parse_for(ctx, stmt, current, depth)
        elif isinstance(stmt, ast.Expr):
            current = _parse_expr_stmt(ctx, stmt, current)
        elif isinstance(stmt, ast.Assign):
            current = _parse_assign(ctx, stmt, current)
        elif isinstance(stmt, ast.Try):
            current = _parse_try(ctx, stmt, current, depth)
        elif hasattr(ast, "Match") and isinstance(stmt, ast.Match):
            current = _parse_match(ctx, stmt, current, depth)
        elif isinstance(stmt, _FUNC_TYPES):
            current = _parse_local_function(stmt, ctx.graph, current)
        elif isinstance(stmt, ast.AsyncFor):
            current = _parse_for(ctx, stmt, current, depth)
        elif isinstance(stmt, ast.AsyncWith):
            current = _parse_block(ctx, stmt.body, current, depth + 1)
    return current


def _parse_while(ctx: ParseContext, stmt: ast.While, parent_id: str, depth: int) -> str:
    loop_id = f"loop_{stmt.lineno}"
    ctx.graph.add_node(Node(id=loop_id, label=_while_label(stmt), node_type=NodeType.LOOP))
    ctx.graph.add_edge(Edge(source=parent_id, target=loop_id))

    last_in_body = _parse_block(ctx, stmt.body, loop_id, depth + 1)
    if last_in_body != loop_id:
        ctx.graph.add_edge(Edge(source=last_in_body, target=loop_id,
                                label=ctx.prof.loop_edge_label))
    return loop_id


def _parse_if(ctx: ParseContext, stmt: ast.If, parent_id: str, depth: int) -> str:
    tool_from_dispatch = _detect_tool_dispatch(stmt, ctx.prof)

    dec_id = f"dec_{stmt.lineno}"
    label, detail = _if_label_and_detail(stmt, ctx.prof)
    ctx.graph.add_node(Node(id=dec_id, label=label, detail=detail,
                            node_type=NodeType.DECISION))
    ctx.graph.add_edge(Edge(source=parent_id, target=dec_id))

    next_parent = dec_id
    if tool_from_dispatch:
        tool_id = f"tool_{tool_from_dispatch}_{stmt.lineno}"
        t_label, t_detail = ctx.prof.tool_names.get(
            tool_from_dispatch, (tool_from_dispatch, "")
        )
        ctx.graph.add_node(Node(
            id=tool_id, label=t_label, detail=t_detail,
            node_type=NodeType.TOOL, line=stmt.lineno,
        ))
        ctx.graph.add_edge(Edge(source=dec_id, target=tool_id, label="YES"))
        next_parent = tool_id

    last_yes = _parse_block(ctx, stmt.body, next_parent, depth + 1)

    if stmt.orelse:
        if len(stmt.orelse) == 1 and isinstance(stmt.orelse[0], ast.If):
            last_no = _parse_if(ctx, stmt.orelse[0], dec_id, depth + 1)
        else:
            last_no = _parse_block(ctx, stmt.orelse, dec_id, depth + 1)
            for e in ctx.graph.edges:
                if e.source == dec_id and e.target == last_yes and not e.label:
                    e.label = "YES"
                elif e.source == dec_id and e.target == last_no and not e.label:
                    e.label = "NO"
        return last_no

    return last_yes


def _detect_tool_dispatch(stmt: ast.If, prof: Profile) -> str | None:
    """Detect ``if <obj>.<dispatch_attr> == "<known tool>"`` patterns."""
    test = stmt.test
    if (
        isinstance(test, ast.Compare)
        and isinstance(test.ops[0], ast.Eq)
        and len(test.comparators) == 1
    ):
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


def _parse_for(ctx: ParseContext, stmt: ast.For | ast.AsyncFor, parent_id: str, depth: int) -> str:
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
    ctx.graph.add_node(Node(id=loop_id, label=label, node_type=NodeType.LOOP))
    ctx.graph.add_edge(Edge(source=parent_id, target=loop_id))

    last_in_body = _parse_block(ctx, stmt.body, loop_id, depth + 1)
    if last_in_body != loop_id:
        ctx.graph.add_edge(Edge(source=last_in_body, target=loop_id,
                                label=ctx.prof.loop_edge_label))
    return loop_id


def _parse_expr_stmt(ctx: ParseContext, stmt: ast.Expr, parent_id: str) -> str:
    inner = _unwrap_call(stmt.value)
    if isinstance(inner, ast.Call):
        call_info = _extract_call_info(inner, ctx.prof)
        if call_info:
            node_id, label, node_type, detail = call_info
            ctx.graph.add_node(Node(
                id=node_id, label=label, detail=detail,
                node_type=node_type, line=stmt.lineno,
            ))
            ctx.graph.add_edge(Edge(source=parent_id, target=node_id))
            return node_id
    return parent_id


def _parse_assign(ctx: ParseContext, stmt: ast.Assign, parent_id: str) -> str:
    inner = _unwrap_call(stmt.value)
    if isinstance(inner, ast.Call):
        call_info = _extract_call_info(inner, ctx.prof)
        if call_info:
            node_id, label, node_type, detail = call_info
            if stmt.targets and isinstance(stmt.targets[0], ast.Name):
                var_name = stmt.targets[0].id
                if not var_name.startswith("_"):
                    label = f"{var_name} = {label}"
            ctx.graph.add_node(Node(
                id=node_id, label=label, detail=detail,
                node_type=node_type, line=stmt.lineno,
            ))
            ctx.graph.add_edge(Edge(source=parent_id, target=node_id))
            return node_id
    return parent_id


def _parse_try(ctx: ParseContext, stmt: ast.Try, parent_id: str, depth: int) -> str:
    last = _parse_block(ctx, stmt.body, parent_id, depth + 1)
    for handler in stmt.handlers:
        last = _parse_block(ctx, handler.body, last, depth + 1)
    if stmt.finalbody:
        last = _parse_block(ctx, stmt.finalbody, last, depth + 1)
    return last


def _parse_match(ctx: ParseContext, stmt: ast.Match, parent_id: str, depth: int) -> str:
    """Parse a match/case statement (Python 3.10+)."""
    subject = ast.unparse(stmt.subject) if hasattr(ast, "unparse") else "value"
    match_id = f"match_{stmt.lineno}"
    ctx.graph.add_node(Node(
        id=match_id, label=f"match {subject}",
        detail=f"structural pattern match\nsubject: {subject}",
        node_type=NodeType.DECISION,
        line=stmt.lineno,
    ))
    ctx.graph.add_edge(Edge(source=parent_id, target=match_id))

    for case in stmt.cases:
        pattern = ast.unparse(case.pattern) if hasattr(ast, "unparse") else "case"
        case_line = case.body[0].lineno if case.body else stmt.lineno
        case_id = f"case_{case_line}"
        ctx.graph.add_node(Node(
            id=case_id, label=f"case {pattern}",
            detail=f"pattern: {pattern}",
            node_type=NodeType.DECISION,
            line=case_line,
        ))
        ctx.graph.add_edge(Edge(source=match_id, target=case_id))
        case_last = _parse_block(ctx, case.body, case_id, depth + 1)
        if case_last != case_id:
            ctx.graph.add_edge(Edge(source=case_last, target=match_id))
    return match_id


def _parse_local_function(method: ast.FunctionDef | ast.AsyncFunctionDef, graph: FlowGraph, parent_id: str) -> str:
    node_id = f"fn_{method.name}_{method.lineno}"
    label = method.name.lstrip("_").replace("_", " ").title()
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


def _parse_function(method: ast.FunctionDef | ast.AsyncFunctionDef, graph: FlowGraph) -> None:
    node_id = f"fn_{method.name}"
    label = method.name.lstrip("_").replace("_", " ").title()
    graph.add_node(Node(id=node_id, label=label, node_type=NodeType.SUBPROCESS,
                        line=method.lineno))
    graph.add_edge(Edge(source="start", target=node_id))


def _scan_handle_eval_for_tools(method: ast.FunctionDef | ast.AsyncFunctionDef, ctx: ParseContext) -> None:
    """Scan _handle_eval_result for tool dispatch patterns and add tool nodes.

    These are tools dispatched from the for-loop body via if/elif chains.
    We connect them to the for-loop node (loop_*) so they appear in the flow.
    """
    for_loop_id = None
    for n in ctx.graph.nodes:
        if n.node_type == NodeType.LOOP and "tool_calls" in n.label.lower():
            for_loop_id = n.id
            break
    if not for_loop_id:
        for_loop_id = "main_loop"

    for node in ast.walk(method):
        if isinstance(node, ast.If):
            tool_name = _detect_tool_dispatch(node, ctx.prof)
            if tool_name and not any(
                n.id.startswith(f"tool_{tool_name}_") for n in ctx.graph.nodes
            ):
                tool_id = f"tool_{tool_name}_{node.lineno}"
                label, detail = ctx.prof.tool_names.get(tool_name, (tool_name, ""))
                ctx.graph.add_node(Node(
                    id=tool_id, label=label, detail=detail,
                    node_type=NodeType.TOOL, line=node.lineno,
                ))
                ctx.graph.add_edge(Edge(source=for_loop_id, target=tool_id,
                                        label="dispatch"))


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

    if isinstance(func, ast.Name) and func.id in prof.tool_names:
        label, detail = prof.tool_names[func.id]
        return (
            f"tool_{func.id}_{call.lineno}",
            label,
            NodeType.TOOL,
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
