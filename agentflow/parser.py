"""Parse Python source code to extract agent control flow.

Uses Python's ast module to analyze the control flow of an agent class
and produce a FlowGraph with nodes (processes, decisions, tools) and
edges (flow connections with labels).

Labels are EXHAUSTIVE: each node includes its parameters, thresholds,
conditions, and what it does — not just a name.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path
from typing import Optional

from agentflow.models import Edge, FlowGraph, Node, NodeType


# ── Pattern matching helpers ──────────────────────────────────────────

TOOL_NAMES = {
    "generate_candidate", "audit_page", "audit_visual", "audit_creative",
    "audit_truth", "revert_workspace", "select_final", "update_lessons",
    "fetch_readme", "fetch_repo_topics",
    "inspect_archetype", "analyze_project", "deploy_preview", "git_snapshot",
}

# ── Auto-evolution patterns ────────────────────────────────────────

AUTO_EVOLUTION_METHODS = {
    "_maybe_auto_lesson", "_maybe_subtask_lesson", "_maybe_content_lesson",
    "_auto_truth_audit", "_auto_visual_audit", "_compute_novelty",
}
META_EDIT_TOOLS = {"edit_skill", "review_harness"}
CONTEXT_METHODS = {"_compact", "should_compact"}

# ── Exhaustive node labels ──────────────────────────────────────────
# Each entry: (label, detail) — label is the name, detail is params/what-it-does

TOOL_INFO: dict[str, tuple[str, str]] = {
    "generate_candidate": (
        "Generate Candidate",
        "LLM sub-agent genera HTML/CSS/JS\nexploration=True, target_h=0..N",
    ),
    "audit_page": (
        "Audit Page",
        "Validación estática: SEO, A11y,\nPerf, Responsive, Best Practices",
    ),
    "audit_visual": (
        "Audit Visual",
        "VLM Gemini: screenshot → score 0-100\n+ issues + suggestions",
    ),
    "audit_creative": (
        "Audit Creative",
        "VLM anti-proxy: novedad/originalidad\nscore 0-100, mutation hints",
    ),
    "audit_truth": (
        "Audit Truth",
        "Partes huérfanas, enlaces rotos,\nreferencias vs diseño real",
    ),
    "revert_workspace": (
        "Revert Workspace",
        "Restaura candidato anterior\nsi el nuevo empeora",
    ),
    "select_final": (
        "Select Final",
        "Selecciona mejor candidato\ny exporta a runs/{run_id}/final/",
    ),
    "update_lessons": (
        "Update Lessons",
        "Persiste lecciones acumuladas\na memory/global_lessons",
    ),
    "fetch_readme": (
        "Fetch README",
        "Descarga README de GitHub\n→ genera página HTML por repo",
    ),
    "fetch_repo_topics": (
        "Fetch Repo Topics",
        "Clasifica repos vía LLM\n→ genera graph_data.json",
    ),
    "inspect_archetype": (
        "Inspect Archetype",
        "Analiza estructura del archetype\npluck + archetype_name",
    ),
    "analyze_project": (
        "Analyze Project",
        "Análisis completo del proyecto\nstack, estructura, dependencias",
    ),
    "deploy_preview": (
        "Deploy Preview",
        "http.server en puerto 8000\npara preview local",
    ),
    "git_snapshot": (
        "Git Snapshot",
        "Copia candidato a runs/\npara historial de versiones",
    ),
}

EVO_INFO: dict[str, tuple[str, str]] = {
    "_maybe_auto_lesson": (
        "Auto Lesson",
        "delta ≥ 4.0 → aprende worked/didnt\nmax 8/run, dedup por snippet",
    ),
    "_maybe_subtask_lesson": (
        "Subtask Lesson",
        "Detecta subtask fail→pass\n(prev best vs candidato actual)",
    ),
    "_maybe_content_lesson": (
        "Content Lesson",
        "VLM score < 85 → extrae issues\ny suggestions como lecciones",
    ),
    "_auto_truth_audit": (
        "Auto Truth Audit",
        "1 vez/run: partes conectadas\nrepo linking, broken refs",
    ),
    "_auto_visual_audit": (
        "Auto Visual Audit",
        "Post-generate: VLM screenshot\nevalúa calidad visual 0-100",
    ),
    "_compute_novelty": (
        "Compute Novelty",
        "DOM(0.45) + palette(0.35)\n+ JS(0.20) vs best previous",
    ),
}


def parse_file(filepath: str | Path) -> FlowGraph:
    """Parse a Python file and extract the agent flow graph."""
    path = Path(filepath)
    source = path.read_text(encoding="utf-8")
    graph = parse_source(source, title=f"Flow: {path.stem}")
    return graph


def parse_source(source: str, title: str = "Agent Flow") -> FlowGraph:
    """Parse Python source code and extract the agent flow graph."""
    tree = ast.parse(source)
    graph = FlowGraph(title=title)

    graph.add_node(Node(
        id="start", label="Start", detail="Agent.run() invoked\nbudget.start()",
        node_type=NodeType.START,
    ))

    agent_cls = _find_agent_class(tree)
    if agent_cls:
        _parse_agent_class(agent_cls, graph)
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

    return graph


# ── Class/method parsing ──────────────────────────────────────────────


def _find_agent_class(tree: ast.Module) -> Optional[ast.ClassDef]:
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef):
            name_lower = node.name.lower()
            if "agent" in name_lower or any(
                isinstance(item, ast.FunctionDef) and item.name == "run"
                for item in node.body
            ):
                return node
    return None


def _parse_agent_class(cls: ast.ClassDef, graph: FlowGraph) -> None:
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
        _parse_init(init_method, graph)

    if init_method:
        graph.add_edge(Edge(source="start", target="init", label=""))
        prev_node = "init"
    else:
        graph.add_edge(Edge(source="start", target="main_loop", label=""))
        prev_node = "start"

    if run_method:
        _parse_run_method(run_method, graph, prev_node)

        # Also scan _handle_eval_result for tool dispatch patterns
        if handle_eval:
            _scan_handle_eval_for_tools(handle_eval, graph)
    else:
        for item in cls.body:
            if isinstance(item, ast.FunctionDef) and item.name != "__init__":
                _parse_function(item, graph)
                break


def _parse_init(method: ast.FunctionDef, graph: FlowGraph) -> None:
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
    label = "Init Agent"
    detail = "Configura LLM, budget, memory,\ncontext manager, harness snapshot"
    if key_steps:
        detail = ", ".join(key_steps[:6])

    graph.add_node(Node(id="init", label=label, detail=detail, node_type=NodeType.PROCESS))


def _parse_run_method(method: ast.FunctionDef, graph: FlowGraph, prev_node: str) -> None:
    graph.add_node(Node(
        id="main_loop", label="Main Loop",
        detail="while True:\n  turn += 1\n  register_evaluation()\n  budget.done()?",
        node_type=NodeType.LOOP,
    ))
    graph.add_edge(Edge(source=prev_node, target="main_loop"))
    _parse_block(method.body, graph, parent_id="main_loop")


def _parse_block(
    stmts: list[ast.stmt],
    graph: FlowGraph,
    parent_id: str,
    depth: int = 0,
) -> str:
    if depth > 10:
        return parent_id

    current = parent_id

    for stmt in stmts:
        if isinstance(stmt, ast.While):
            current = _parse_while(stmt, graph, current, depth)
        elif isinstance(stmt, ast.If):
            current = _parse_if(stmt, graph, current, depth)
        elif isinstance(stmt, ast.For):
            current = _parse_for(stmt, graph, current, depth)
        elif isinstance(stmt, ast.Expr):
            current = _parse_expr_stmt(stmt, graph, current)
        elif isinstance(stmt, ast.Assign):
            current = _parse_assign(stmt, graph, current)
        elif isinstance(stmt, ast.Try):
            current = _parse_try(stmt, graph, current, depth)
        elif isinstance(stmt, ast.FunctionDef):
            current = _parse_local_function(stmt, graph, current)

    return current


def _parse_while(
    stmt: ast.While, graph: FlowGraph, parent_id: str, depth: int
) -> str:
    loop_id = f"loop_{stmt.lineno}"
    graph.add_node(Node(id=loop_id, label=_while_label(stmt), node_type=NodeType.LOOP))
    graph.add_edge(Edge(source=parent_id, target=loop_id))

    last_in_body = _parse_block(stmt.body, graph, loop_id, depth + 1)

    if last_in_body != loop_id:
        graph.add_edge(Edge(source=last_in_body, target=loop_id, label="loop"))

    return loop_id


def _parse_if(
    stmt: ast.If, graph: FlowGraph, parent_id: str, depth: int
) -> str:
    tool_from_dispatch = _detect_tool_dispatch(stmt)

    dec_id = f"dec_{stmt.lineno}"
    label, detail = _if_label_and_detail(stmt)
    graph.add_node(Node(id=dec_id, label=label, detail=detail, node_type=NodeType.DECISION))
    graph.add_edge(Edge(source=parent_id, target=dec_id))

    if tool_from_dispatch:
        tool_id = f"tool_{tool_from_dispatch}_{stmt.lineno}"
        t_label, t_detail = TOOL_INFO.get(tool_from_dispatch, (tool_from_dispatch, ""))
        graph.add_node(Node(
            id=tool_id, label=t_label, detail=t_detail,
            node_type=NodeType.TOOL, line=stmt.lineno,
        ))
        graph.add_edge(Edge(source=dec_id, target=tool_id, label="YES"))

    last_yes = _parse_block(stmt.body, graph, tool_id if tool_from_dispatch else dec_id, depth + 1)

    if stmt.orelse:
        if len(stmt.orelse) == 1 and isinstance(stmt.orelse[0], ast.If):
            last_no = _parse_if(stmt.orelse[0], graph, dec_id, depth + 1)
        else:
            last_no = _parse_block(stmt.orelse, graph, dec_id, depth + 1)
            for e in graph.edges:
                if e.source == dec_id and e.target == last_yes and not e.label:
                    e.label = "YES"
                elif e.source == dec_id and e.target == last_no and not e.label:
                    e.label = "NO"

        return last_no
    else:
        return last_yes


def _detect_tool_dispatch(stmt: ast.If) -> Optional[str]:
    test = stmt.test
    if not isinstance(test, ast.Compare):
        return None
    if not isinstance(test.ops[0], ast.Eq):
        return None
    if len(test.comparators) != 1:
        return None

    left = test.left
    if not isinstance(left, ast.Attribute) or left.attr != "name":
        return None

    comparator = test.comparators[0]
    if not isinstance(comparator, ast.Constant) or not isinstance(comparator.value, str):
        return None

    tool_name = comparator.value
    if tool_name in TOOL_NAMES:
        return tool_name
    return None


def _parse_for(
    stmt: ast.For, graph: FlowGraph, parent_id: str, depth: int
) -> str:
    loop_id = f"loop_{stmt.lineno}"
    # Improve the for-loop label
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
        label = f"For loop"
    graph.add_node(Node(id=loop_id, label=label, node_type=NodeType.LOOP))
    graph.add_edge(Edge(source=parent_id, target=loop_id))

    last_in_body = _parse_block(stmt.body, graph, loop_id, depth + 1)
    if last_in_body != loop_id:
        graph.add_edge(Edge(source=last_in_body, target=loop_id, label="loop"))

    return loop_id


def _parse_expr_stmt(
    stmt: ast.Expr, graph: FlowGraph, parent_id: str
) -> str:
    if isinstance(stmt.value, ast.Call):
        call_info = _extract_call_info(stmt.value)
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
    stmt: ast.Assign, graph: FlowGraph, parent_id: str
) -> str:
    if isinstance(stmt.value, ast.Call):
        call_info = _extract_call_info(stmt.value)
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
    stmt: ast.Try, graph: FlowGraph, parent_id: str, depth: int
) -> str:
    last = _parse_block(stmt.body, graph, parent_id, depth + 1)

    for handler in stmt.handlers:
        last = _parse_block(handler.body, graph, last, depth + 1)

    if stmt.finalbody:
        last = _parse_block(stmt.finalbody, graph, last, depth + 1)

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


def _parse_function(
    method: ast.FunctionDef, graph: FlowGraph
) -> None:
    node_id = f"fn_{method.name}"
    label = method.name.lstrip("_").replace("_", " ").title()
    graph.add_node(Node(id=node_id, label=label, node_type=NodeType.SUBPROCESS, line=method.lineno))
    graph.add_edge(Edge(source="start", target=node_id))


def _scan_handle_eval_for_tools(method: ast.FunctionDef, graph: FlowGraph) -> None:
    """Scan _handle_eval_result for tool dispatch patterns and add tool nodes.

    These are tools dispatched from the for-loop body via if/elif chains.
    We connect them to the for-loop node (loop_*) so they appear in the flow.
    """
    # Find the for-loop node (the tool_calls iterator)
    for_loop_id = None
    for n in graph.nodes:
        if n.node_type == NodeType.LOOP and "tool_calls" in n.label.lower():
            for_loop_id = n.id
            break
    if not for_loop_id:
        for_loop_id = "main_loop"

    for node in ast.walk(method):
        if isinstance(node, ast.If):
            tool_name = _detect_tool_dispatch(node)
            if tool_name and not any(n.id.startswith(f"tool_{tool_name}_") for n in graph.nodes):
                tool_id = f"tool_{tool_name}_{node.lineno}"
                label, detail = TOOL_INFO.get(tool_name, (tool_name, ""))
                graph.add_node(Node(
                    id=tool_id, label=label, detail=detail,
                    node_type=NodeType.TOOL, line=node.lineno,
                ))
                # Connect from the for-loop (tools are dispatched inside the loop)
                graph.add_edge(Edge(source=for_loop_id, target=tool_id, label="dispatch"))


# ── Label + detail extraction ───────────────────────────────────────


def _extract_call_info(call: ast.Call) -> Optional[tuple[str, str, NodeType, str]]:
    """Extract (node_id, label, type, detail) from a function call."""
    func = call.func

    if isinstance(func, ast.Attribute):
        method_name = func.attr

        # Tool calls — exhaustive labels
        if method_name in TOOL_NAMES:
            label, detail = TOOL_INFO.get(method_name, (method_name, ""))
            return (
                f"tool_{method_name}_{call.lineno}",
                label,
                NodeType.TOOL,
                detail,
            )

        # Auto-evolution methods
        if method_name in AUTO_EVOLUTION_METHODS:
            label, detail = EVO_INFO.get(method_name, (method_name, ""))
            return (
                f"evo_{method_name}_{call.lineno}",
                label,
                NodeType.EVOLUTION,
                detail,
            )

        # Meta-edit tools
        if method_name in META_EDIT_TOOLS:
            return (
                f"meta_{method_name}_{call.lineno}",
                f"Meta-Edit: {method_name}",
                NodeType.EVOLUTION,
                "Propone cambio al harness\nacepta/revierte vía gate_harness_edit",
            )

        # Context compaction
        if method_name in CONTEXT_METHODS:
            return (
                f"ctx_{method_name}_{call.lineno}",
                "Context Compaction",
                NodeType.EVOLUTION,
                "tokens > 60000 → compacta\nresumen + lessons persistentes",
            )

        # Internal methods
        if method_name == "_snapshot":
            return (
                f"snapshot_{call.lineno}",
                "Snapshot Workspace",
                NodeType.PROCESS,
                "Copia workspace/ → candidates/{id}/\npara historial de cambios",
            )
        if method_name == "_seed_from_workspace":
            return (
                f"seed_{call.lineno}",
                "Seed Workspace",
                NodeType.PROCESS,
                "Si workspace/current existe\n→ evalúa como H0 inicial",
            )
        if method_name == "_export_final":
            return (
                f"export_{call.lineno}",
                "Export Final",
                NodeType.END,
                "Copia mejor candidato a\nruns/{run_id}/final/index.html",
            )
        if method_name == "_render_state":
            return (
                f"state_{call.lineno}",
                "Render State",
                NodeType.PROCESS,
                "Genera prompt con: turn, cost,\nbest, tree, lessons, stagnation",
            )
        if method_name == "_sync_budget_cost":
            return None

    if isinstance(func, ast.Name):
        func_name = func.id
        if func_name in ("evaluate", "render_screenshot", "novelty_score"):
            return (
                f"fn_{func_name}_{call.lineno}",
                func_name,
                NodeType.TOOL,
                "",
            )

    return None


def _if_label_and_detail(stmt: ast.If) -> tuple[str, str]:
    """Generate exhaustive label + detail for an if statement."""
    test = stmt.test

    # budget.done()
    if isinstance(test, ast.Call):
        func = test.func
        if isinstance(func, ast.Attribute):
            if func.attr == "done":
                return (
                    "Budget\ndone?",
                    "turns ≥ 24 OR cost ≥ $5.00\nOR stagnation ≥ 16 OR time ≥ 120min",
                )
            if func.attr == "register_evaluation":
                return (
                    "Register\nscore?",
                    "score - last_best ≥ 2%?\n→ reset stagnation counter",
                )
            if func.attr == "should_compact":
                return (
                    "Compact\ncontext?",
                    "tokens > 60000?\n(solo 1 vez por run)",
                )
        # Detect any(k in text.lower() for k in ("done", "fin", ...))
        if isinstance(func, ast.Name) and func.id == "any":
            try:
                raw = ast.dump(test)
                if "value='done'" in raw and "value='fin'" in raw:
                    return (
                        "Agent said\ndone?",
                        "¿Agente dijo done/fin/finalizado?\n→ terminar si alcanzó target_h",
                    )
            except Exception:
                pass
        if isinstance(func, ast.Name):
            if func.id == "stop_reason":
                return (
                    "Stop\nreason?",
                    "Agente dijo done/fin?\nO budget agotado?",
                )

    # tool_calls check
    if isinstance(test, ast.Attribute):
        if test.attr in ("tool_calls",):
            return (
                "Has tool\ncalls?",
                "LLM devolvió tool_calls?\n→ iterar sobre cada una",
            )
        if test.attr in ("nodes",):
            return (
                "Has nodes?",
                "Search tree tiene nodos?\n→ evaluar candidato",
            )

    # Comparisons
    if isinstance(test, ast.Compare):
        left = test.left
        if isinstance(left, ast.Name):
            if left.id == "stop_reason":
                return (
                    "Stop\nreason?",
                    "Motivo de parada?\nbudget/stagnation/agent-decided",
                )
            if left.id == "delta":
                return (
                    "Delta >\nthreshold?",
                    "Mejora > umbral?\n→ aprender lección",
                )

        # Detect tool name comparisons: call.name == "tool_name"
        if isinstance(left, ast.Attribute) and left.attr == "name":
            for comp in test.comparators:
                if isinstance(comp, ast.Constant) and isinstance(comp.value, str):
                    tool_name = comp.value
                    if tool_name in TOOL_INFO:
                        label, detail = TOOL_INFO[tool_name]
                        return (f"Tool:\n{tool_name}?", detail)
                    return (f"Tool:\n{tool_name}?", f"Dispatch {tool_name}")

        # Detect: node_id is not None / node_id in ...
        if isinstance(left, ast.Name) and left.id == "node_id":
            return (
                "node_id\nvalid?",
                "¿Se generó nodo?\n→ evaluar resultado",
            )

    # Boolean ops
    if isinstance(test, ast.BoolOp):
        # Try to detect specific patterns in BoolOp
        for val in test.values:
            if isinstance(val, ast.Compare):
                left = val.left
                if isinstance(left, ast.Name) and left.id == "node_id":
                    return (
                        "node_id valid\n+ tool check?",
                        "Nodo existe y\nherramienta relevante?",
                    )
        return (
            "Condition\ncheck?",
            "Múltiples condiciones\nAND/OR combinadas",
        )

    # Name
    if isinstance(test, ast.Name):
        return (
            f"{test.id}?",
            f"Verifica {test.id}\nen contexto actual",
        )

    # Not
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        if isinstance(test.operand, ast.Attribute):
            return (
                f"NOT {test.operand.attr}?",
                f"Niega {test.operand.attr}\npara lógica invertida",
            )

    # Fallback with raw analysis
    try:
        raw = ast.dump(test)
        if "stop_reason" in raw:
            return (
                "Stop\nreason?",
                "Motivo de parada?\nbudget/stagnation/agent-decided",
            )
        if "budget" in raw:
            return (
                "Budget\ncheck?",
                "turns ≥ 24 OR cost ≥ $5.00\nOR stagnation ≥ 16",
            )
        if "tool_calls" in raw:
            return (
                "Has tool\ncalls?",
                "LLM devolvió tool_calls?\n→ iterar sobre cada una",
            )
        if "target_h" in raw:
            return (
                "Target H\nreached?",
                "hypothesis_count ≤ target_h?\n→ continuar generando",
            )
        if "meta_edits" in raw or "allow_meta" in raw:
            return (
                "Meta-edits\nenabled?",
                "allow_meta_edits = True?\n→ permitir edit_skill",
            )
        # Detect "done"/"fin" keyword checks in text
        if '"done"' in raw or '"fin"' in raw or '"finalizado"' in raw:
            return (
                "Agent said\ndone?",
                "¿Agente dijo done/fin/finalizado?\n→ terminar si alcanzó target_h",
            )
        # Detect incremental/memory operations
        if "incremental" in raw or "global_lessons" in raw:
            return (
                "Lessons\nto merge?",
                "¿Hay lecciones incrementales?\n→ merge a global_lessons",
            )
        # Detect node_id checks
        if "node_id" in raw:
            return (
                "node_id\nvalid?",
                "¿Se generó nodo válido?\n→ evaluar resultado",
            )
    except Exception:
        pass

    return ("Condition?", "Condición no identificada")


def _while_label(stmt: ast.While) -> str:
    test = stmt.test

    if isinstance(test, ast.Constant) and test.value is True:
        return "Main Loop\n(while True)"

    if isinstance(test, ast.Name):
        return f"while {test.id}"

    return "Loop"
