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
    parser.add_argument("-l", "--layout", choices=["hierarchical", "grid", "phased", "swimlane"], default="hierarchical")
    parser.add_argument("-f", "--format", choices=["excalidraw", "svg", "mermaid", "html"], default="excalidraw")
    parser.add_argument("--profile", default="generic")
    parser.add_argument("-t", "--title", default=None)
    parser.add_argument("--theme", choices=["light", "dark", "pastel", "neon", "mono"], default="light")
    parser.add_argument("--palette", choices=["light", "dark", "pastel", "neon", "mono"], default=None, help="Alias for --theme")
    parser.add_argument("--no-legend", action="store_true")
    parser.add_argument("--seed", type=int, default=None)
    parser.add_argument("--detail", choices=["low", "med", "high"], default="high")
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
            path = save_mermaid(graph, args.output, layout=args.layout, detail=args.detail)
            print(f"OK: {path} ({graph.node_count} nodes, {graph.edge_count} edges)")
        else:
            sys.stdout.write(to_mermaid(graph, layout=args.layout, detail=args.detail))
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
        choices=["hierarchical", "grid", "phased", "swimlane"],
        default="hierarchical",
        help="Layout algorithm (default: hierarchical)",
    )
    parser.add_argument(
        "-f", "--format",
        choices=["excalidraw", "svg", "mermaid", "html", "ascii", "dot", "sequence", "mermaid-seq"],
        default="excalidraw",
        help="Output format (default: excalidraw)",
    )
    parser.add_argument(
        "--profile",
        default="generic",
        help="Domain profile: 'generic', 'reaweb', or path to a .py file "
             "defining a PROFILE dict (default: generic)",
    )
    parser.add_argument(
        "-t", "--title",
        default=None,
        help="Diagram title (default: derived from filename)",
    )
    parser.add_argument(
        "--theme",
        choices=["light", "dark", "pastel", "neon", "mono"],
        default="light",
        help="Color theme (default: light)",
    )
    parser.add_argument(
        "--palette",
        choices=["light", "dark", "pastel", "neon", "mono"],
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
            path = save_mermaid(graph, args.output, layout=args.layout, detail=args.detail)
            print(f"OK: {path} ({graph.node_count} nodes, {graph.edge_count} edges)")
        else:
            sys.stdout.write(to_mermaid(graph, layout=args.layout, detail=args.detail))
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

    if args.format in ("sequence", "mermaid-seq"):
        from agentflow.sequence import (
            extract_from_file,
            to_mermaid_sequence,
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
