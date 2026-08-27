"""Domain profiles for the AgentFlow parser.

A Profile carries all domain-specific knowledge used while parsing agent
source code: known tool names, exhaustive labels, auto-evolution methods,
decision hints and phase patterns. The parser itself is domain-agnostic.

Two built-in profiles are provided:
- GENERIC: no domain knowledge — labels derive from the code itself.
- REAWEB: exhaustive labels for the ReaWeb self-evolving web-design agent.
- REAGAME: exhaustive labels for the ReaGame self-evolving game-design agent.

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
