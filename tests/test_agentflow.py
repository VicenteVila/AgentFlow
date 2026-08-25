"""Tests for AgentFlow parser and Excalidraw generation."""

import json
import tempfile
from pathlib import Path

from agentflow.models import Edge, FlowGraph, Node, NodeType
from agentflow.parser import parse_source
from agentflow.excalidraw import to_excalidraw, save_excalidraw
from agentflow.layouts import hierarchical_layout, grid_layout


# ── Models tests ──────────────────────────────────────────────────────


def test_node_creation():
    n = Node(id="a", label="Test", node_type=NodeType.PROCESS)
    assert n.id == "a"
    assert n.label == "Test"
    assert n.node_type == NodeType.PROCESS


def test_node_hash():
    n1 = Node(id="a", label="A")
    n2 = Node(id="a", label="B")
    assert n1 == n2
    assert hash(n1) == hash(n2)


def test_flowgraph_add_node():
    g = FlowGraph()
    g.add_node(Node(id="a", label="A"))
    g.add_node(Node(id="a", label="A2"))  # duplicate
    assert g.node_count == 1


def test_flowgraph_add_edge():
    g = FlowGraph()
    g.add_node(Node(id="a", label="A"))
    g.add_node(Node(id="b", label="B"))
    g.add_edge(Edge(source="a", target="b", label="go"))
    assert g.edge_count == 1


def test_flowgraph_get_node():
    g = FlowGraph()
    g.add_node(Node(id="x", label="X"))
    assert g.get_node("x") is not None
    assert g.get_node("y") is None


# ── Parser tests ──────────────────────────────────────────────────────


SIMPLE_AGENT = '''
class Agent:
    def run(self, registry):
        self._init()
        while True:
            if self.budget.done():
                break
            result = self.llm.generate(prompt)
            if not result.tool_calls:
                if "done" in result.text:
                    break
            for call in result.tool_calls:
                if call.name == "generate_candidate":
                    self._snapshot()
                    self._auto_truth_audit()
                self._exec_tool(call)
            self._sync_budget()
        self._export_final()
'''


def test_parse_simple_agent():
    graph = parse_source(SIMPLE_AGENT, title="Test Agent")
    assert graph.node_count >= 3
    assert graph.edge_count >= 1
    # Should have start and end
    assert any(n.node_type == NodeType.START for n in graph.nodes)
    assert any(n.node_type == NodeType.END for n in graph.nodes)


def test_parse_has_loop():
    graph = parse_source(SIMPLE_AGENT, title="Test Agent")
    loops = [n for n in graph.nodes if n.node_type == NodeType.LOOP]
    assert len(loops) >= 1


def test_parse_has_decisions():
    graph = parse_source(SIMPLE_AGENT, title="Test Agent")
    decisions = [n for n in graph.nodes if n.node_type == NodeType.DECISION]
    assert len(decisions) >= 1


def test_parse_has_tool_calls():
    graph = parse_source(SIMPLE_AGENT, title="Test Agent")
    tools = [n for n in graph.nodes if n.node_type == NodeType.TOOL]
    assert len(tools) >= 1


MINIMAL_CODE = '''
def main():
    start()
    if condition:
        do_a()
    else:
        do_b()
    end()
'''


def test_parse_minimal():
    graph = parse_source(MINIMAL_CODE, title="Minimal")
    assert graph.node_count >= 3


# ── Layout tests ──────────────────────────────────────────────────────


def test_hierarchical_layout():
    graph = parse_source(SIMPLE_AGENT, title="Test")
    result = hierarchical_layout(graph)
    assert len(result.positioned) == graph.node_count
    assert result.width > 0
    assert result.height > 0


def test_grid_layout():
    graph = parse_source(SIMPLE_AGENT, title="Test")
    result = grid_layout(graph)
    assert len(result.positioned) == graph.node_count


def test_layout_no_overlap_simple():
    """Nodes should not overlap in a simple linear graph."""
    g = FlowGraph(title="Linear")
    g.add_node(Node(id="a", label="A"))
    g.add_node(Node(id="b", label="B"))
    g.add_node(Node(id="c", label="C"))
    g.add_edge(Edge(source="a", target="b"))
    g.add_edge(Edge(source="b", target="c"))

    result = hierarchical_layout(g)
    # All nodes should have distinct positions
    positions = [(p.x, p.y) for p in result.positioned]
    assert len(positions) == len(set(positions))


# ── Excalidraw tests ─────────────────────────────────────────────────


def test_to_excalidraw_valid_structure():
    g = FlowGraph(title="Test")
    g.add_node(Node(id="a", label="A"))
    g.add_node(Node(id="b", label="B"))
    g.add_edge(Edge(source="a", target="b"))

    doc = to_excalidraw(g)
    assert doc["type"] == "excalidraw"
    assert doc["version"] == 2
    assert "elements" in doc
    assert "appState" in doc
    assert "files" in doc


def test_to_excalidraw_has_shapes():
    g = FlowGraph(title="Test")
    g.add_node(Node(id="start", label="Start", node_type=NodeType.START))
    g.add_node(Node(id="proc", label="Process", node_type=NodeType.PROCESS))
    g.add_node(Node(id="dec", label="Decision?", node_type=NodeType.DECISION))
    g.add_node(Node(id="end", label="End", node_type=NodeType.END))
    g.add_edge(Edge(source="start", target="proc"))
    g.add_edge(Edge(source="proc", target="dec"))
    g.add_edge(Edge(source="dec", target="end"))

    doc = to_excalidraw(g)
    elements = doc["elements"]

    # Should have shapes (start=ellipse, proc=rectangle, dec=diamond, end=ellipse)
    types = [e["type"] for e in elements]
    assert "ellipse" in types
    assert "rectangle" in types
    assert "diamond" in types
    assert "text" in types
    assert "arrow" in types


def test_to_excalidraw_has_arrows():
    g = FlowGraph(title="Test")
    g.add_node(Node(id="a", label="A"))
    g.add_node(Node(id="b", label="B"))
    g.add_edge(Edge(source="a", target="b", label="yes"))

    doc = to_excalidraw(g)
    arrows = [e for e in doc["elements"] if e["type"] == "arrow"]
    assert len(arrows) >= 1
    # Arrow should have bindings
    arrow = arrows[0]
    assert arrow.get("startBinding") is not None
    assert arrow.get("endBinding") is not None


def test_save_excalidraw():
    g = FlowGraph(title="Save Test")
    g.add_node(Node(id="a", label="A"))
    g.add_node(Node(id="b", label="B"))
    g.add_edge(Edge(source="a", target="b"))

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test.excalidraw"
        result = save_excalidraw(g, path)
        assert result.exists()
        data = json.loads(result.read_text())
        assert data["type"] == "excalidraw"
        assert len(data["elements"]) > 0


# ── Integration: parse → layout → excalidraw ─────────────────────────


def test_full_pipeline():
    """End-to-end: parse agent code → layout → Excalidraw JSON."""
    graph = parse_source(SIMPLE_AGENT, title="Full Pipeline Test")
    doc = to_excalidraw(graph)

    # Verify the pipeline produces valid output
    assert doc["type"] == "excalidraw"
    assert len(doc["elements"]) > 0

    # All elements should have required fields
    for el in doc["elements"]:
        assert "id" in el
        assert "type" in el
        assert "x" in el
        assert "y" in el


def test_full_pipeline_with_save():
    """End-to-end: parse → save .excalidraw file."""
    graph = parse_source(SIMPLE_AGENT, title="Save Pipeline")

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "agent_flow.excalidraw"
        save_excalidraw(graph, path)
        assert path.exists()

        data = json.loads(path.read_text())
        assert data["type"] == "excalidraw"
        assert len(data["elements"]) > 0
