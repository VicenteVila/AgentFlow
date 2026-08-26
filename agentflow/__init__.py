"""AgentFlow - Parse and visualize AI agent control flows as Excalidraw/SVG diagrams."""

from agentflow.diff import diff_files, diff_graphs
from agentflow.excalidraw import save_excalidraw, to_excalidraw
from agentflow.html import save_html, to_html
from agentflow.mermaid import save_mermaid, to_mermaid
from agentflow.models import Edge, FlowGraph, Node, NodeType
from agentflow.parser import parse_file, parse_source
from agentflow.profiles import Profile, get_profile, load_profile
from agentflow.repo import build_repo_overview, collect_python_files
from agentflow.svg import save_svg, to_svg

__version__ = "1.5.0"
__all__ = [
    "Edge",
    "FlowGraph",
    "Node",
    "NodeType",
    "Profile",
    "build_repo_overview",
    "collect_python_files",
    "diff_files",
    "diff_graphs",
    "get_profile",
    "load_profile",
    "parse_file",
    "parse_source",
    "save_excalidraw",
    "save_html",
    "save_mermaid",
    "save_svg",
    "to_excalidraw",
    "to_html",
    "to_mermaid",
    "to_svg",
]
