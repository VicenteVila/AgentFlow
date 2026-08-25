"""Command-line interface for AgentFlow.

Usage:
    agentflow --input agent.py --output flowchart.excalidraw
    agentflow --input agent.py --output flowchart.excalidraw --layout grid
    agentflow --input agent.py  # prints to stdout as JSON
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="agentflow",
        description="Parse AI agent control flows and generate Excalidraw diagrams.",
    )
    parser.add_argument(
        "-i", "--input",
        required=True,
        help="Python source file to parse (e.g., agent.py)",
    )
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="Output .excalidraw file path (default: stdout as JSON)",
    )
    parser.add_argument(
        "-l", "--layout",
        choices=["hierarchical", "grid", "phased"],
        default="hierarchical",
        help="Layout algorithm (default: hierarchical)",
    )
    parser.add_argument(
        "-t", "--title",
        default=None,
        help="Diagram title (default: derived from filename)",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print graph summary instead of generating diagram",
    )

    args = parser.parse_args(argv)

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: file not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    # Parse the source
    from agentflow.parser import parse_file

    title = args.title or f"Flow: {input_path.stem}"
    graph = parse_file(str(input_path))
    graph.title = title

    if args.summary:
        print(graph.summary())
        return

    # Generate Excalidraw
    from agentflow.excalidraw import to_excalidraw, save_excalidraw

    if args.output:
        path = save_excalidraw(graph, args.output, layout=args.layout)
        print(f"OK: {path} ({graph.node_count} nodes, {graph.edge_count} edges)")
    else:
        doc = to_excalidraw(graph, layout=args.layout)
        json.dump(doc, sys.stdout, indent=2, ensure_ascii=False)
        sys.stdout.write("\n")


if __name__ == "__main__":
    main()
