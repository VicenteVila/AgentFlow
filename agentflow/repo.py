"""Repository overview: scan a directory of Python files and build a
high-level FlowGraph where each module/agent becomes one node.

Usage:
    graph = build_repo_overview(Path("./cogniteam"), profile="generic")

The overview graph uses START → file nodes → END and, when
``include_imports`` is True, adds dashed edges mirroring intra-repo
import dependencies.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

from agentflow.models import Edge, FlowGraph, Node, NodeType
from agentflow.parser import parse_file

_EXCLUDE_DIRS = {".git", ".venv", "venv", "venv_linux", "venv_windows",
                 "__pycache__", ".pytest_cache", "node_modules", ".mypy_cache",
                 ".ruff_cache", "dist", "build", "htmlcov", ".tox", "eggs",
                 "*.egg-info", "data", "obsidian_vault", "ingesta", "ingestion"}


def collect_python_files(root: Path, exclude: set[str] | None = None,
                         include_hidden: bool = False) -> list[Path]:
    """Recursively collect ``*.py`` files under *root*, skipping noise dirs.

    When *include_hidden* is True, dot-directories (e.g. ``.agent/``) and
    directory symlinks are also scanned, so hidden agent cores are found.
    """
    excl = _EXCLUDE_DIRS | (exclude or set())
    files: list[Path] = []
    seen: set[Path] = set()
    for dirpath, dirnames, filenames in os.walk(root, followlinks=True):
        # prune noise dirs in place
        kept = []
        for d in dirnames:
            full = Path(dirpath) / d
            rel_parts = full.relative_to(root).parts
            if any(part in excl for part in rel_parts):
                continue
            if (not include_hidden) and any(part.startswith(".") for part in rel_parts):
                continue
            kept.append(d)
        for d in dirnames:
            if d not in kept:
                dirnames.remove(d)
        for fn in sorted(filenames):
            if not fn.endswith(".py"):
                continue
            full = Path(dirpath) / fn
            if any(
                part in excl or ((not include_hidden) and part.startswith("."))
                for part in full.relative_to(root).parts
            ):
                continue
            if str(full).endswith(".pyc"):
                continue
            try:
                if full.stat().st_size < 20:
                    continue
            except OSError:
                continue
            resolved = full.resolve()
            if resolved in seen:
                continue
            seen.add(resolved)
            files.append(full)
    return sorted(files)


def _module_name(root: Path, file: Path) -> str:
    """Dotted module name of *file* relative to *root* (e.g. cogniteam.core.planner)."""
    rel = file.relative_to(root).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _parse_imports(file: Path) -> set[str]:
    """Return imported dotted names found in *file* (best-effort)."""
    try:
        tree = ast.parse(file.read_text(encoding="utf-8"))
    except Exception:
        return set()
    imports: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module)
    return imports


def _classify_file_graph(g: FlowGraph) -> NodeType:
    """Pick a NodeType for the overview node based on the file's contents."""
    types = {n.node_type for n in g.nodes}
    if NodeType.LOOP in types:
        return NodeType.LOOP
    if NodeType.TOOL in types:
        return NodeType.TOOL
    if NodeType.DECISION in types:
        return NodeType.PROCESS
    # many subprocess nodes → likely a utility module
    sub = sum(1 for n in g.nodes if n.node_type == NodeType.SUBPROCESS)
    if sub >= 5:
        return NodeType.SUBPROCESS
    return NodeType.PROCESS


def build_repo_overview(
    root: str | Path,
    profile: str | object | None = None,
    include_imports: bool = False,
    title: str | None = None,
    include_hidden: bool = False,
) -> FlowGraph:
    """Scan *root* and return an overview FlowGraph.

    Each Python file with >2 nodes becomes one overview node. When
    *include_imports* is True, import edges between overview nodes are added
    as dashed edges. Set *include_hidden* to also scan dot-directories
    (e.g. ``.agent/``) via :func:`collect_python_files`.
    """
    root = Path(root).resolve()
    if not root.is_dir():
        raise ValueError(f"Not a directory: {root}")

    files = collect_python_files(root, include_hidden=include_hidden)
    # Parse each file; keep only non-trivial graphs
    file_graphs: list[tuple[Path, FlowGraph]] = []
    for f in files:
        try:
            g = parse_file(f, profile=profile)
        except Exception:
            continue
        # filter: at least one meaningful node beyond start/end
        if g.node_count <= 2:
            continue
        # filter tiny utility files (< 3 edges and no decisions)
        has_flow = g.edge_count >= 2 or any(
            n.node_type in (NodeType.LOOP, NodeType.DECISION, NodeType.TOOL)
            for n in g.nodes
        )
        if not has_flow and g.node_count < 5:
            continue
        file_graphs.append((f, g))

    if not file_graphs:
        # fallback: at least show that the repo was scanned
        g = FlowGraph(title=title or f"Repo: {root.name} (empty)")
        g.add_node(Node(id="start", label="Start", node_type=NodeType.START))
        g.add_node(Node(id="end", label="End", node_type=NodeType.END))
        g.add_edge(Edge(source="start", target="end", label="no agents found"))
        return g

    overview = FlowGraph(title=title or f"Repo: {root.name}")
    overview.add_node(Node(id="start", label="Start", node_type=NodeType.START))

    id_map: dict[str, str] = {}  # module name -> overview node id
    for file, g in file_graphs:
        mod = _module_name(root, file)
        nid = "mod_" + mod.replace(".", "_")
        # label: short file stem + agent class if found
        agent_classes = [n.label for n in g.nodes if n.node_type == NodeType.SUBPROCESS and "Agent" in n.label]
        label = agent_classes[0] if agent_classes else file.stem.replace("_", " ").title()
        # detail: stats + relative path
        rel = str(file.relative_to(root))
        detail = f"{rel}\n{g.node_count} nodes, {g.edge_count} edges"
        ntype = _classify_file_graph(g)
        overview.add_node(Node(id=nid, label=label, detail=detail, node_type=ntype))
        id_map[mod] = nid

    # Chain: start → first → ... → last → end (gives a readable left→right flow)
    ordered_ids = [nid for _, nid in sorted(id_map.items())]
    if ordered_ids:
        overview.add_edge(Edge(source="start", target=ordered_ids[0]))
        for a, b in zip(ordered_ids, ordered_ids[1:], strict=False):
            overview.add_edge(Edge(source=a, target=b))
        overview.add_node(Node(id="end", label="End", node_type=NodeType.END))
        overview.add_edge(Edge(source=ordered_ids[-1], target="end"))

    if include_imports:
        for file, _ in file_graphs:
            src_mod = _module_name(root, file)
            src_id = id_map.get(src_mod)
            if not src_id:
                continue
            for imp in _parse_imports(file):
                # match import against known modules (prefix match)
                for target_mod, target_id in id_map.items():
                    if imp == target_mod or imp.startswith(target_mod + ".") or target_mod.startswith(imp + "."):
                        if target_id != src_id:
                            overview.add_edge(Edge(source=src_id, target=target_id, label="imports", style="dashed"))
                        break

    return overview
