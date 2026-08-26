"""Domain profiles for the AgentFlow parser.

A Profile carries all domain-specific knowledge used while parsing agent
source code: known tool names, exhaustive labels, auto-evolution methods,
decision hints and phase patterns. The parser itself is domain-agnostic.

Two built-in profiles are provided:
- GENERIC: no domain knowledge — labels derive from the code itself.
- REAWEB: exhaustive labels for the ReaWeb self-evolving web-design agent.

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


REAWEB_PROFILE = Profile(
    name="reaweb",
    tool_names=_REAWEB_TOOL_INFO,
    special_calls=_REAWEB_SPECIAL_CALLS,
    evolution_methods=_REAWEB_EVO_INFO,
    dispatch_attr="name",
    decision_hints=_REAWEB_DECISION_HINTS,
    phase_patterns=_REAWEB_PHASE_PATTERNS,
    init_label=("Init Agent", "Configura LLM, budget, memory,\ncontext manager, harness snapshot"),
)


PROFILES: dict[str, Profile] = {
    "generic": GENERIC_PROFILE,
    "reaweb": REAWEB_PROFILE,
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
