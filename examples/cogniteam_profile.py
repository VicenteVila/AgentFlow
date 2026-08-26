"""Example custom profile for CogniTeam.

Usage:
    agentflow -i cogniteam/core/orchestrator.py --profile examples/cogniteam_profile.py -o out.excalidraw

This profile teaches AgentFlow about CogniTeam-specific tools so they
render as teal TOOL nodes with exhaustive labels instead of generic
subprocesses. It reuses the structural phase detection (cycles → loop)
so no phase_patterns are needed.
"""

PROFILE = {
    "name": "cogniteam",
    "tool_names": {
        "llm_complete": (
            "LLM Complete",
            "Groq/Ollama: envía prompt\n+ contexto → JSON/texto",
        ),
        "get_knowledge_loader": (
            "Knowledge Loader",
            "Carga world-model / YAML\narchetype para el plan",
        ),
        "run_orchestrated_flow": (
            "Run Orchestrated Flow",
            "Orquesta multi-agente:\nplanner → developer → validator",
        ),
        "generate_plan": (
            "Generate Plan",
            "PlannerAgent: genera plan\nestructurado con World Model",
        ),
        "execute_step": (
            "Execute Step",
            "Developer/Debugger: ejecuta\npaso del plan con LLM",
        ),
    },
    "evolution_methods": {
        "_calibrate": (
            "Calibration Store",
            "Guarda métricas de éxito\npara scoping futuro",
        ),
    },
    "special_calls": {
        "_validate_output": (
            "Validate Output",
            "Verifica artefactos generados\nvs plan (file tree, quality)",
            "tool",
        ),
        "_record_step_skill_usage": (
            "Record Skill Usage",
            "Persiste uso de skills\n→ memoria de equipo",
            "evolution",
        ),
    },
}
