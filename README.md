# AgentFlow

**Parse and visualize AI agent control flows as Excalidraw diagrams and SVG.**

AgentFlow reads Python source code of AI agents, extracts the control flow via AST analysis
(loops, decisions, tool dispatch, self-evolution hooks), and renders it as an editable
[Excalidraw](https://excalidraw.com) file or a standalone SVG — no external dependencies.

```bash
pip install -e .

# Single file: works with ANY Python agent
agentflow -i my_agent.py -o flow.excalidraw

# Whole repository overview (each module → one node)
agentflow -i ./my_repo -o repo.excalidraw
agentflow -i ./my_repo --include-imports -o repo_imports.excalidraw  # dashed import edges

# Domain profile with exhaustive labels
agentflow -i my_agent.py --profile reaweb -l phased -o flow.excalidraw

# Mermaid for GitHub, with detail control (orchestrator 133 nodes → readable)
agentflow -i orchestrator.py -f mermaid --detail low -o flow.mmd
agentflow -i ./my_repo -f mermaid -o repo.mmd

# Interactive HTML (pan/zoom, search, collapse phases)
agentflow -i orchestrator.py -f html -o flow.html
agentflow -i ./my_repo -f html --detail low -o repo.html

# Sequence diagram multi-agente (lifelines + mensajes ordenados)
agentflow -i orchestrator.py -f sequence -o seq.svg
agentflow -i orchestrator.py -f mermaid-seq -o seq.mmd   # renderiza en GitHub

# Diff two versions (green=added, red=removed, amber=changed)
agentflow diff old.py new.py -o diff.excalidraw
agentflow diff old.py new.py -f mermaid -o diff.mmd

# Terminal ASCII + Graphviz DOT
agentflow -i orchestrator.py -f ascii --detail low
agentflow -i my_agent.py -f dot -o flow.dot   # → dot -Tsvg flow.dot

# Palettes: light | dark | pastel | neon | mono | dungeon | violet | sandy | ocean (--palette = alias de --theme)
agentflow -i my_agent.py -f svg --palette neon -o flow.svg

# Nueva generación completa: jerarquía muñecas rusas L0→L1→L2→L3
agentflow -i ./mi_repo --drilldown -t MiProyecto --output-dir ./flow_output

# Mermaid plano y horizontal (sin cajas FASE) + tema aplicado a los nodos
agentflow -i my_agent.py -f mermaid -l phased --no-phases --theme neon -o flow.mmd

# SVG export, dark theme, deterministic output
agentflow -i my_agent.py -f svg --theme dark --seed 42 -o flow.svg
```

## Features

- **Domain-agnostic parser** — extracts `run()` flow, loops, decisions and calls from any
  Python class or function tree.
- **Profiles** — pluggable domain knowledge (known tools, exhaustive labels, phase patterns).
  Built-ins: `generic` (zero assumptions) and `reaweb`. Load your own from a `.py` file.
- **Six layouts** — `hierarchical` (horizontal), `phased` (vertical FASE 1/2/3), `phased-horizontal` (fases en columnas), `radial` (anillos alrededor del agente central), `swimlane` (vertical lanes per actor), `grid`.
- **Smart visuals** — content-driven sizing, orthogonal routing, swimlanes, lateral feedback, light/dark themes, **semantic edge colors** (YES green / NO red / loop blue).
- **Repo overview** — point at a directory and get a map of the whole codebase (one node per module, optional import edges).
- **Drill-down (muñecas rusas)** — `--drilldown` sobre un directorio genera toda la jerarquía recursiva L0 (overview) → paquetes → ficheros → splits por función/clase como `.mmd` + `.html` interactivos con click-links, botón «← Volver» e `index.html`. Hereda `--theme` / `--no-phases` / `--layout` y resuelve symlinks (incluye la carpeta oculta `.agent`).
- **Mermaid export** — `flowchart TD` / `LR` que renderiza natively en GitHub/GitLab/Notion, no extra tooling. `--theme` colorea los nodos (`classDef`) y `--no-phases` deja el flujo plano y horizontal sin cajas FASE.
- **Progressive detail** — `--detail low|med|high` makes huge graphs readable (low = labels only).
- **Diff mode** — `agentflow diff old.py new.py` highlights added/removed/changed nodes (leverages `--seed` determinism).
- **Sequence diagrams** — `-f sequence` / `-f mermaid-seq`: lifelines por agente (Planner/LLM/Memory…), mensajes ordenados por línea.
- **Interactive HTML** — self-contained `flow.html` with pan/zoom, phase collapse and search (works offline via `file://`).
- **Deterministic output** — pass `--seed` to get byte-identical files (great for CI diffs).
- **6 output formats** — excalidraw · svg · mermaid · html · **ascii** (terminal) · **dot** (Graphviz).
- **9 palettes** — light, dark, pastel, neon, mono, dungeon (garabato kraft), violet, sandy, ocean vía `--palette`.
- **SVG export** — same geometry, zero dependencies.

## Profiles

The parser ships without domain knowledge. A profile teaches it about your agent:

```python
# my_profile.py
PROFILE = {
    "name": "my-agent",
    "tool_names": {
        "deploy": ("Deploy App", "Sube el build a producción"),
        "run_tests": "Run Tests",          # shorthand: label only
    },
    "evolution_methods": {"_learn": ("Learn", "Persiste lecciones del run")},
    "phase_patterns": {"init": 1, "learn": 2, "export": 3},
}
```

```bash
agentflow -i my_agent.py --profile my_profile.py -o flow.excalidraw
```

Phase detection is structural by default: cycles in the graph become the *loop* phase
(FASE 2), their ancestors the *init* phase (FASE 1) and the rest the *close* phase (FASE 3).

## Architecture

```
source.py ──▶ parser (AST + Profile) ──▶ FlowGraph ──▶ layouts ──┬─▶ excalidraw (.excalidraw)
                                                                 └─▶ svg (.svg)
models.py     Node / Edge / FlowGraph          profiles.py   generic · reaweb · custom
```

| Module | Responsibility |
|---|---|
| `parser.py` | AST → FlowGraph (domain knowledge comes from the profile) |
| `profiles.py` | `Profile` dataclass, built-ins, custom loader |
| `layouts.py` | hierarchical / phased / phased-horizontal / radial / grid / swimlane positioning, text measurement, themes |
| `excalidraw.py` | FlowGraph → Excalidraw JSON (bindings, orthogonal routing) |
| `svg.py` | FlowGraph → standalone SVG |
| `mermaid.py` | FlowGraph → Mermaid flowchart TD |
| `diff.py` | Diff two graphs (added/removed/changed) |
| `html.py` | FlowGraph → interactive HTML (pan/zoom + search) |
| `sequence.py` | Interacciones entre agentes → sequence diagram |
| `repo.py` | Directory scan → overview FlowGraph |
| `cli.py` | argparse front-end |

## Development

```bash
python -m pytest tests/ -q   # 71 tests, <1s
python -m ruff check agentflow tests
```

MIT © Vicente Vila
