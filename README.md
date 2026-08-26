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

# Diff two versions (green=added, red=removed, amber=changed)
agentflow diff old.py new.py -o diff.excalidraw
agentflow diff old.py new.py -f mermaid -o diff.mmd

# SVG export, dark theme, deterministic output
agentflow -i my_agent.py -f svg --theme dark --seed 42 -o flow.svg
```

## Features

- **Domain-agnostic parser** — extracts `run()` flow, loops, decisions and calls from any
  Python class or function tree.
- **Profiles** — pluggable domain knowledge (known tools, exhaustive labels, phase patterns).
  Built-ins: `generic` (zero assumptions) and `reaweb`. Load your own from a `.py` file.
- **Three layouts** — `hierarchical` (horizontal + category groups), `phased`
  (vertical FASE 1/2/3 boxes with feedback arrows), `grid`.
- **Smart visuals** — content-driven node sizing, orthogonal arrow routing,
  lateral feedback routes, light/dark themes, optional legend.
- **Repo overview** — point at a directory and get a map of the whole codebase (one node per module, optional import edges).
- **Mermaid export** — `flowchart TD` that renders natively on GitHub/GitLab/Notion, no extra tooling.
- **Progressive detail** — `--detail low|med|high` makes huge graphs readable (low = labels only).
- **Diff mode** — `agentflow diff old.py new.py` highlights added/removed/changed nodes (leverages `--seed` determinism).
- **Interactive HTML** — self-contained `flow.html` with pan/zoom, phase collapse and search (works offline via `file://`).
- **Deterministic output** — pass `--seed` to get byte-identical files (great for CI diffs).
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
| `layouts.py` | hierarchical / phased / grid positioning, text measurement, themes |
| `excalidraw.py` | FlowGraph → Excalidraw JSON (bindings, orthogonal routing) |
| `svg.py` | FlowGraph → standalone SVG |
| `mermaid.py` | FlowGraph → Mermaid flowchart TD |
| `diff.py` | Diff two graphs (added/removed/changed) |
| `html.py` | FlowGraph → interactive HTML (pan/zoom + search) |
| `repo.py` | Directory scan → overview FlowGraph |
| `cli.py` | argparse front-end |

## Development

```bash
python -m pytest tests/ -q   # 62 tests, <1s
python -m ruff check agentflow tests
```

MIT © Vicente Vila
