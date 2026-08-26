"""Data models for agent flow graphs."""

from __future__ import annotations

import enum
from dataclasses import dataclass, field


class NodeType(enum.Enum):
    START = "start"
    END = "end"
    PROCESS = "process"
    DECISION = "decision"
    SUBPROCESS = "subprocess"
    TOOL = "tool"
    LOOP = "loop"
    EVOLUTION = "evolution"  # Self-evolution: lessons, meta-edits, compaction


@dataclass
class Node:
    id: str
    label: str
    node_type: NodeType = NodeType.PROCESS
    detail: str = ""
    line: int = 0
    phase: int = 0  # Phase hint (1/2/3); 0 = let the layout decide structurally

    def __hash__(self) -> int:
        return hash(self.id)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Node):
            return NotImplemented
        return self.id == other.id


@dataclass
class Edge:
    source: str
    target: str
    label: str = ""
    style: str = "solid"

    def __hash__(self) -> int:
        return hash((self.source, self.target, self.label))


@dataclass
class FlowGraph:
    title: str = "Agent Flow"
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    _node_ids: set[str] = field(default_factory=set, repr=False)

    def add_node(self, node: Node) -> None:
        if node.id not in self._node_ids:
            self.nodes.append(node)
            self._node_ids.add(node.id)

    def add_edge(self, edge: Edge) -> None:
        self.edges.append(edge)

    def get_node(self, node_id: str) -> Node | None:
        for n in self.nodes:
            if n.id == node_id:
                return n
        return None

    @property
    def node_count(self) -> int:
        return len(self.nodes)

    @property
    def edge_count(self) -> int:
        return len(self.edges)

    def summary(self) -> str:
        lines = [f"FlowGraph: {self.title} ({self.node_count} nodes, {self.edge_count} edges)"]
        for n in self.nodes:
            incoming = sum(1 for e in self.edges if e.target == n.id)
            outgoing = sum(1 for e in self.edges if e.source == n.id)
            lines.append(f"  [{n.node_type.value}] {n.id}: {n.label} (in={incoming}, out={outgoing})")
        return "\n".join(lines)
