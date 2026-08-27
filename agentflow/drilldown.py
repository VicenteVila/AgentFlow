"""Exhaustive recursive drill-down (matryoshka) diagram generator.

Given a repo root, generate a hierarchy of linked flowcharts where each
complexity is subdivided into its own diagram:

    L0_Overview                 <- repo overview (top-level actors)
    L{n}_<Package>              <- overview of each package directory
    L{n}_<Path...>              <- per-file flow (n = path depth)
    L{n+1}_<Path...>_<Group>    <- function/class-level splits

Every overview node links down to its child flowchart via Mermaid ``click``
directives; every page carries a ``← Volver`` back-link to its parent; and an
``index.html`` hub lets you navigate all levels.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from agentflow.layouts import with_detail_level
from agentflow.mermaid import save_mermaid, save_mermaid_html
from agentflow.models import Edge, FlowGraph, Node, NodeType
from agentflow.parser import parse_class_methods, parse_file, parse_functions
from agentflow.profiles import Profile
from agentflow.repo import _classify_file_graph

# Directories never turned into flowcharts (data / tests / docs).
_EXCLUDED_DIRS = {
    "test", "tests", "datasets", "fixtures", "templates", "workspace",
    "runs", "docs", "website", "assets", "migrations",
}

_SKIP_DIRS = _EXCLUDED_DIRS | {
    "venv", ".venv", "__pycache__", ".git", ".pytest_cache", ".ruff_cache",
    ".mypy_cache", "node_modules", "egg-info", "*.egg-info", "dist",
    "build", "htmlcov", ".tox",
}

# Function-level splits: dotted module path -> [(group label, [function names])].
# A file listed here is NOT emitted whole; each group becomes its own flowchart.
FUNCTION_SPLITS: dict[str, list[tuple[str, list[str]]]] = {
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

# Class-level splits: dotted module path -> [class names to expand each alone].
CLASS_SPLITS: dict[str, list[str]] = {
    "tools.domain.web_generator": [
        "InspectArchetype", "FetchUrl", "GenerateCandidate", "AuditPage",
        "UpdateLessons", "SelectFinal", "RevertWorkspace",
    ],
}

_MAX_DEPTH = 6


@dataclass
class _Ctx:
    repo_root: Path
    out_dir: Path
    prefix: str
    profile: str | Profile | None
    layout: str
    theme: str
    no_phases: bool
    include_hidden: bool
    index: list[dict[str, object]]
    graph_cache: dict[Path, FlowGraph | None]

    def graph_of(self, file: Path) -> FlowGraph | None:
        resolved = file.resolve()
        if resolved in self.graph_cache:
            return self.graph_cache[resolved]
        try:
            g = parse_file(str(file), profile=self.profile)
        except (ValueError, SyntaxError, OSError):
            g = None
        if g is not None and g.node_count <= 2:
            g = None
        self.graph_cache[resolved] = g
        return g


def _title_segments(segments: list[str]) -> str:
    parts = [s[0].upper() + s[1:] if s else s for s in segments]
    return "_".join(parts)


def _level_name(prefix: str, level: int, segments: list[str]) -> str:
    if not segments:
        return f"{prefix}_L0_Overview"
    return f"{prefix}_L{level}_{_title_segments(segments)}"


def _display_title(file: Path) -> str:
    return file.stem.replace("_", " ").title()


def _module_name(ctx: _Ctx, file: Path) -> str:
    return ".".join(_rel_segments(ctx, file))


def _rel_segments(ctx: _Ctx, file: Path) -> list[str]:
    parts = list(file.relative_to(ctx.repo_root).with_suffix("").parts)
    if parts and parts[0].startswith("."):
        parts[0] = parts[0].lstrip(".")
    if parts and parts[-1] == "__init__":
        parts.pop()
    return parts


def _collect_dirs(ctx: _Ctx, root: Path) -> list[Path]:
    """Immediate subdirs to scan (deduplicated by real path, dotless preferred)."""
    raw: dict[Path, Path] = {}
    for p in root.iterdir():
        if not p.is_dir() or p.name in _SKIP_DIRS:
            continue
        if not ctx.include_hidden and p.name.startswith("."):
            continue
        resolved = p.resolve()
        cur = raw.get(resolved)
        if cur is None or (not p.name.startswith(".") and cur.name.startswith(".")):
            raw[resolved] = p
    return sorted(raw.values(), key=lambda p: p.name.lower())


def _flow_files_in(ctx: _Ctx, dir_path: Path, recursive: bool) -> list[Path]:
    """Python files under *dir_path* that parse to a real flow."""
    seen: set[Path] = set()
    result: list[Path] = []
    if recursive:
        candidates = [p for p in dir_path.rglob("*.py")
                      if not any(part in _SKIP_DIRS
                                 for part in p.relative_to(dir_path).parts)]
    else:
        candidates = [p for p in dir_path.iterdir() if p.is_file() and p.suffix == ".py"]
    for p in sorted(candidates, key=lambda pp: pp.name.lower()):
        if p.name == "__init__.py" or p.name.startswith("."):
            continue
        resolved = p.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if ctx.graph_of(p) is not None:
            result.append(p)
    return result


def _warrants_overview(ctx: _Ctx, dir_path: Path) -> bool:
    immediate = _flow_files_in(ctx, dir_path, recursive=False)
    if len(immediate) >= 2:
        return True
    subdirs = _collect_dirs(ctx, dir_path)
    if any(_flow_files_in(ctx, d, recursive=True) for d in subdirs):
        return True
    return len(_flow_files_in(ctx, dir_path, recursive=True)) >= 2


def _split_overview_father(
    title: str,
    items: list[tuple[str, str]],
) -> tuple[FlowGraph, dict[str, str]]:
    """Fallback father: one node per class/group, each linked to its drill-down.

    ``items`` are ``(node_id_suffix, label)`` pairs; returns the graph plus a
    ``{node_id: href}`` map (href filled in by the caller).
    """
    overview = FlowGraph(title=title)
    nid_key: list[str] = []
    prev = "start"
    overview.add_node(Node(id="start", label="Start", node_type=NodeType.START))
    for i, (_, label) in enumerate(items):
        nid = f"mod_{i}"
        overview.add_node(Node(id=nid, label=label, node_type=NodeType.SUBPROCESS))
        overview.add_edge(Edge(source=prev, target=nid))
        nid_key.append(nid)
        prev = nid
    overview.add_node(Node(id="end", label="End", node_type=NodeType.END))
    if nid_key:
        overview.add_edge(Edge(source=prev, target="end"))
    return overview, {nid: "" for nid in nid_key}


def _parent_href(ctx: _Ctx, level: int, segments: list[str]) -> str | None:
    if not segments or level == 0:
        return None
    return f"{_level_name(ctx.prefix, level - 1, segments[:-1])}.html"


def _save_artifact(
    ctx: _Ctx,
    name: str,
    graph: FlowGraph,
    level: int,
    title: str,
    links: dict[str, str] | None,
    back: str | None,
) -> None:
    save_mermaid(
        graph, ctx.out_dir / f"{name}.mmd", layout=ctx.layout, detail="high",
        links=links, title=title, theme=ctx.theme, no_phases=ctx.no_phases,
    )
    save_mermaid_html(
        graph, ctx.out_dir / f"{name}.html", layout=ctx.layout, detail="high",
        links=links, back_link=back, title=title, theme=ctx.theme,
        no_phases=ctx.no_phases,
    )
    ctx.index.append({
        "level": level,
        "name": name,
        "title": title,
        "href": f"{name}.html",
        "back": back,
    })


def _handle_dir(ctx: _Ctx, root: Path, segments: list[str], level: int) -> str:
    """Generate flowcharts for *root* and its descendants.

    Returns the ``<name>`` (without extension) of the overview saved here,
    which the parent uses as the ``click`` target for this directory's node.
    """
    if level > _MAX_DEPTH:
        return _handle_dir_shallow(ctx, root, segments, level)

    # ── Plan children ────────────────────────────────────────────────
    overview_children: list[tuple[Path, str]] = []
    file_children: list[tuple[Path, list[str]]] = []
    seen_files: set[Path] = set()

    for d in _collect_dirs(ctx, root):
        if not _flow_files_in(ctx, d, recursive=True):
            continue
        if _warrants_overview(ctx, d):
            overview_children.append((d, d.name))
        else:
            for f in _flow_files_in(ctx, d, recursive=True):
                r = f.resolve()
                if r in seen_files:
                    continue
                seen_files.add(r)
                file_children.append((f, _rel_segments(ctx, f)))

    for f in _flow_files_in(ctx, root, recursive=False):
        r = f.resolve()
        if r in seen_files:
            continue
        seen_files.add(r)
        file_children.append((f, _rel_segments(ctx, f)))

    parent_href = _parent_href(ctx, level, segments)

    # ── Children first (their hrefs feed the parent overview) ────────
    child_hrefs: dict[str, str] = {}
    for dir_path, seg in overview_children:
        child_segments = segments + [seg.lstrip(".")]
        child_level = level + 1
        child_name = _level_name(ctx.prefix, child_level, child_segments)
        _handle_dir(ctx, dir_path, child_segments, child_level)
        child_hrefs[seg] = f"{child_name}.html"

    for file, _rel in file_children:
        base_name = _level_name(ctx.prefix, level + 1, _rel)
        split_name = _level_name(ctx.prefix, level + 2, _rel)
        module = _module_name(ctx, file)
        overview_target = f"{_level_name(ctx.prefix, level, segments)}.html"
        if not segments:
            overview_target = f"{ctx.prefix}_L0_Overview.html"

        if module in FUNCTION_SPLITS:
            groups = FUNCTION_SPLITS[module]
            child_links: dict[str, str] = {}
            for group, funcs in groups:
                name = f"{split_name}_{group}"
                for func in funcs:
                    child_links[f"fn_{func}"] = f"{name}.html"
            items = [(g, f"{g} · {len(fs)} funciones")
                     for g, fs in groups]
            for group, funcs in groups:
                name = f"{split_name}_{group}"
                sub = parse_functions(file, funcs, profile=ctx.profile,
                                      title=f"{_display_title(file)} · {group}")
                _save_artifact(ctx, name, sub, level + 2,
                               f"{_display_title(file)} · {group}", None,
                               f"{base_name}.html")
            child_hrefs[file.stem] = f"{base_name}.html"
        elif module in CLASS_SPLITS:
            child_links = {}
            for cls in CLASS_SPLITS[module]:
                name = f"{split_name}_{cls}"
                for node_id in (f"fn_{cls.lower()}_{m}".lower()
                                for m in ("run", "schema", "__init__")):
                    child_links[node_id] = f"{name}.html"
            items = [(cls, f"{_title_segments([cls])} · clase") for cls in CLASS_SPLITS[module]]
            for cls in CLASS_SPLITS[module]:
                name = f"{split_name}_{cls}"
                sub = parse_class_methods(file, cls, profile=ctx.profile,
                                          title=f"{_display_title(file)} · {cls}")
                _save_artifact(ctx, name, sub, level + 2,
                               f"{_display_title(file)} · {cls}", None,
                               f"{base_name}.html")
            child_hrefs[file.stem] = f"{base_name}.html"
        else:
            g = ctx.graph_of(file)
            if g is None:
                continue
            _save_artifact(ctx, base_name, with_detail_level(g, "high"),
                           level + 1, _display_title(file), None, overview_target)
            child_hrefs[file.stem] = f"{base_name}.html"

        # ── Split-file father: whole-flow, else per-group overview ────
        if module in FUNCTION_SPLITS or module in CLASS_SPLITS:
            father = ctx.graph_of(file)
            if father is not None:
                valid = {n.id for n in father.nodes}
                links = {k: v for k, v in child_links.items() if k in valid} or None
            else:
                links = None
            if links:
                _save_artifact(ctx, base_name, with_detail_level(father, "high"),
                               level + 1, _display_title(file), links, overview_target)
            else:
                overview, link_map = _split_overview_father(
                    _display_title(file), items)
                hrefs = {nid: f"{split_name}_{label}.html"
                         for nid, (label, _detail)
                         in zip(link_map, items, strict=True)}
                _save_artifact(ctx, base_name, overview, level + 1,
                               _display_title(file), hrefs, overview_target)

    # ── Overview of this directory ───────────────────────────────────
    overview = _build_overview(ctx, root, overview_children, file_children)
    if overview is None:
        return ""

    name = _level_name(ctx.prefix, level, segments)
    title = ctx.prefix
    if segments:
        title = f"{ctx.prefix} · {' · '.join(segments)}"
    _save_artifact(ctx, name, overview, level, title,
                   {f"mod_{_safe_mod(seg)}": href for seg, href in child_hrefs.items()},
                   parent_href)
    return name


def _handle_dir_shallow(ctx: _Ctx, root: Path, segments: list[str], level: int) -> str:
    """Depth-guard fallback: only this directory's file flows."""
    for f in _flow_files_in(ctx, root, recursive=True):
        g = ctx.graph_of(f)
        if g is None:
            continue
        name = _level_name(ctx.prefix, level + 1, _rel_segments(ctx, f))
        _save_artifact(ctx, name, with_detail_level(g, "high"), level + 1,
                       _display_title(f), None,
                       f"{_level_name(ctx.prefix, level, segments)}.html"
                       if segments else f"{ctx.prefix}_L0_Overview.html")
    return ""


def _build_overview(
    ctx: _Ctx,
    root: Path,
    overview_children: list[tuple[Path, str]],
    file_children: list[tuple[Path, list[str]]],
) -> FlowGraph | None:
    """Overview whose nodes are this directory's immediate actors."""
    overview = FlowGraph(title="")

    actors: list[tuple[str, str, NodeType, str]] = []  # (seg, label, type, detail)
    for dir_path, seg in overview_children:
        total = len(_flow_files_in(ctx, dir_path, recursive=True))
        actors.append((seg, seg.replace("_", " ").title(),
                       NodeType.SUBPROCESS, f"{total} sub-flujos"))
    for file, _rel in file_children:
        g = ctx.graph_of(file)
        if g is None:
            continue
        actors.append((file.stem, _display_title(file), _classify_file_graph(g),
                       f"{g.node_count} nodos, {g.edge_count} enlaces"))

    if not actors:
        return None

    overview.add_node(Node(id="start", label="Start", node_type=NodeType.START))
    prev = "start"
    for seg, label, ntype, detail in actors:
        nid = f"mod_{_safe_mod(seg)}"
        overview.add_node(Node(id=nid, label=label, detail=detail, node_type=ntype))
        overview.add_edge(Edge(source=prev, target=nid))
        prev = nid
    overview.add_node(Node(id="end", label="End", node_type=NodeType.END))
    overview.add_edge(Edge(source=prev, target="end"))
    return overview


def _safe_mod(seg: str) -> str:
    return "".join(ch if (ch.isalnum() or ch == "_") else "_" for ch in seg)


def _write_index(ctx: _Ctx) -> None:
    by_level: dict[int, list[dict[str, object]]] = {}
    for e in ctx.index:
        by_level.setdefault(int(e["level"]), []).append(e)

    rows: list[str] = []
    for level in sorted(by_level):
        rows.append("  <section class='lvl'>\n")
        rows.append(f"    <h2>Nivel L{level}</h2>\n")
        rows.append("    <ul>\n")
        for e in sorted(by_level[level], key=lambda x: str(x["name"])):
            rows.append(
                f"      <li><a href=\"{e['href']}\">{e['name']}</a>"
                f"<span class='t'>{e['title']}</span></li>\n"
            )
        rows.append("    </ul>\n")
        rows.append("  </section>\n")

    (ctx.out_dir / "index.html").write_text(
        _INDEX_TEMPLATE.format(
            title=f"{ctx.prefix} · Drill-down completo",
            body="".join(rows),
        ),
        encoding="utf-8",
    )


_INDEX_TEMPLATE = """\
<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <style>
    body {{ margin: 0; padding: 28px; font-family: system-ui,-apple-system,sans-serif;
            background: #0b0b0f; color: #e0e0e0; }}
    h1 {{ font-size: 1.4rem; color: #00ff88; margin: 0 0 4px 0; }}
    p.lead {{ font-size: 0.9rem; color: #94a3b8; margin: 0 0 22px 0; }}
    section.lvl {{ margin-bottom: 22px; }}
    h2 {{ font-size: 1rem; color: #facc15; border-bottom: 1px solid #2a2a35;
          padding-bottom: 6px; }}
    ul {{ list-style: none; padding: 0; display: grid;
          grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 6px; }}
    li {{
      background: #16161d; border: 1px solid #26262f; border-radius: 8px;
      padding: 8px 12px; font-size: 0.85rem;
    }}
    li:hover {{ border-color: #8b5cf6; }}
    a {{ color: #8b5cf6; text-decoration: none; font-weight: 600; }}
    a:hover {{ text-decoration: underline; color: #a78bfa; }}
    .t {{ color: #94a3b8; margin-left: 8px; }}
  </style>
</head>
<body>
  <h1>{title}</h1>
  <p class="lead">Cada gráfica es un flujograma Mermaid. Haz click en los nodos de
  una vista para bajar de nivel; cada página incluye un &laquo;Volver&raquo; al padre.</p>
{body}
</body>
</html>
"""


def run_drilldown(
    input_dir: str | Path,
    out_dir: str | Path | None = None,
    prefix: str = "flow",
    *,
    profile: str | Profile | None = "reaweb",
    layout: str = "phased-horizontal",
    theme: str = "neon",
    no_phases: bool = True,
    include_hidden: bool = True,
) -> list[dict[str, object]]:
    """Generate the exhaustive drill-down hierarchy and return index entries."""
    repo_root = Path(input_dir).resolve()
    if not repo_root.is_dir():
        raise ValueError(f"Not a directory: {repo_root}")

    if out_dir is None:
        out_dir = Path("drilldown_output")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    assets_src = Path(__file__).parent.parent / "examples" / "reaweb_flows" / "assets"
    if assets_src.is_dir() and not (out_dir / "assets").is_dir():
        shutil.copytree(assets_src, out_dir / "assets")

    ctx = _Ctx(
        repo_root=repo_root,
        out_dir=out_dir,
        prefix=prefix,
        profile=profile,
        layout=layout,
        theme=theme,
        no_phases=no_phases,
        include_hidden=include_hidden,
        index=[],
        graph_cache={},
    )

    _handle_dir(ctx, repo_root, [], 0)
    _write_index(ctx)
    return ctx.index
