"""Command-line interface for AgentFlow.

Usage:
    agentflow --input agent.py --output flowchart.excalidraw
    agentflow --input agent.py --output flowchart.excalidraw --layout phased
    agentflow -i ./my_repo -o repo.mmd -f mermaid --detail low
    agentflow diff old.py new.py -o diff.excalidraw
    agentflow --input agent.py  # prints to stdout as JSON
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agentflow import __version__


def _handle_diff(argv: list[str]) -> None:
    parser = argparse.ArgumentParser(
        prog="agentflow diff",
        description="Diff two agent files and render the merged graph (green=added, red=removed, amber=changed).",
    )
    parser.add_argument("old", help="Old version of the file")
    parser.add_argument("new", help="New version of the file")
    parser.add_argument("-o", "--output", default=None, help="Output file path")
    parser.add_argument("-l", "--layout", choices=["hierarchical", "grid", "phased", "phased-horizontal", "radial", "swimlane"], default="hierarchical")
    parser.add_argument("-f", "--format", choices=["excalidraw", "svg", "mermaid", "mermaid-html", "html"], default="excalidraw")
    parser.add_argument("--profile", default="generic")
    parser.add_argument("-t", "--title", default=None)
    parser.add_argument("--theme", choices=["light", "dark", "pastel", "neon", "mono", "dungeon", "violet", "sandy", "ocean"], default="light")
    parser.add_argument("--palette", choices=["light", "dark", "pastel", "neon", "mono", "dungeon", "violet", "sandy", "ocean"], default=None, help="Alias for --theme")
    parser.add_argument("--no-legend", action="store_true")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--detail", choices=["low", "med", "high"], default="high")
    parser.add_argument("--no-phases", action="store_true",
                        help="Mermaid only: flatten phased without FASE boxes (left→right)")
    args = parser.parse_args(argv)
    if args.palette:
        args.theme = args.palette

    old_p = Path(args.old)
    new_p = Path(args.new)
    for path in (old_p, new_p):
        if not path.exists():
            print(f"Error: file not found: {path}", file=sys.stderr)
            sys.exit(1)

    from agentflow.diff import diff_files

    try:
        graph = diff_files(str(old_p), str(new_p), profile=args.profile)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)
    if args.title:
        graph.title = args.title

    if args.format == "svg":
        from agentflow.svg import save_svg, to_svg

        if args.output:
            path = save_svg(graph, args.output, layout=args.layout, theme=args.theme,
                            legend=not args.no_legend, detail=args.detail)
            print(f"OK: {path} ({graph.node_count} nodes, {graph.edge_count} edges)")
        else:
            sys.stdout.write(to_svg(graph, layout=args.layout, theme=args.theme,
                                    legend=not args.no_legend, detail=args.detail))
        return
    if args.format == "mermaid":
        from agentflow.mermaid import save_mermaid, to_mermaid

        if args.output:
            path = save_mermaid(graph, args.output, layout=args.layout, detail=args.detail,
                                theme=args.theme, no_phases=args.no_phases)
            print(f"OK: {path} ({graph.node_count} nodes, {graph.edge_count} edges)")
        else:
            sys.stdout.write(to_mermaid(graph, layout=args.layout, detail=args.detail,
                                        theme=args.theme, no_phases=args.no_phases))
        return

    if args.format == "mermaid-html":
        from agentflow.mermaid import save_mermaid_html, to_mermaid_html

        if args.output:
            path = save_mermaid_html(graph, args.output, layout=args.layout, detail=args.detail,
                                     theme=args.theme, no_phases=args.no_phases)
            print(f"OK: {path} ({graph.node_count} nodes, {graph.edge_count} edges)")
        else:
            sys.stdout.write(to_mermaid_html(graph, layout=args.layout, detail=args.detail,
                                             theme=args.theme, no_phases=args.no_phases))
        return

    if args.format == "html":
        from agentflow.html import save_html, to_html

        if args.output:
            path = save_html(graph, args.output, layout=args.layout, theme=args.theme, legend=not args.no_legend, detail=args.detail)
            print(f"OK: {path} ({graph.node_count} nodes, {graph.edge_count} edges)")
        else:
            sys.stdout.write(to_html(graph, layout=args.layout, theme=args.theme, legend=not args.no_legend, detail=args.detail))
        return
    if args.format == "ascii":
        from agentflow.ascii import save_ascii, to_ascii
        if args.output:
            path = save_ascii(graph, args.output, detail=args.detail)
            print(f"OK: {path} ({graph.node_count} nodes, {graph.edge_count} edges)")
        else:
            sys.stdout.write(to_ascii(graph, detail=args.detail))
        return
    if args.format == "dot":
        from agentflow.dot import save_dot, to_dot
        if args.output:
            path = save_dot(graph, args.output, detail=args.detail)
            print(f"OK: {path} ({graph.node_count} nodes, {graph.edge_count} edges)")
        else:
            sys.stdout.write(to_dot(graph, detail=args.detail))
        return
    from agentflow.excalidraw import save_excalidraw, to_excalidraw

    if args.output:
        path = save_excalidraw(graph, args.output, layout=args.layout, theme=args.theme,
                               legend=not args.no_legend, seed=args.seed, detail=args.detail)
        print(f"OK: {path} ({graph.node_count} nodes, {graph.edge_count} edges)")
    else:
        doc = to_excalidraw(graph, layout=args.layout, theme=args.theme,
                            legend=not args.no_legend, seed=args.seed, detail=args.detail)
        json.dump(doc, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")


def _handle_drilldown(args, input_path: Path) -> None:
    """Generate the exhaustive drill-down hierarchy (L0 → L1 → L2 → L3)."""
    from agentflow.drilldown import run_drilldown
    from agentflow.layouts import with_detail_level
    from agentflow.mermaid import save_mermaid, save_mermaid_html
    from agentflow.parser import parse_file

    out_dir = Path(args.output_dir) if args.output_dir else Path("drilldown_output")
    prefix = args.title or "agentflow"

    if input_path.is_dir():
        entries = run_drilldown(
            input_path,
            out_dir=out_dir,
            prefix=prefix,
            profile=args.profile,
            layout=args.layout,
            theme=args.theme,
            no_phases=bool(getattr(args, "no_phases", False)),
        )
        overview = next((e for e in entries if e["name"].endswith("L0_Overview")), None)
        if overview:
            print(f"Drill-down completado: {len(entries)} flowcharts en {out_dir}/")
            print(f"  Entrada: {input_path}")
            print(f"  Abre {out_dir / overview['href']} o {out_dir / 'index.html'}")
        else:
            print(f"Drill-down completado (sin L0): {len(entries)} flowcharts en {out_dir}/")
        return

    # Single file: L0/L1 direct
    g0 = parse_file(str(input_path), profile=args.profile)
    g0 = with_detail_level(g0, "high")
    name = f"{prefix}_L1_Main"
    save_mermaid(g0, out_dir / f"{name}.mmd", layout=args.layout, detail="high",
                 theme=args.theme, no_phases=bool(getattr(args, "no_phases", False)))
    save_mermaid_html(g0, out_dir / f"{name}.html", layout=args.layout, detail="high",
                      theme=args.theme, no_phases=bool(getattr(args, "no_phases", False)))
    print(f"Done. Open {out_dir / f'{name}.html'} in a browser.")


def main(argv: list[str] | None = None) -> None:
    _raw = argv if argv is not None else sys.argv[1:]
    if _raw and _raw[0] == "diff":
        _handle_diff(_raw[1:])
        return

    parser = argparse.ArgumentParser(
        prog="agentflow",
        description="Parse AI agent control flows and generate Excalidraw diagrams.",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"agentflow {__version__}",
    )
    parser.add_argument(
        "-i", "--input",
        required=True,
        help="Python source file or directory to parse (e.g., agent.py or ./my_repo)",
    )
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="Output .excalidraw file path (default: stdout as JSON)",
    )
    parser.add_argument(
        "-l", "--layout",
        choices=["hierarchical", "grid", "phased", "phased-horizontal", "radial", "swimlane"],
        default="hierarchical",
        help="Layout algorithm (default: hierarchical)",
    )
    parser.add_argument(
        "-f", "--format",
        choices=["excalidraw", "svg", "mermaid", "mermaid-html", "html", "ascii", "dot", "sequence", "mermaid-seq", "sequence-html"],
        default="excalidraw",
        help="Output format (default: excalidraw)",
    )
    parser.add_argument(
        "--profile",
        default="generic",
        help="Domain profile: 'generic', 'reaweb', 'reagame', 'traceforge', or path to a .py file "
             "defining a PROFILE dict (default: generic)",
    )
    parser.add_argument(
        "-t", "--title",
        default=None,
        help="Diagram title (default: derived from filename)",
    )
    parser.add_argument(
        "--theme",
        choices=["light", "dark", "pastel", "neon", "mono", "dungeon", "violet", "sandy", "ocean"],
        default="light",
        help="Color theme (default: light)",
    )
    parser.add_argument(
        "--palette",
        choices=["light", "dark", "pastel", "neon", "mono", "dungeon", "violet", "sandy", "ocean"],
        default=None,
        help="Alias for --theme (overrides --theme if given)",
    )
    parser.add_argument(
        "--no-legend",
        action="store_true",
        help="Omit the node-type legend from the diagram",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=None,
        help="RNG seed for deterministic output (same input + seed = identical file)",
    )
    parser.add_argument(
        "--detail",
        choices=["low", "med", "high"],
        default="high",
        help="Detail level for node text (default: high)",
    )
    parser.add_argument(
        "--include-imports",
        action="store_true",
        help="In repo mode, add dashed import edges between modules",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print graph summary instead of generating diagram",
    )
    parser.add_argument(
        "--drilldown",
        action="store_true",
        help="Generate the full drill-down hierarchy (L0→L1→L2→L3) as .mmd + .html files",
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help="Output directory for --drilldown mode (default: ./drilldown_output)",
    )
    parser.add_argument(
        "--no-phases",
        action="store_true",
        help="Mermaid only: flatten phased/phased-horizontal into a single "
             "left→right flowchart without FASE subgraph boxes",
    )

    args = parser.parse_args(argv)
    if getattr(args, "palette", None):
        args.theme = args.palette

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    # Parse the source (file vs directory → repo overview)
    if input_path.is_dir():
        from agentflow.repo import build_repo_overview

        title = args.title or f"Repo: {input_path.resolve().name}"
        try:
            graph = build_repo_overview(
                input_path,
                profile=args.profile,
                include_imports=args.include_imports,
                title=title,
            )
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
    else:
        from agentflow.parser import parse_file

        title = args.title or f"Flow: {input_path.stem}"
        try:
            graph = parse_file(str(input_path), profile=args.profile)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            sys.exit(1)
        graph.title = title

    if args.summary:
        print(graph.summary())
        return

    if args.drilldown:
        _handle_drilldown(args, input_path)
        return

    # Generate output (detail level applied inside renderers)
    if args.format == "svg":
        from agentflow.svg import save_svg, to_svg

        if args.output:
            path = save_svg(graph, args.output, layout=args.layout, theme=args.theme,
                            legend=not args.no_legend, detail=args.detail)
            print(f"OK: {path} ({graph.node_count} nodes, {graph.edge_count} edges)")
        else:
            svg_text = to_svg(graph, layout=args.layout, theme=args.theme,
                              legend=not args.no_legend, detail=args.detail)
            sys.stdout.write(svg_text)
        return

    if args.format == "mermaid":
        from agentflow.mermaid import save_mermaid, to_mermaid

        if args.output:
            path = save_mermaid(graph, args.output, layout=args.layout, detail=args.detail,
                                theme=args.theme, no_phases=args.no_phases)
            print(f"OK: {path} ({graph.node_count} nodes, {graph.edge_count} edges)")
        else:
            sys.stdout.write(to_mermaid(graph, layout=args.layout, detail=args.detail,
                                        theme=args.theme, no_phases=args.no_phases))
        return
    if args.format == "mermaid-html":
        from agentflow.mermaid import save_mermaid_html, to_mermaid_html

        if args.output:
            path = save_mermaid_html(graph, args.output, layout=args.layout, detail=args.detail,
                                     theme=args.theme, no_phases=args.no_phases)
            print(f"OK: {path} ({graph.node_count} nodes, {graph.edge_count} edges)")
        else:
            sys.stdout.write(to_mermaid_html(graph, layout=args.layout, detail=args.detail,
                                             theme=args.theme, no_phases=args.no_phases))
        return
    if args.format == "html":
        from agentflow.html import save_html, to_html

        if args.output:
            path = save_html(graph, args.output, layout=args.layout, theme=args.theme, legend=not args.no_legend, detail=args.detail)
            print(f"OK: {path} ({graph.node_count} nodes, {graph.edge_count} edges)")
        else:
            sys.stdout.write(to_html(graph, layout=args.layout, theme=args.theme, legend=not args.no_legend, detail=args.detail))
        return

    if args.format == "ascii":
        from agentflow.ascii import save_ascii, to_ascii

        if args.output:
            path = save_ascii(graph, args.output, detail=args.detail)
            print(f"OK: {path} ({graph.node_count} nodes, {graph.edge_count} edges)")
        else:
            sys.stdout.write(to_ascii(graph, detail=args.detail))
        return

    if args.format == "dot":
        from agentflow.dot import save_dot, to_dot

        if args.output:
            path = save_dot(graph, args.output, detail=args.detail, theme=args.theme)
            print(f"OK: {path} ({graph.node_count} nodes, {graph.edge_count} edges)")
        else:
            sys.stdout.write(to_dot(graph, detail=args.detail, theme=args.theme))
        return

    if args.format in ("sequence", "mermaid-seq", "sequence-html"):
        from agentflow.sequence import (
            extract_from_file,
            to_mermaid_sequence,
            to_sequence_html,
            to_sequence_svg,
        )

        interactions = extract_from_file(input_path, profile=args.profile)
        title = args.title or f"Sequence: {input_path.stem}"
        if args.format == "sequence":
            svg_text = to_sequence_svg(interactions, title=title)
            if args.output:
                out = Path(args.output)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(svg_text, encoding="utf-8")
                print(f"OK: {out} ({len(interactions.messages)} messages, {len(interactions.all_participants)} actors)")
            else:
                sys.stdout.write(svg_text)
        elif args.format == "sequence-html":
            html_text = to_sequence_html(interactions, title=title)
            if args.output:
                out = Path(args.output)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(html_text, encoding="utf-8")
                print(f"OK: {out} ({len(interactions.messages)} messages, {len(interactions.all_participants)} actors)")
            else:
                sys.stdout.write(html_text)
        else:
            mmd = to_mermaid_sequence(interactions, title=title)
            if args.output:
                out = Path(args.output)
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(mmd, encoding="utf-8")
                print(f"OK: {out} ({len(interactions.messages)} messages)")
            else:
                sys.stdout.write(mmd)
        return

    from agentflow.excalidraw import save_excalidraw, to_excalidraw

    if args.output:
        path = save_excalidraw(
            graph, args.output,
            layout=args.layout, theme=args.theme, legend=not args.no_legend,
            seed=args.seed, detail=args.detail,
        )
        print(f"OK: {path} ({graph.node_count} nodes, {graph.edge_count} edges)")
    else:
        doc = to_excalidraw(
            graph, layout=args.layout, theme=args.theme, legend=not args.no_legend,
            seed=args.seed, detail=args.detail,
        )
        json.dump(doc, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()
