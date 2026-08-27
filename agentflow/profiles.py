"""Domain profiles for the AgentFlow parser.

A Profile carries all domain-specific knowledge used while parsing agent
source code: known tool names, exhaustive labels, auto-evolution methods,
decision hints and phase patterns. The parser itself is domain-agnostic.

Built-in profiles are provided:
- GENERIC: no domain knowledge — labels derive from the code itself.
- REAWEB: exhaustive labels for the ReaWeb self-evolving web-design agent.
- REAGAME: exhaustive labels for the ReaGame self-evolving game-design agent.
- TRACEFORGE: labels for the TraceForge LLM-tracing library.
- ASUBARNIPAL: labels for the Asubarnipal wiki/RAG assistant (Telegram + FastAPI).
- COGNITEAM: labels for the CogniTeam multi-agent orchestration framework.
- AGENTFLOW: labels for this tool itself (parse → layout → render pipelines).

Custom profiles can be loaded from an external Python file exposing a
``PROFILE`` dict (see :func:`load_profile`).
"""

from __future__ import annotations

import importlib.util
from dataclasses import dataclass, field
from pathlib import Path

from agentflow.models import NodeType


@dataclass
class Profile:
    """Domain knowledge for parsing a family of agents."""

    name: str = "generic"

    # Method names recognized as tool calls → (label, detail)
    tool_names: dict[str, tuple[str, str]] = field(default_factory=dict)

    # Internal method names with special meaning → (label, detail, node_type)
    special_calls: dict[str, tuple[str, str, NodeType]] = field(default_factory=dict)

    # Auto-evolution methods → (label, detail); rendered as EVOLUTION nodes
    evolution_methods: dict[str, tuple[str, str]] = field(default_factory=dict)

    # Attribute names checked in ``x.attr == "name"`` dispatch patterns
    dispatch_attr: str = "name"

    # Decision label overrides: substring of the raw AST dump → (label, detail)
    decision_hints: list[tuple[str, str, str]] = field(default_factory=list)

    # Node id/label substrings → phase number (for phased layout)
    phase_patterns: dict[str, int] = field(default_factory=dict)

    # Init node label/detail override; None → derive from assignments
    init_label: tuple[str, str] | None = None

    # Loop-back edge label (e.g. "loop")
    loop_edge_label: str = "loop"

    # Framework-specific agent class names (for instance-to-actor mapping)
    # e.g. {"AgentExecutor": "Agent", "Crew": "Orchestrator"}
    agent_class_names: dict[str, str] = field(default_factory=dict)

    # Drill-down: dotted module path -> [(group label, [function/method names])].
    # Files listed here are split into one flowchart per group instead of being
    # emitted whole as a single diagram (see agentflow.drilldown).
    function_splits: dict[str, list[tuple[str, list[str]]]] = field(default_factory=dict)

    # Drill-down: dotted module path -> [class names to expand, one diagram each].
    class_splits: dict[str, list[str]] = field(default_factory=dict)


# ── Generic profile ───────────────────────────────────────────────────

GENERIC_PROFILE = Profile(name="generic")


# ── ReaWeb profile ────────────────────────────────────────────────────

_REAWEB_TOOL_INFO: dict[str, tuple[str, str]] = {
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

_REAWEB_EVO_INFO: dict[str, tuple[str, str]] = {
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

_REAWEB_SPECIAL_CALLS: dict[str, tuple[str, str, NodeType]] = {
    "_snapshot": (
        "Snapshot Workspace",
        "Copia workspace/ → candidates/{id}/\npara historial de cambios",
        NodeType.PROCESS,
    ),
    "_seed_from_workspace": (
        "Seed Workspace",
        "Si workspace/current existe\n→ evalúa como H0 inicial",
        NodeType.PROCESS,
    ),
    "_export_final": (
        "Export Final",
        "Copia mejor candidato a\nruns/{run_id}/final/index.html",
        NodeType.END,
    ),
    "_render_state": (
        "Render State",
        "Genera prompt con: turn, cost,\nbest, tree, lessons, stagnation",
        NodeType.PROCESS,
    ),
    "_sync_budget_cost": ("", "", NodeType.PROCESS),  # skipped by parser
    "edit_skill": (
        "Meta-Edit: edit_skill",
        "Propone cambio al harness\nacepta/revierte vía gate_harness_edit",
        NodeType.EVOLUTION,
    ),
    "review_harness": (
        "Meta-Edit: review_harness",
        "Propone cambio al harness\nacepta/revierte vía gate_harness_edit",
        NodeType.EVOLUTION,
    ),
    "_compact": (
        "Context Compaction",
        "tokens > 60000 → compacta\nresumen + lessons persistentes",
        NodeType.EVOLUTION,
    ),
    "should_compact": (
        "Context Compaction",
        "tokens > 60000 → compacta\nresumen + lessons persistentes",
        NodeType.EVOLUTION,
    ),
}

# Substring of AST dump → (label, detail) for known decisions
_REAWEB_DECISION_HINTS: list[tuple[str, str, str]] = [
    ("attr='done'", "Budget\ndone?",
     "turns ≥ 24 OR cost ≥ $5.00\nOR stagnation ≥ 16 OR time ≥ 120min"),
    ("register_evaluation", "Register\nscore?",
     "score - last_best ≥ 2%?\n→ reset stagnation counter"),
    ("should_compact", "Compact\ncontext?",
     "tokens > 60000?\n(solo 1 vez por run)"),
    ("value='done'", "Agent said\ndone?",
     "¿Agente dijo done/fin/finalizado?\n→ terminar si alcanzó target_h"),
    ("stop_reason", "Stop\nreason?",
     "Motivo de parada?\nbudget/stagnation/agent-decided"),
    ("tool_calls", "Has tool\ncalls?",
     "LLM devolvió tool_calls?\n→ iterar sobre cada una"),
    ("id='nodes'", "Has nodes?",
     "Search tree tiene nodos?\n→ evaluar candidato"),
    ("id='delta'", "Delta >\nthreshold?",
     "Mejora > umbral?\n→ aprender lección"),
    ("target_h", "Target H\nreached?",
     "hypothesis_count ≤ target_h?\n→ continuar generando"),
    ("meta_edits", "Meta-edits\nenabled?",
     "allow_meta_edits = True?\n→ permitir edit_skill"),
    ("global_lessons", "Lessons\nto merge?",
     "¿Hay lecciones incrementales?\n→ merge a global_lessons"),
]

_REAWEB_PHASE_PATTERNS: dict[str, int] = {
    "start": 1,
    "init": 1,
    "seed": 1,
    "decision_url": 1,
    "fetch_url": 1,
    "main_loop": 2,
    "render": 2,
    "llm": 2,
    "budget": 2,
    "generate": 2,
    "audit": 2,
    "truth": 2,
    "revert": 2,
    "vlm": 2,
    "creative": 2,
    "lesson": 2,
    "subtask_lesson": 2,
    "content_lesson": 2,
    "truth_audit": 2,
    "visual_audit": 2,
    "novelty": 2,
    "compact": 2,
    "snapshot": 2,
    "select": 3,
    "export": 3,
    "final": 3,
    "end": 3,
    "meta": 3,
    "harm": 3,
    "summary": 3,
}


# Drill-down splits: dotted module path -> [(group label, [function names])].
_REAWEB_FUNCTION_SPLITS: dict[str, list[tuple[str, list[str]]]] = {
    "agent.agent": [
        ("Init", [
            "__init__", "_system_prompt", "_snapshot", "_snapshot_workspace",
            "_workspace_diff_summary", "_stash_vlm", "_render_state",
        ]),
        ("Iterations", [
            "_handle_eval_result", "_last_action_summary", "_subtask_checklist",
            "_safe_history_slice", "_exec_tool",
        ]),
        ("Lessons", [
            "_maybe_subtask_lesson", "_maybe_auto_lesson", "_maybe_content_lesson",
        ]),
        ("Audits", [
            "_auto_truth_audit", "_auto_visual_audit", "_compute_novelty",
            "_attribute_harm",
        ]),
        ("Finalize", [
            "_seed_from_workspace", "_export_final", "_current_best_score",
        ]),
    ],
    "tools.domain.evaluator": [
        ("Gating", ["evaluate", "_apply_blocking_gates"]),
        ("Scoring", ["_score", "_strip_js_comments"]),
        ("VisualTotal", ["blend_visual_total"]),
        ("RequirementsSections", [
            "extract_requirements", "extract_sections", "_html_has_section",
        ]),
        ("Subtasks", [
            "extract_subtasks", "subtasks_status", "format_subtasks_status",
        ]),
        ("Novelty", ["novelty_score", "_jaccard", "_palette", "_dom_structure"]),
        ("VisualChecks", [
            "_has_real_css_animations", "_has_real_transitions",
            "_has_real_gradients", "_has_animated_canvas", "_no_dead_canvas",
            "_has_dark_mode", "_has_scroll_reveal", "_has_hover_effects",
            "_has_microinteractions", "_has_content_richness", "_inputs_labeled",
            "_has_modern_images", "_scripts_async", "_img_responsive",
        ]),
    ],
    "scripts.trend_evolution": [
        ("Data", ["_baseline", "collect"]),
        ("Render", ["render_markdown", "_fmt_num"]),
        ("Entry", ["main"]),
    ],
    "scripts.run_benchmark": [
        ("Load", ["_baseline", "load_benchmark"]),
        ("Render", ["render", "_f"]),
        ("Suite", ["_run_suite"]),
        ("Leaderboard", ["_write_leaderboard"]),
        ("Entry", ["main"]),
    ],
}

_REAWEB_CLASS_SPLITS: dict[str, list[str]] = {
    "tools.domain.web_generator": [
        "InspectArchetype", "FetchUrl", "GenerateCandidate", "AuditPage",
        "UpdateLessons", "SelectFinal", "RevertWorkspace",
    ],
}

REAWEB_PROFILE = Profile(
    name="reaweb",
    tool_names=_REAWEB_TOOL_INFO,
    special_calls=_REAWEB_SPECIAL_CALLS,
    evolution_methods=_REAWEB_EVO_INFO,
    dispatch_attr="name",
    decision_hints=_REAWEB_DECISION_HINTS,
    phase_patterns=_REAWEB_PHASE_PATTERNS,
    init_label=("Init Agent", "Configura LLM, budget, memory,\ncontext manager, harness snapshot"),
    function_splits=_REAWEB_FUNCTION_SPLITS,
    class_splits=_REAWEB_CLASS_SPLITS,
)


# ── ReaGame profile ───────────────────────────────────────────────────

_REAGAME_TOOL_INFO: dict[str, tuple[str, str]] = {
    "generate_candidate": (
        "Generate Candidate",
        "LLM sub-agente genera un juego Godot\n(scripts .gd + assets) → hipótesis H0..Hn",
    ),
    "audit_page": (
        "Audit Game",
        "Validación estática del juego: features\nextraídas, controles, conectividad, gates",
    ),
    "audit_visual": (
        "Audit Visual",
        "VLM: captura del juego → score 0-100\n+ issues + sugerencias de arte/nivel",
    ),
    "audit_creative": (
        "Audit Creative",
        "VLM anti-proxy: novedad/originalidad\nscore 0-100, hints de mutación",
    ),
    "inspect_archetype": (
        "Inspect Archetype",
        "Analiza el archetype de juego\n(schema de archivos/features requeridos)",
    ),
    "update_lessons": (
        "Update Lessons",
        "Persiste lecciones acumuladas\na memory/global_lessons",
    ),
    "select_final": (
        "Select Final",
        "Selecciona mejor hipótesis\ny exporta a runs/{run_id}/final/",
    ),
    "revert_workspace": (
        "Revert Workspace",
        "Restaura el candidato anterior\nsi el nuevo empeora",
    ),
    "edit_skill": (
        "Meta-Edit: edit_skill",
        "Propone cambio al harness\nacepta/revierte vía gate_harness_edit",
    ),
    "review_harness": (
        "Meta-Edit: review_harness",
        "Propone cambio al harness\nacepta/revierte vía gate_harness_edit",
    ),
    "deploy_preview": (
        "Deploy Preview",
        "Empaqueta/preview del juego\n(export o http.server local)",
    ),
    "git_snapshot": (
        "Git Snapshot",
        "Copia candidato a runs/\npara historial de versiones",
    ),
}

_REAGAME_EVO_INFO: dict[str, tuple[str, str]] = {
    "_maybe_auto_lesson": (
        "Auto Lesson",
        "delta ≥ umbral → aprende worked/didnt\nmax por run, dedup por snippet",
    ),
    "_maybe_subtask_lesson": (
        "Subtask Lesson",
        "Detecta subtask fail→pass\n(prev best vs candidato actual)",
    ),
    "_maybe_content_lesson": (
        "Content Lesson",
        "Score < 85 → extrae issues\ny suggestions como lecciones",
    ),
    "_compute_novelty": (
        "Compute Novelty",
        "Hash de archivos + Jaccard vs\nmejores hipótesis previas",
    ),
    "_attribute_harm": (
        "Attribute Harm",
        "Detecta contenido/deficiencias graves\ny penaliza la hipótesis",
    ),
}

_REAGAME_SPECIAL_CALLS: dict[str, tuple[str, str, NodeType]] = {
    "_snapshot": (
        "Snapshot Workspace",
        "Copia workspace/ → candidates/{id}/\npara historial de cambios",
        NodeType.PROCESS,
    ),
    "_seed_from_workspace": (
        "Seed Workspace",
        "Si workspace/current existe\n→ evalúa como H0 inicial",
        NodeType.PROCESS,
    ),
    "_export_final": (
        "Export Final",
        "Copia mejor candidato a\nruns/{run_id}/final/",
        NodeType.END,
    ),
    "_render_state": (
        "Render State",
        "Genera prompt con: turn, cost,\nbest, tree, lessons, stagnation",
        NodeType.PROCESS,
    ),
    "_sync_budget_cost": ("", "", NodeType.PROCESS),
}

_REAGAME_DECISION_HINTS: list[tuple[str, str, str]] = [
    ("attr='done'", "Task\ndone?",
     "¿Agente devolvió done/fin/finalizado?\n→ terminar si alcanzó target_h"),
    ("register_evaluation", "Stagnation\nreset?",
     "score - last_best ≥ umbral?\n→ reset del contador de estancamiento"),
    ("stop_reason", "Stop\nreason?",
     "Motivo de parada?\nbudget/stagnation/agent-decided"),
    ("tool_calls", "Has tool\ncalls?",
     "LLM devolvió tool_calls?\n→ iterar sobre cada una"),
    ("target_h", "Target H\nreached?",
     "hypothesis_count ≤ target_h?\n→ seguir generando hipótesis"),
    ("meta_edits", "Meta-edits\nenabled?",
     "allow_meta_edits = True?\n→ permitir edit_skill"),
    ("delta_threshold", "Delta ≥\numbral?",
     "Mejora suficiente?\n→ aprender lección"),
    ("should_compact", "Compact\ncontext?",
     "tokens > umbral?\n→ compactar contexto (1 vez/run)"),
    ("attr='nodes'", "Has nodes?",
     "Search tree tiene nodos?\n→ evaluar candidato"),
    ("global_lessons", "Lessons\nto merge?",
     "¿Hay lecciones incremental?\n→ merge a global_lessons"),
]

_REAGAME_PHASE_PATTERNS: dict[str, int] = {
    "start": 1,
    "init": 1,
    "seed": 1,
    "main_loop": 2,
    "render": 2,
    "llm": 2,
    "budget": 2,
    "generate": 2,
    "audit": 2,
    "vlm": 2,
    "creative": 2,
    "lesson": 2,
    "subtask_lesson": 2,
    "content_lesson": 2,
    "novelty": 2,
    "snapshot": 2,
    "select": 3,
    "export": 3,
    "final": 3,
    "end": 3,
    "meta": 3,
    "harm": 3,
    "summary": 3,
}

_REAGAME_FUNCTION_SPLITS: dict[str, list[tuple[str, list[str]]]] = {
    "agent.agent": [
        ("Init", [
            "__init__", "_system_prompt", "_log", "_snapshot", "_render_state",
        ]),
        ("Iterations", [
            "_last_action_summary", "_subtask_checklist", "_safe_history_slice",
            "_exec_tool", "_handle_eval_result",
        ]),
        ("Lessons", [
            "_maybe_subtask_lesson", "_maybe_auto_lesson", "_maybe_content_lesson",
        ]),
        ("Audits", [
            "_compute_novelty", "_attribute_harm", "_smoke",
        ]),
        ("Finalize", [
            "_seed_from_workspace", "_export_final", "_current_best_score",
            "_final_summary",
        ]),
        ("Budget", ["_sync_budget_cost"]),
    ],
    "scripts.build_baseline": [
        ("Project", ["write_project_godot", "write_game_gd"]),
        ("Player", ["write_player_gd"]),
        ("Enemies", ["write_enemy_gd", "write_boss_gd"]),
        ("Pickups", ["write_coin_gd", "write_goal_gd"]),
        ("Menu", ["write_menu"]),
        ("AssetsScene", ["copy_assets", "write_tscns"]),
    ],
    "tools.domain.game_evaluator": [
        ("Features", [
            "extract_features", "_project_files", "_all_source_text",
            "_strip_comments", "_axis_score", "feature_present",
            "features_status", "has_entry",
        ]),
        ("Connectivity", [
            "_connected_methods", "_unconnected_signal_handlers",
            "_has_real_movement", "_has_real_jump", "_win_connected",
            "_lose_connected", "_restart_real", "connectivity_report",
        ]),
        ("Subtasks", [
            "extract_subtasks", "subtasks_status", "format_subtasks_status",
        ]),
        ("Gating", [
            "evaluate", "_apply_blocking_gates", "metrics_block",
            "parse_metrics_block", "blend_visual_total",
        ]),
        ("Novelty", ["_file_hashes", "_jaccard", "novelty_score"]),
    ],
    "agent.memory_db": [
        ("Runs", ["upsert_run", "get_run", "all_runs"]),
        ("Lessons", [
            "add_lesson", "update_lesson_safety", "increment_harmful_reuses",
            "record_reuse", "lessons", "lesson_text", "count_lessons",
        ]),
        ("Experiments", [
            "add_experiment", "delete_experiments", "experiments",
            "count_experiments",
        ]),
        ("Tree", ["upsert_node", "nodes", "count_nodes"]),
        ("HarnessEdits", [
            "add_harness_edit", "harness_edits", "get_harness_edit",
            "set_harness_edit_decision", "count_harness_edits",
        ]),
        ("Migrations", ["_migrate_lessons_safety", "close"]),
    ],
}

_REAGAME_CLASS_SPLITS: dict[str, list[str]] = {
    "tools.domain.game_generator": [
        "InspectArchetype", "GenerateCandidate", "AuditPage", "UpdateLessons",
        "SelectFinal", "RevertWorkspace",
    ],
}

REAGAME_PROFILE = Profile(
    name="reagame",
    tool_names=_REAGAME_TOOL_INFO,
    special_calls=_REAGAME_SPECIAL_CALLS,
    evolution_methods=_REAGAME_EVO_INFO,
    dispatch_attr="name",
    decision_hints=_REAGAME_DECISION_HINTS,
    phase_patterns=_REAGAME_PHASE_PATTERNS,
    init_label=("Init Agent", "Configura LLM, budget, memory,\ncontext manager, harness snapshot"),
    function_splits=_REAGAME_FUNCTION_SPLITS,
    class_splits=_REAGAME_CLASS_SPLITS,
)


# ── TraceForge profile ────────────────────────────────────────────────

_TRACEFORGE_TOOL_INFO: dict[str, tuple[str, str]] = {
    "instrument": (
        "Instrument",
        "Engancha tracers a frameworks\n(openai / anthropic / langchain / llamaindex)",
    ),
    "instrument_openai": (
        "Instrument OpenAI",
        "Monkey-patch a openai\npara trazar llamadas LLM",
    ),
    "instrument_anthropic": (
        "Instrument Anthropic",
        "Monkey-patch a anthropic\npara trazar llamadas LLM",
    ),
    "save": (
        "Save Span",
        "Persiste un span en el backend\nelegido (postgres/sqlite/clickhouse/…)",
    ),
    "get_trace": (
        "Get Trace",
        "Recupera un trace completo por id",
    ),
    "get_span": (
        "Get Span",
        "Recupera un span individual",
    ),
    "list_traces": (
        "List Traces",
        "Enumeración de traces con filtros",
    ),
    "get_last_trace_id": (
        "Last Trace ID",
        "Último id de trace persistido",
    ),
    "query": (
        "Query",
        "Consulta estructurada/filtrada de spans",
    ),
    "clear": (
        "Clear",
        "Vacía los datos del backend",
    ),
    "close": (
        "Close",
        "Cierra conexión/recursos del backend",
    ),
    "generate_report": (
        "Generate Report",
        "Span tree → reporte HTML\n(gantt + sankey + costes)",
    ),
    "run_dashboard": (
        "Run Dashboard",
        "Arranca el servidor HTTP\ncon el panel de trazabilidad",
    ),
    "show": ("CLI show", "Muestra un trace en la terminal"),
    "stats": ("CLI stats", "Estadísticas agregadas de la traza"),
    "report": ("CLI report", "Genera el reporte HTML"),
    "export": ("CLI export", "Exporta traces a un fichero"),
    "dashboard": ("CLI dashboard", "Lanza el dashboard web"),
    "refresh_prices": ("CLI refresh-prices", "Actualiza la tabla de precios LLM"),
}

_TRACEFORGE_SPECIAL_CALLS: dict[str, tuple[str, str, NodeType]] = {
    "on_llm_start": (
        "LLM Start",
        "Callback de framework:\ninicio de una llamada LLM",
        NodeType.PROCESS,
    ),
    "on_llm_end": (
        "LLM End",
        "Callback de framework:\nfin de una llamada LLM",
        NodeType.PROCESS,
    ),
    "on_llm_error": (
        "LLM Error",
        "Callback de framework:\nerror en una llamada LLM",
        NodeType.PROCESS,
    ),
}

_TRACEFORGE_FUNCTION_SPLITS: dict[str, list[tuple[str, list[str]]]] = {
    "traceforge.auto": [
        ("Core", [
            "_patch_method", "_new_span", "_estimate_tokens", "_extract_prompt",
            "_llm_wrapper_factory",
        ]),
        ("StreamProxies", [
            "_streammixin___getattr__", "_streammixin__on_chunk",
            "_streammixin__finalize", "_streammixin___del__",
            "_syncstreamproxy___iter__", "_syncstreamproxy___next__",
            "_syncstreamproxy___enter__", "_syncstreamproxy___exit__",
            "_syncstreamproxy_close", "_asyncstreamproxy___aiter__",
            "_asyncstreamproxy___anext__", "_asyncstreamproxy___aenter__",
            "_asyncstreamproxy___aexit__", "_asyncstreamproxy_aclose",
        ]),
        ("OpenAI", [
            "instrument_openai", "_openai_usage", "_openai_chunk_text",
        ]),
        ("Anthropic", [
            "instrument_anthropic", "_anthropic_usage", "_anthropic_chunk_text",
        ]),
        ("LangChain", [
            "_register_langchain", "_langchain_model",
            "traceforgelangchainhandler_on_llm_start",
            "traceforgelangchainhandler_on_llm_end",
            "traceforgelangchainhandler_on_llm_error",
        ]),
        ("LlamaIndex", [
            "_register_llamaindex",
            "traceforgellamaindexhandler_on_llm_start",
            "traceforgellamaindexhandler_on_llm_end",
            "traceforgellamaindexhandler_on_llm_error",
        ]),
        ("Entry", ["instrument"]),
    ],
    "traceforge.reporting": [
        ("Tree", ["_get_plotly_tag", "_build_span_tree_data", "_add_children"]),
        ("Gantt", ["_build_gantt"]),
        ("Sankey", ["_build_sankey"]),
        ("Cost", ["_build_cost_chart"]),
        ("Entry", ["generate_report"]),
    ],
    "traceforge.cli": [
        ("Entry", ["_main"]),
        ("Show", ["show", "show_trace", "_span_dict", "_build_span_tree", "_percentile"]),
        ("List", ["list_traces"]),
        ("Stats", ["stats"]),
        ("Report", ["report"]),
        ("Export", ["export"]),
        ("Query", ["query"]),
        ("Dashboard", ["dashboard"]),
        ("Pricing", ["refresh_prices"]),
        ("Clear", ["clear"]),
    ],
    "traceforge.dashboard": [
        ("Entry", ["run_dashboard"]),
        ("Views", ["_span_dict", "_trace_summary", "_build_timeseries"]),
        ("HTTP", [
            "dashboardhandler_log_message", "dashboardhandler_do_get",
            "dashboardhandler__params", "dashboardhandler__query",
            "dashboardhandler__stats", "dashboardhandler__send_json",
            "dashboardhandler__send_html", "dashboardhandler__export_rows",
            "dashboardhandler__send_csv",
        ]),
    ],
}

TRACEFORGE_PROFILE = Profile(
    name="traceforge",
    tool_names=_TRACEFORGE_TOOL_INFO,
    special_calls=_TRACEFORGE_SPECIAL_CALLS,
    function_splits=_TRACEFORGE_FUNCTION_SPLITS,
)


# ── Asubarnipal profile ───────────────────────────────────────────────

_ASUBARNIPAL_TOOL_INFO: dict[str, tuple[str, str]] = {
    "ingest_url": (
        "Ingest URL",
        "WikiIngest: descarga y parsea una URL\n(youtube si procede) al vault",
    ),
    "ingest_url_smart": (
        "Ingest Smart",
        "Detección de tipo de fuente\n(youtube / web / file) y ruta de ingestión",
    ),
    "ingest_file": (
        "Ingest File",
        "Ingesta de un fichero de texto\n(ruta local o documento Telegram)",
    ),
    "ingest_image": (
        "Ingest Image",
        "Ingesta de una imagen → OCR\nsi el modelo está disponible",
    ),
    "ingest_pdf": (
        "Ingest PDF",
        "Análisis página a página + OCR",
    ),
    "extract_with_ocr": (
        "Extract w/ OCR",
        "Extracción de texto de imagen\nvía modelo OCR",
    ),
    "save_research_proposal": (
        "Save Proposal",
        "Persiste la propuesta de investigación\ncomo nota wiki",
    ),
    "ingestar": (
        "Ingestar",
        "WikiEngine: midende notas de una fuente\nal vault (frontmatter + relaciones)",
    ),
    "query_wiki": (
        "Query Wiki",
        "Búsqueda semántica sobre el vault wiki",
    ),
    "lint": ("Lint Wiki", "Valida la estructura de las notas wiki"),
    "search": (
        "Search",
        "Búsqueda híbrida (sqlite + obsidian /\nsemántica densa + BM25)",
    ),
    "query_knowledge": (
        "Query Knowledge",
        "API: consulta RAG sobre el conocimiento indexado",
    ),
    "retrieve": (
        "Retrieve",
        "HybridRetriever: planifica y recupera de\ntree + graph + embbeding",
    ),
    "answer": ("Answer", "Respuesta con contexto recuperado"),
    "remember": (
        "Remember",
        "HMem: consolida un evento en la memoria",
    ),
    "recall": ("Recall", "HMem: recupera memoria reciente"),
    "think": ("Think", "HMem: razonamiento sobre la memoria"),
    "build_graph": (
        "Build Graph",
        "Graphify: construye el grafo\n(story-graph) del vault",
    ),
    "query_graph": (
        "Query Graph",
        "Graphify: consulta el grafo",
    ),
    "update_graph": ("Update Graph", "Graphify: actualiza el grafo"),
    "export_graph": ("Export Graph", "Graphify: exporta el grafo"),
    "add_url_to_graph": (
        "Add URL to Graph",
        "Graphify: añade una URL como nodo",
    ),
    "add_entity": (
        "Add Entity",
        "EntityGraph: inserta/actualiza una entidad",
    ),
    "add_relation": (
        "Add Relation",
        "EntityGraph: crea una relación entre entidades",
    ),
    "link_memory": (
        "Link Memory",
        "EntityGraph: enlaza una memoria a entidades",
    ),
    "extract_entities": (
        "Extract Entities",
        "EntityGraph: entidades desde un texto\nvia LLM",
    ),
    "ingest_memory": (
        "Ingest Memory",
        "HybridRetriever: inserta y consolida memoria",
    ),
    "search_web": (
        "Search Web",
        "Búsqueda web externa para \nrespuestas del asistente",
    ),
    "generate": (
        "Generate",
        "LLMRouter: invocación LLM\ngenerativa (gemini/ollama)",
    ),
    "call_agent": (
        "Call Agent",
        "LLMRouter: conversación con el agente",
    ),
    "call_with_harness": (
        "Call w/ Harness",
        "LLM + harness de runtime (herramientas\ntrajectoria y presupuesto)",
    ),
    "call_with_turbo": (
        "Call w/ Turbo",
        "LLM con compresión turboquant",
    ),
    "search_and_summarize": (
        "Search & Summarize",
        "Librarian: búsqueda bibliográfica\n+ resumen con fuentes",
    ),
    "research_topic": (
        "Research Topic",
        "Investigación de un tema desde\nel servicio principal",
    ),
}

_ASUBARNIPAL_SPECIAL_CALLS: dict[str, tuple[str, str, NodeType]] = {
    "_heartbeat_loop": (
        "Heartbeat Loop",
        "Background loop: notifica estado\ndel agente cada heartbeat",
        NodeType.LOOP,
    ),
    "_suture_loop": (
        "Suture Loop",
        "Background loop: conservación de la\nmemoria (respaldos)",
        NodeType.LOOP,
    ),
    "_graph_loop": (
        "Graph Loop",
        "Background loop: reconstrucción del grafo\ngraphify del vault",
        NodeType.LOOP,
    ),
    "_hmem_loop": (
        "HMem Loop",
        "Background loop: consolidación de la\nmemoria híbrida",
        NodeType.LOOP,
    ),
    "_run_hmem_consolidation": (
        "HMem Consolidate",
        "Consolidación programada de memoria",
        NodeType.PROCESS,
    ),
    "_update_graphify": (
        "Update Graphify",
        "Reconstruye el grafo del vault",
        NodeType.PROCESS,
    ),
    "_check_ollama_available": (
        "Check Ollama",
        "Comprueba disponibilidad del modelo\nlocal ollama",
        NodeType.PROCESS,
    ),
    "_check_ollama": (
        "Check Ollama",
        "Comprueba disponibilidad del modelo\nlocal ollama",
        NodeType.PROCESS,
    ),
    "_memory_robustness": (
        "Memory Robustness",
        "Robustecimiento/consolidación del\nárbol de memoria",
        NodeType.PROCESS,
    ),
    "heal_orphans": (
        "Heal Orphans",
        "WikiHealer: repara notas huérfanas",
        NodeType.PROCESS,
    ),
}

_ASUBARNIPAL_EVO_INFO: dict[str, tuple[str, str]] = {
    "evolve_from_failures": (
        "Evolve from Failures",
        "ProceduralSkillLayer: deriva habilidades\nde los fallos registrados",
    ),
    "record_failure": (
        "Record Failure",
        "Registra un fallo de acción para evolución\nde habilidades",
    ),
}

_ASUBARNIPAL_FUNCTION_SPLITS: dict[str, list[tuple[str, list[str]]]] = {
    "interface.telegram_bot": [
        ("Entry", ["main"]),
        ("Sessions", [
            "get_user_session", "_save_to_db", "_load_from_db",
            "_prune_db_history", "_clear_db_session",
        ]),
        ("Messages", ["_estimate_tokens", "_trim_history", "_build_messages"]),
        ("Handlers", [
            "handle_message", "handle_voice", "handle_photo",
            "agent_callback", "error_handler",
        ]),
        ("Commands", [
            "indexar_wiki_cmd", "clear_session_cmd", "session_info_cmd",
        ]),
    ],
    "api.main": [
        ("Entry", [
            "_graceful_shutdown", "root",
            "http_exception_handler", "general_exception_handler",
        ]),
        ("Health", ["health", "liveness", "readiness", "circuit_breaker_status"]),
        ("Metrics", ["get_metrics", "get_prometheus_metrics"]),
        ("Knowledge", ["query_knowledge", "list_vaults"]),
        ("Commands", ["execute_command", "get_command_history", "add_to_history"]),
        ("Status", ["get_status", "get_stats"]),
        ("Feeds", [
            "list_feeds", "subscribe_feed", "unsubscribe_feed", "check_feed_updates",
        ]),
        ("Logs", ["get_logs"]),
        ("Schedules", ["list_schedules"]),
    ],
    "core.graphify_integration": [
        ("Paths", ["_get_graph_dir", "_get_graphify_bin"]),
        ("GraphIO", ["_graph_json", "_graph_html", "_graph_report"]),
        ("Runner", ["_check_graphify", "_run_graphify"]),
        ("Ops", ["build_graph", "update_graph", "export_graph", "add_url_to_graph"]),
        ("Query", [
            "query_graph", "get_graph_stats", "get_graph_report",
            "get_graph_html_path",
        ]),
        ("Dashboard", ["copy_graph_to_dashboard", "install_graphify_hook"]),
    ],
    "interface.handlers.busqueda": [
        ("Helpers", ["is_url", "is_local_path", "extract_url_from_text"]),
        ("Ingestion", [
            "ingest_cmd", "_ingest_url", "_ingest_local_file",
            "_ingest_telegram_document", "_ingest_telegram_photo",
        ]),
        ("Research", ["investigar_cmd", "_validate_topic", "_validate_url"]),
    ],
    "core.wiki_engine": [
        ("Helpers", [
            "guardar_schema", "_hash_fuente", "_extraer_frontmatter",
            "_actualizar_index",
        ]),
        ("Ingestion", [
            "ingestar", "log_ingest", "_buscar_notas_existentes",
            "_encontrar_relacionadas",
        ]),
        ("Query", ["query_wiki", "lint"]),
        ("VectorIndex", [
            "_scan", "generar_embeddings", "construir_grafo",
            "detectar_comunidades", "identificar_hubs", "full_index",
        ]),
    ],
    "core.wiki.ingest": [
        ("Entry", ["ingest_url_smart", "get_last_source", "get_last_ingested"]),
        ("Youtube", [
            "ingest_url", "_is_youtube_url", "_check_node_js", "_extract_video_id",
            "_extract_youtube_transcript", "_extract_youtube_metadata",
            "_parse_vtt_content", "_parse_srt_content", "_ingest_youtube",
        ]),
        ("Enrichment", [
            "_detect_language", "_translate_text", "_generate_summary",
            "_extract_concepts", "_find_related_notes",
        ]),
        ("OCR", [
            "_check_ocr_model_available", "extract_with_ocr", "_process_pdf_page_ocr",
        ]),
        ("Files", ["ingest_file", "_ingest_text_file", "ingest_image"]),
        ("Pdf", ["_analyze_pdf_pages", "ingest_pdf"]),
        ("Research", ["save_research_proposal"]),
    ],
    "core.memory_tree": [
        ("Core", [
            "__init__", "_get_active_vault_name", "_get_db_path", "_init_db",
            "_get_llm", "_get_embeddings_model", "_generate_node_id",
            "_get_time_window",
        ]),
        ("Similarity", ["_compute_similarity", "_generate_summary", "_memory_robustness"]),
        ("Insert", [
            "insert", "_propagate_consolidation", "_merge_nodes", "_create_parent_node",
        ]),
        ("Query", [
            "query", "_query_level", "_temporal_relevance", "_rank_results",
        ]),
        ("Maintenance", [
            "force_consolidation", "prune_old_nodes", "get_stats", "get_recent",
            "close",
        ]),
    ],
    "core.entity_graph": [
        ("Core", [
            "__init__", "_get_active_vault_name", "_get_db_path", "_init_db",
            "_get_llm", "_generate_entity_id", "_generate_relation_id",
        ]),
        ("Entities", [
            "add_entity", "update_entity", "get_entity",
            "get_entities_by_type", "get_entity_by_id",
        ]),
        ("Relations", ["add_relation", "expand", "get_relations"]),
        ("Memory", ["link_memory", "extract_entities", "ingest_with_entities"]),
        ("Traversal", ["get_neighbors", "get_hubs", "get_stats", "close"]),
    ],
    "core.vault_manager": [
        ("Core", ["__new__", "__init__", "_load_config", "_save_config"]),
        ("Hall", [
            "_ensure_default_vault", "_get_db_path", "_get_index_path",
        ]),
        ("Vaults", ["list_vaults", "get_active", "create", "_init_vault_db"]),
        ("Switch", ["switch", "delete"]),
        ("Transfer", ["export_vault", "import_vault"]),
        ("Connect", ["connect", "disconnect", "get_vault_notes_count"]),
    ],
}

_ASUBARNIPAL_CLASS_SPLITS: dict[str, list[str]] = {
    "core.runtime_harness": [
        "RuntimeHarness", "EnvironmentContractLayer", "ProceduralSkillLayer",
        "ProceduralSkill", "ActionValidationResult", "ActionRealizationLayer",
        "TrajectoryState", "TrajectoryRegulationLayer",
    ],
    "core.background_manager": [
        "BackgroundManager", "AgentState", "BraveCounter",
        "MemorySkill", "WikiHealer", "GraphBuilder",
    ],
    "core.llm_router": [
        "LLMRouter", "GeminiRouter", "BraveRouter", "BraveCounter",
    ],
}

ASUBARNIPAL_PROFILE = Profile(
    name="asubarnipal",
    tool_names=_ASUBARNIPAL_TOOL_INFO,
    special_calls=_ASUBARNIPAL_SPECIAL_CALLS,
    evolution_methods=_ASUBARNIPAL_EVO_INFO,
    function_splits=_ASUBARNIPAL_FUNCTION_SPLITS,
    class_splits=_ASUBARNIPAL_CLASS_SPLITS,
)


# ── CogniTeam profile ─────────────────────────────────────────────────

_COGNITEAM_TOOL_INFO: dict[str, tuple[str, str]] = {
    "llm_complete": (
        "LLM Complete",
        "Groq/Ollama: envía prompt + contexto\n→ JSON/texto (routing por proveedor)",
    ),
    "get_model_for_task": (
        "Model for Task",
        "Selecciona modelo/temperatura\nsegún la tarea resuelta",
    ),
    "get_llm_prompt": (
        "LLM Prompt",
        "Build del prompt según dominio\n(archetype fewshot)",
    ),
    "run_orchestrated_flow": (
        "Run Orchestrated Flow",
        "Orquesta multi-agente: planner →\ndeveloper → validator con retries",
    ),
    "execute_step": (
        "Execute Step",
        "Developer/Debugger: ejecuta un\npaso del plan con el LLM",
    ),
    "generate_plan": (
        "Generate Plan",
        "PlannerAgent: genera plan\nestructurado con World Model",
    ),
    "generate_plan_with_world_model": (
        "Plan w/ World Model",
        "Plan enriquecido con el bloque\nYAML del world model",
    ),
    "generate_world_model": (
        "Generate World Model",
        "WorldModelGenerator: archetype\nYAML desde el prompt del usuario",
    ),
    "create_planner_agent": (
        "Create Planner",
        "Factory del agente planner",
    ),
    "create_debugger_agent": (
        "Create Debugger",
        "Factory del agente debugger",
    ),
    "normalize_step_ids": (
        "Normalize Steps",
        "Renombra step_ids del plan\n(secuencia estable)",
    ),
    "clarify_task": (
        "Clarify Task",
        "Scoping interactivo: preguntas,\nmanifiesto y clasificación",
    ),
    "extract_inputs_from_task": (
        "Extract Inputs",
        "Extrae entradas del task\nsegún el archetype",
    ),
    "classify_without_llm": (
        "Classify (No LLM)",
        "Clasificación determinista por\nreglas (sin coste de LLM)",
    ),
    "run_with_world_model": (
        "Run w/ World Model",
        "DeterministicCage: run con\nworld model + verificación",
    ),
    "create_cage_from_yaml": (
        "Cage from YAML",
        "Construye DeterministicCage\napartir del archetype YAML",
    ),
    "complete_plan": (
        "Complete Plan",
        "YamlCage: completa el plan con\npasos de código/html/stack",
    ),
    "validate_artifacts": (
        "Validate Artifacts",
        "YamlCage: valida el árbol de\nartefactos generados",
    ),
    "repair_step": (
        "Repair Step",
        "Arregla un paso fallido con\nfeedback del validador",
    ),
    "repair_step_v2": (
        "Repair Step v2",
        "Reparación mejorada (evidencia\nrecopilada del entorno)",
    ),
    "repair_with_loop": (
        "Repair Loop",
        "Bucle de reparación: staging →\nevidence → verify → promote",
    ),
    "verify_grounding": (
        "Verify Grounding",
        "Comprueba que el artefacto\ngenerado sigue el plan",
    ),
    "verify_html_quality": (
        "Verify HTML Quality",
        "Valida calidad del HTML generado",
    ),
    "register_skill": (
        "Register Skill",
        "Añade una skill al catálogo\n(con score inicial)",
    ),
    "record_skill_usage": (
        "Record Skill Usage",
        "Registra uso de skill y ajusta\nscore",
    ),
    "retrieve_with_memory": (
        "Retrieve w/ Memory",
        "Recupera skills relevantes para\nla tarea",
    ),
    "answer_with_memory": (
        "Answer w/ Memory",
        "Respuesta del agente apoyada\nen memoria de skills",
    ),
    "sage_read": (
        "Sage Read",
        "Lee el grafo de memoria\n(sage graph)",
    ),
    "sage_write": (
        "Sage Write",
        "Escribe en el grafo de memoria",
    ),
    "co_evolve": (
        "Co-Evolve",
        "Genera nuevas skills a partir de\nlas existentes",
    ),
    "add_memory": (
        "Add Memory",
        "HMEM: añade un nodo de memoria\ncon contexto",
    ),
    "add_knowledge": (
        "Add Knowledge",
        "HMEM: añade conocimientos\n(tripletas)",
    ),
    "query_knowledge": (
        "Query Knowledge",
        "HMEM: consulta el conocimiento\nestructurado",
    ),
    "hybrid_retrieve": (
        "Hybrid Retrieve",
        "Recuperación híbrida (list-sage\ngraph + consulta local)",
    ),
    "consolidate": (
        "Consolidate",
        "Consolidación de memoria y\nresúmenes",
    ),
    "store_memory": (
        "Store Memory",
        "MATM: guarda memoria por agente",
    ),
    "retrieve_memories": (
        "Retrieve Memories",
        "MATM: recupera memoria transactiva",
    ),
    "transactive_retrieve": (
        "Transactive Retrieve",
        "Recupera de agentes expertos del\nteam",
    ),
    "synthesize_knowledge": (
        "Synthesize",
        "Sintetiza conocimiento recuperado",
    ),
    "find_expert": (
        "Find Expert",
        "MATM: selecciona el agente experto\npara el query",
    ),
    "extract_entities_from_text": (
        "Extract Entities",
        "GraphRAG: extrae entidades y\nrelaciones de un texto",
    ),
    "global_search": (
        "Global Search",
        "GraphRAG: búsqueda global sobre\ncomunidades resumidas",
    ),
    "local_search": (
        "Local Search",
        "GraphRAG: búsqueda local con\nvecinos de entidades",
    ),
    "hybrid_search": (
        "Hybrid Search",
        "GraphRAG: combina búsqueda\nlocal y global",
    ),
    "run_slow_phase": (
        "Slow Phase",
        "FastSlow: evolución lenta de\npolíticas (crossover/mutación)",
    ),
    "run_fast_phase": (
        "Fast Phase",
        "FastSlow: adaptación rápida\n(selección + control)",
    ),
    "get_best_action": (
        "Best Action",
        "FastSlow: decide la mejor acción",
    ),
    "execute_task": (
        "Execute Task",
        "ProspectiveOrchestrator: ejecuta\nla tarea con scoping + plan",
    ),
    "process_task": (
        "Process Task",
        "CageOrchestrator: procesa la tarea\n(end-to-end con cage)",
    ),
}

_COGNITEAM_SPECIAL_CALLS: dict[str, tuple[str, str, NodeType]] = {
    "_validate_output": (
        "Validate Output",
        "Verifica artefactos generados vs plan\n(file tree, quality)",
        NodeType.PROCESS,
    ),
    "_record_step_skill_usage": (
        "Record Skill Usage",
        "Persiste uso de skills\n→ memoria de equipo",
        NodeType.EVOLUTION,
    ),
    "_warmup_litellm": (
        "Warmup LiteLLM",
        "Precalienta routing/fallback\nde proveedores LLM",
        NodeType.PROCESS,
    ),
    "_run_functional_validation": (
        "Functional Validation",
        "Ejecuta validación funcional del\nartefacto (script de prueba)",
        NodeType.PROCESS,
    ),
    "_record_rejection": (
        "Record Rejection",
        "Registra un rechazo del cage\n→ adaptación",
        NodeType.PROCESS,
    ),
    "_try_local_repair": (
        "Local Repair",
        "Intenta reparación puntual ante\nerror transitorio",
        NodeType.PROCESS,
    ),
    "_get_memory_context": (
        "Memory Context",
        "Compone el contexto de memoria\npara el paso",
        NodeType.PROCESS,
    ),
}

_COGNITEAM_EVO_INFO: dict[str, tuple[str, str]] = {
    "_calibrate": (
        "Calibration Store",
        "Guarda métricas de éxito\npara scoping futuro",
    ),
    "co_evolve": (
        "Co-Evolve",
        "Genera nuevas skills a partir de\nlas existentes",
    ),
    "_sage_consolidate": (
        "Sage Consolidate",
        "Consolida el grafo de memoria\n(sage)",
    ),
    "_generate_new_skill": (
        "Generate Skill",
        "Crea una skill nueva con prompt",
    ),
    "summarize_communities": (
        "Summarize Communities",
        "Resume comunidades detectadas\ndel grafo RAG",
    ),
    "_mutate_policy": (
        "Mutate Policy",
        "Mutación de políticas\nen la fase lenta",
    ),
}

_COGNITEAM_FUNCTION_SPLITS: dict[str, list[tuple[str, list[str]]]] = {
    "cogniteam.world_model.deterministic_cage": [
        ("Inputs", [
            "_extract_inputs", "_extract_num_pages", "_extract_devices",
            "_extract_data_source", "_extract_ml_objective", "_extract_model_type",
            "_extract_content_type", "_extract_tone", "_extract_seo_keywords",
            "_extract_infra_type", "_extract_cloud_provider", "_extract_audit_type",
            "_extract_security_scope", "_extract_compliance", "extract_variables",
            "_extract_title", "_extract_subtitle", "_extract_cta",
        ]),
        ("Classify", [
            "classify_without_llm", "_parse_task", "_classify_with_llm",
            "_extract_word_count", "_render_prompt", "_check_world_model",
            "run_with_world_model",
        ]),
        ("LLM", ["_call_llm", "_verify_output", "_get_rejection_adaptation", "_record_rejection"]),
        ("Demo", ["demo"]),
    ],
    "cogniteam.core.orchestrator": [
        ("Calibration", [
            "_key", "record", "get_threshold", "get_report",
            "to_dict", "from_dict", "save", "load",
        ]),
        ("Tools", [
            "_resolve_tool_name", "_validate_output", "_seed_skills_once",
            "_record_step_skill_usage", "_get_memory_context",
            "_get_artifacts_summary", "_run_functional_validation",
            "_find_file_in_tree",
        ]),
        ("Loop", ["run_orchestrated_flow"]),
        ("Repair", [
            "_is_transient_error", "_build_repair_structure_hint",
            "_try_local_repair", "_try_local_repair_v2",
        ]),
        ("Memory", ["_build_completed_summary", "_store_in_memory", "_save_all_memory"]),
    ],
    "cogniteam.agents.planner_agent": [
        ("WorldModel", [
            "_select_world_model_prompt", "_get_yaml", "_yaml_world_model_block",
            "generate_world_model",
        ]),
        ("Agent", ["create_planner_agent"]),
        ("Prompt", ["_build_prompt", "_extract_json"]),
        ("Plan", ["normalize_step_ids", "generate_plan", "generate_plan_with_world_model"]),
    ],
    "cogniteam.scoping.agent": [
        ("Rules", [
            "_archetype_comprobable_rules", "_archetype_prose_rules",
            "_param_name_to_human", "_collect_known_params",
        ]),
        ("Ask", [
            "_ask_user", "_show_classification", "_confirm_classification",
            "_select_manual_classifications", "_generate_questions",
            "_fallback_questions",
        ]),
        ("Clarify", [
            "_yaml_missing_inputs", "_generate_clarified_task",
            "_fallback_clarified", "_build_manifest", "clarify_task",
        ]),
    ],
    "cogniteam.tools.utils.llm": [
        ("Routing", [
            "get_last_provider", "get_last_model", "_provider_available",
            "get_model_for_task", "get_litellm_model_name", "get_genai_model_name",
        ]),
        ("Providers", [
            "_ollama_complete", "_groq_complete", "_openai_compatible_complete",
            "_cerebras_complete", "_mistral_complete", "_nvidia_complete",
            "_google_complete",
        ]),
        ("Availability", [
            "_cerebras_available", "_cerebras_model", "_mistral_available",
            "_mistral_model", "_nvidia_available", "_nvidia_model",
            "_google_available", "_google_model", "_get_primary_provider",
            "_groq_available", "_record_groq",
        ]),
        ("Complete", [
            "llm_complete", "_llm_complete_body", "_escape_control_chars_in_match",
            "_resolve_model_name", "sanitize_json_string_for_control_chars",
        ]),
    ],
    "cogniteam.agents.debugger_agent": [
        ("Agent", ["create_debugger_agent"]),
        ("Grounding", ["verify_grounding", "validate", "_grounding_fallback"]),
        ("Quality", ["verify_html_quality"]),
        ("Repair", [
            "_repair_fallback", "repair_step", "repair_step_v2",
            "_build_test_script_hint",
        ]),
    ],
    "main": [
        ("Setup", ["_build_tool_map", "_categorize_tools", "_warmup_litellm"]),
        ("Entry", ["main"]),
        ("Output", ["_save_result"]),
    ],
    "cogniteam.memory.skills.skills": [
        ("Manager", [
            "register_skill", "get_skills_by_category", "get_top_skills",
            "record_skill_usage", "add_preference", "_update_skill_score",
            "get_preferred_skill", "save", "load",
        ]),
        ("SageGraph", [
            "_add_sage_node", "_add_sage_edge", "sage_write",
            "sage_read", "_sage_consolidate",
        ]),
        ("CoEvolve", ["co_evolve", "_generate_new_skill"]),
        ("Retrieve", ["retrieve_with_memory", "answer_with_memory", "get_skills"]),
    ],
    "cogniteam.world_model.yaml_loader": [
        ("Loader", [
            "_load", "get_archetype", "get_all_archetypes", "get_domain",
            "get_domain_fewshot", "get_domain_prose", "get_llm_prompt",
            "_render_conditionals", "get_verification_rules", "get_thresholds",
            "get_grounding_keywords", "get_structure", "get_input_definitions",
            "get_default_config", "get_calibration_config", "get_fallback",
            "extract_inputs_from_task", "find_archetype_by_keywords",
        ]),
        ("Cage", [
            "_collect_plan_files", "_structure_required", "validate_structure",
            "_check_stack_architecture", "validate_artifacts", "_find_exact_file",
            "complete_plan", "_build_completion_steps", "_build_code_steps",
            "_build_textual_steps", "_build_meta_step", "_build_html_steps",
            "create_cage_from_yaml",
        ]),
        ("Validation", [
            "validate_output", "_looks_like_filler", "_extract_classes_ids_tags",
            "_js_selectors", "_check_css_js_coherence",
        ]),
    ],
    "cogniteam.agents.repair_v2": [
        ("Staging", [
            "_staging_dir_for", "_setup_staging", "_promote",
            "_rewrite_paths_to_staging", "_execute_tool_in_staging",
        ]),
        ("Evidence", [
            "_collect_file_evidence", "_collect_span_evidence", "_collect_evidence",
            "_find_html_in_dir", "_run_verification",
        ]),
        ("Loop", ["repair_with_loop"]),
    ],
}

_COGNITEAM_CLASS_SPLITS: dict[str, list[str]] = {
    "cogniteam.world_model.world_model_layer": [
        "WorldModelGenerator", "ProspectivePlannerAgent", "ProspectiveScopingAgent",
        "ProspectiveDebuggerAgent", "CalibrationStore", "ProspectiveOrchestrator",
        "LLMClient",
    ],
}

COGNITEAM_PROFILE = Profile(
    name="cogniteam",
    tool_names=_COGNITEAM_TOOL_INFO,
    special_calls=_COGNITEAM_SPECIAL_CALLS,
    evolution_methods=_COGNITEAM_EVO_INFO,
    function_splits=_COGNITEAM_FUNCTION_SPLITS,
    class_splits=_COGNITEAM_CLASS_SPLITS,
)


# ── AgentFlow profile (el propio generador de flujogramas) ─────────────

_AGENTFLOW_TOOL_INFO: dict[str, tuple[str, str]] = {
    "parse_source": ("Parse Source", "Analiza código Python\n→ grafo de flujo"),
    "parse_file": ("Parse File", "Parsear fichero completo\n(agent flow)"),
    "parse_functions": ("Parse Functions", "Sub-flujo de un subconjunto\nde funciones escogidas"),
    "parse_class_methods": ("Parse Class Methods", "Sub-flujo de los métodos\nde una clase"),
    "get_profile": ("Load Profile", "Carga perfil de dominio\n(herramientas/etiquetas)"),
    "run_drilldown": ("Run Drill-Down", "Genera la jerarquía completa\nL0→Ln de un repositorio"),
    "build_repo_overview": ("Repo Overview", "Overview de un repositorio\n(imports + módulos)"),
    "collect_python_files": ("Collect Python Files", "Rastrea ficheros .py\nexcluyendo venvs/cachés"),
    "to_mermaid": ("Render Mermaid", "Serializa el flujo a texto\nMermaid (markdown)"),
    "to_mermaid_html": ("Interactive HTML", "HTML interactivo Mermaid\n(zoom + clicks)"),
    "to_sequence_svg": ("Sequence SVG", "Diagrama de secuencia\nSVG desde interacciones"),
    "to_sequence_html": ("Sequence HTML", "Diagrama de secuencia\nHTML interactivo"),
    "extract_interactions": ("Extract Interactions", "Extrae mensajes actor-a-actor\nde un fuente"),
    "extract_interactions_from_dir": ("Extract Interactions Dir", "Secuencias de todo un\nrepositorio"),
    "extract_interactions_multi": ("Extract Interactions Multi", "Extrae secuencias de varios\nmódulos"),
    "merge_interactions": ("Merge Interactions", "Fusiona secuencias por actor\n(imports)"),
    "to_excalidraw": ("Excalidraw", "Exporta geometría del flujo\na .excalidraw"),
    "save_excalidraw": ("Save Excalidraw", "Escribe el fichero .excalidraw"),
    "to_dot": ("Graphviz DOT", "Texto DOT para renderización\ncon graphviz"),
    "save_dot": ("Save DOT", "Escribe el fichero .dot"),
    "to_ascii": ("ASCII Art", "Renderizado en texto plano\ndel flujo"),
    "to_svg": ("Render SVG", "Renderizado vectorial SVG\ndel flujo (neon/dark/...)"),
    "save_svg": ("Save SVG", "Escribe el fichero .svg"),
    "to_html": ("Render HTML", "HTML autocontenido del flujo"),
    "save_html": ("Save HTML", "Escribe el fichero .html"),
    "save_sequence_svg": ("Save Sequence SVG", "Escribe el SVG de secuencia"),
}

_AGENTFLOW_SPECIAL_CALLS: dict[str, tuple[str, str, NodeType]] = {
    "_parse_block": (
        "Parse Block",
        "Recorre el cuerpo de una función\nregistrando nodos/aristas",
        NodeType.PROCESS,
    ),
    "_detect_tool_dispatch": (
        "Detect Tool Dispatch",
        "Reconoce despachos de herramientas\n(tool.dispatch / dispatch_attr)",
        NodeType.PROCESS,
    ),
    "_build_overview": (
        "Build Overview",
        "Arma el overview con nodos por\nactor (módulo/directorio)",
        NodeType.PROCESS,
    ),
    "_write_index": (
        "Write Index",
        "Genera index.html con la lista\njerárquica de todas las vistas",
        NodeType.PROCESS,
    ),
    "_handle_diff": (
        "Handle Diff",
        "Subcomando CLI: compara dos\nflujos y pinta cambios",
        NodeType.PROCESS,
    ),
    "_handle_drilldown": (
        "Handle Drill-Down",
        "Subcomando CLI: lanza el\ndrill-down completo",
        NodeType.PROCESS,
    ),
}

_AGENTFLOW_FUNCTION_SPLITS: dict[str, list[tuple[str, list[str]]]] = {
    "agentflow.parser": [
        ("Entry", ["parse_file", "parse_source", "_unwrap_call", "parse_functions", "parse_class_methods"]),
        ("Agent", ["_find_agent_class", "_parse_agent_class", "_parse_init", "_parse_run_method"]),
        ("Block", [
            "_parse_block", "_parse_while", "_parse_if", "_parse_for",
            "_parse_try", "_parse_match", "_parse_assign", "_parse_expr_stmt",
            "_parse_local_function", "_parse_function",
        ]),
        ("Tools", ["_detect_tool_dispatch", "_scan_handle_eval_for_tools", "_extract_call_info"]),
        ("Labels", [
            "_generic_if_label", "_if_label_and_detail", "_while_label",
            "_apply_phase_patterns", "_find_function_def", "_find_class_def",
        ]),
    ],
    "agentflow.layouts": [
        ("Measure", ["_char_em_width", "measure_text", "node_size", "get_theme", "with_detail_level"]),
        ("Topo", [
            "_assign_rows", "_phase_groups", "_structural_phase_groups",
            "_nodes_in_cycles", "_ancestors_of", "_default_phase",
            "_classify_phase_nodes", "_topo_order_filtered", "_topological_sort",
        ]),
        ("PhaseBoxes", [
            "_compute_phase_boxes", "_compute_group_boxes", "_identify_feedback_arrows",
        ]),
        ("Linear", ["hierarchical_layout"]),
        ("Phased", ["phased_layout", "phased_horizontal_layout"]),
        ("GridSwim", ["grid_layout", "swimlane_layout", "_assign_lane"]),
        ("Radial", ["_radial_center", "_radial_levels", "radial_layout"]),
    ],
    "agentflow.sequence": [
        ("Detect", [
            "_is_actor_class_name", "_looks_like_actor", "_try_unwrap_call",
            "_extract_fragments_from_if", "_collect_fragments", "_is_significant_condition",
        ]),
        ("Extract", ["extract_interactions", "extract_from_file", "extract_interactions_multi", "extract_interactions_from_dir"]),
        ("Mermaid", ["to_mermaid_sequence", "_emit_mermaid_msg"]),
        ("Render", ["to_sequence_svg", "save_sequence_svg", "to_sequence_html", "_build_import_actor_map", "merge_interactions"]),
    ],
    "agentflow.excalidraw": [
        ("Geometry", ["_set_seed", "_rid", "_base_element", "_make_shape"]),
        ("Elements", ["_make_text", "_make_title", "_make_box_with_label", "_make_legend", "_make_arrow", "_bind_arrow"]),
        ("Export", ["to_excalidraw", "save_excalidraw"]),
    ],
    "agentflow.drilldown": [
        ("Walk", [
            "_title_segments", "_level_name", "_display_title", "_module_name",
            "_rel_segments", "_collect_dirs", "_iter_py_recurse", "_flow_files_in",
            "_warrants_overview",
        ]),
        ("Split", ["_split_overview_father", "_parent_href", "_save_artifact"]),
        ("Emit", [
            "_handle_dir", "_handle_dir_shallow", "_build_overview", "_safe_mod",
            "_write_index", "run_drilldown",
        ]),
    ],
    "agentflow.mermaid": [
        ("Labels", ["_sanitize_id", "_escape_label", "_node_label", "_node_definition", "_edge_line"]),
        ("Export", ["to_mermaid", "save_mermaid", "to_mermaid_html", "save_mermaid_html"]),
    ],
}

AGENTFLOW_PROFILE = Profile(
    name="agentflow",
    tool_names=_AGENTFLOW_TOOL_INFO,
    special_calls=_AGENTFLOW_SPECIAL_CALLS,
    function_splits=_AGENTFLOW_FUNCTION_SPLITS,
)


# ── LangChain profile ─────────────────────────────────────────────────

LANGCHAIN_PROFILE = Profile(
    name="langchain",
    agent_class_names={
        "AgentExecutor": "Agent",
        "Chain": "Chain",
        "LLMChain": "LLM",
        "ConversationChain": "Conversation",
        "SequentialChain": "Sequential",
        "RouterChain": "Router",
        "TransformChain": "Transform",
        "MultiChain": "Multi",
    },
    tool_names={
        "invoke": ("Invoke", "LangChain .invoke() — single input"),
        "ainvoke": ("Async Invoke", "LangChain .ainvoke() — async single input"),
        "batch": ("Batch", "LangChain .batch() — multiple inputs"),
        "stream": ("Stream", "LangChain .stream() — token streaming"),
        "astream": ("Async Stream", "LangChain .astream() — async streaming"),
        "run": ("Run", "LangChain .run() — deprecated, use invoke"),
        "predict": ("Predict", "LangChain .predict() — text in/text out"),
        "apredict": ("Async Predict", "LangChain .apredict() — async predict"),
        "apply": ("Apply", "LangChain .apply() — batch of inputs"),
        "__call__": ("Call", "LangChain chain.__call__() — legacy invoke"),
    },
    special_calls={
        "bind_tools": ("Bind Tools", "Attach tools to LLM", NodeType.TOOL),
        "with_structured_output": ("Structured Output", "Wrap LLM for structured output", NodeType.TOOL),
        "with_retry": ("Retry Wrapper", "Add retry logic to chain", NodeType.TOOL),
        "with_callbacks": ("Callbacks", "Attach callback handlers", NodeType.TOOL),
        "get_relevant_documents": ("Retrieve", "VectorStore similarity search", NodeType.TOOL),
        "similarity_search": ("Similarity Search", "VectorStore similarity search", NodeType.TOOL),
        "asimilarity_search": ("Async Similarity Search", "Async vector search", NodeType.TOOL),
        "max_marginal_relevance_search": ("MMR Search", "Maximal marginal relevance", NodeType.TOOL),
        "add_documents": ("Add Documents", "Insert into vector store", NodeType.TOOL),
        "from_documents": ("Load Documents", "Create retriever from docs", NodeType.TOOL),
        "save": ("Save", "Persist chain/agent to disk", NodeType.TOOL),
        "load": ("Load", "Load chain/agent from disk", NodeType.TOOL),
    },
    evolution_methods={
        "memory.save_context": ("Save Memory", "Store conversation context"),
        "memory.clear": ("Clear Memory", "Reset conversation memory"),
    },
    phase_patterns={
        "invoke": 2, "ainvoke": 2, "run": 2, "predict": 2,
        "bind_tools": 2, "with_structured_output": 2,
        "similarity_search": 2, "get_relevant_documents": 2,
        "save_context": 3, "clear": 3,
    },
)


# ── CrewAI profile ────────────────────────────────────────────────────

CREWAI_PROFILE = Profile(
    name="crewai",
    agent_class_names={
        "Agent": "Agent",
        "Crew": "Orchestrator",
        "Task": "Task",
        "Process": "Process",
        "Pipeline": "Pipeline",
        "CrewBase": "CrewBase",
    },
    tool_names={
        "kickoff": ("Kickoff", "CrewAI Crew.kickoff() — execute crew"),
        "kickoff_async": ("Async Kickoff", "CrewAI async crew execution"),
        "kickoff_for_each": ("Kickoff Each", "CrewAI parallel crew execution"),
        "execute_task": ("Execute Task", "CrewAI Task.execute() — single task"),
        "run": ("Run", "CrewAI Agent.run() — execute agent"),
        "delegate_work": ("Delegate Work", "Agent delegation to another agent"),
        "create_task": ("Create Task", "Dynamically create a task"),
        "add_job": ("Add Job", "Add job to pipeline"),
        "process_job": ("Process Job", "Process single pipeline job"),
        "plot": ("Plot", "CrewAI crew.plot() — visualize crew"),
    },
    special_calls={
        "tools.append": ("Add Tool", "Attach tool to agent", NodeType.TOOL),
        "agent.tools": ("Set Tools", "Configure agent tools", NodeType.TOOL),
        "allow_delegation": ("Allow Delegation", "Enable agent delegation", NodeType.TOOL),
        "verbose": ("Verbose", "Enable verbose logging", NodeType.TOOL),
        "max_iter": ("Max Iterations", "Set iteration limit", NodeType.TOOL),
        "memory": ("Memory", "Enable crew memory", NodeType.TOOL),
        "cache": ("Cache", "Enable response caching", NodeType.TOOL),
        "step_callback": ("Step Callback", "Attach step callback", NodeType.TOOL),
        "task_callback": ("Task Callback", "Attach task callback", NodeType.TOOL),
    },
    evolution_methods={
        "store_output": ("Store Output", "Persist task output to memory"),
        "update_memory": ("Update Memory", "Update crew memory with results"),
    },
    phase_patterns={
        "kickoff": 2, "kickoff_async": 2, "run": 2,
        "execute_task": 2, "delegate_work": 2,
        "store_output": 3, "update_memory": 3,
    },
)


# ── AutoGen profile ───────────────────────────────────────────────────

AUTOGEN_PROFILE = Profile(
    name="autogen",
    agent_class_names={
        "AssistantAgent": "Assistant",
        "UserProxyAgent": "UserProxy",
        "GroupChat": "GroupChat",
        "GroupChatManager": "Manager",
        "ConversableAgent": "Conversable",
        "RetrieveAssistantAgent": "RetrieveAssistant",
        "RetrieveUserProxyAgent": "RetrieveProxy",
        "CodeExecutorAgent": "CodeExecutor",
    },
    tool_names={
        "initiate_chat": ("Initiate Chat", "AutoGen — start a conversation"),
        "send": ("Send", "AutoGen — send message to agent"),
        "receive": ("Receive", "AutoGen — receive message"),
        "generate_reply": ("Generate Reply", "AutoGen — generate agent response"),
        "run_code": ("Run Code", "AutoGen — execute code block"),
        "execute_code": ("Execute Code", "AutoGen — code execution"),
        "register_for_llm": ("Register LLM", "AutoGen — register tool for LLM"),
        "register_for_execution": ("Register Execution", "AutoGen — register for code exec"),
        "register_function": ("Register Function", "AutoGen — register callable as tool"),
        "process_message_before_send": ("Pre-send", "AutoGen — process message before send"),
    },
    special_calls={
        "code_execution_config": ("Code Exec Config", "Configure code execution", NodeType.TOOL),
        "human_input_mode": ("Human Input", "Set human input mode", NodeType.TOOL),
        "max_consecutive_auto_reply": ("Max Auto Reply", "Limit auto-reply turns", NodeType.TOOL),
        "temperature": ("Temperature", "Set LLM temperature", NodeType.TOOL),
        "llm_config": ("LLM Config", "Configure LLM settings", NodeType.TOOL),
    },
    evolution_methods={
        "update_system_message": ("Update System", "Modify agent system message"),
        "reset": ("Reset", "Reset agent conversation state"),
    },
    phase_patterns={
        "initiate_chat": 2, "send": 2, "generate_reply": 2,
        "run_code": 2, "execute_code": 2,
        "update_system_message": 3, "reset": 3,
    },
)


PROFILES: dict[str, Profile] = {
    "generic": GENERIC_PROFILE,
    "reaweb": REAWEB_PROFILE,
    "reagame": REAGAME_PROFILE,
    "traceforge": TRACEFORGE_PROFILE,
    "asubarnipal": ASUBARNIPAL_PROFILE,
    "cogniteam": COGNITEAM_PROFILE,
    "agentflow": AGENTFLOW_PROFILE,
    "langchain": LANGCHAIN_PROFILE,
    "crewai": CREWAI_PROFILE,
    "autogen": AUTOGEN_PROFILE,
}


def get_profile(profile: str | Profile | None) -> Profile:
    """Resolve a profile by name, object, or file path."""
    if profile is None:
        return GENERIC_PROFILE
    if isinstance(profile, Profile):
        return profile
    if profile in PROFILES:
        return PROFILES[profile]
    path = Path(profile)
    if path.exists():
        return load_profile(path)
    raise ValueError(
        f"Unknown profile: {profile!r}. "
        f"Built-ins: {sorted(PROFILES)} or path to a .py file."
    )


def load_profile(path: str | Path) -> Profile:
    """Load a custom profile from a Python file exposing ``PROFILE = {...}``.

    The dict fields mirror :class:`Profile` keyword arguments; unknown
    keys raise TypeError so typos surface early.
    """
    source = Path(path).resolve()
    spec = importlib.util.spec_from_file_location(f"agentflow_profile_{source.stem}", source)
    if spec is None or spec.loader is None:
        raise ValueError(f"Cannot load profile module from {source}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    data = getattr(module, "PROFILE", None)
    if not isinstance(data, dict):
        raise TypeError(f"{source} must define a PROFILE dict")

    # Normalize shorthand: tool_names values may be plain strings (label only)
    normalized = dict(data)
    tools = normalized.get("tool_names")
    if isinstance(tools, dict):
        normalized["tool_names"] = {
            k: (v if isinstance(v, tuple) else (str(v), "")) for k, v in tools.items()
        }
    evo = normalized.get("evolution_methods")
    if isinstance(evo, dict):
        normalized["evolution_methods"] = {
            k: (v if isinstance(v, tuple) else (str(v), "")) for k, v in evo.items()
        }
    # Normalize special_calls string node types ("tool", "process", ...)
    _NODE_TYPE_MAP = {
        "start": NodeType.START, "end": NodeType.END, "process": NodeType.PROCESS,
        "decision": NodeType.DECISION, "subprocess": NodeType.SUBPROCESS,
        "tool": NodeType.TOOL, "loop": NodeType.LOOP, "evolution": NodeType.EVOLUTION,
    }
    sc = normalized.get("special_calls")
    if isinstance(sc, dict):
        norm_sc: dict[str, tuple[str, str, NodeType]] = {}
        for k, v in sc.items():
            if not isinstance(v, (list, tuple)) or len(v) != 3:
                norm_sc[k] = v  # let Profile.__init__ raise
                continue
            label, detail, ntype = v
            if isinstance(ntype, str):
                ntype = _NODE_TYPE_MAP.get(ntype.lower(), NodeType.PROCESS)
            norm_sc[k] = (label, detail, ntype)
        normalized["special_calls"] = norm_sc

    return Profile(**normalized)
