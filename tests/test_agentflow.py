"""Tests for AgentFlow parser and Excalidraw generation."""

import json
import tempfile
from pathlib import Path

import pytest

from agentflow.excalidraw import save_excalidraw, to_excalidraw
from agentflow.layouts import (
    PositionedNode,
    grid_layout,
    hierarchical_layout,
    phased_layout,
)
from agentflow.models import Edge, FlowGraph, Node, NodeType
from agentflow.parser import parse_source
from agentflow.profiles import (
    REAWEB_PROFILE,
    get_profile,
    load_profile,
)


def parse(text, title="Test"):
    """Parse with the reaweb profile (exhaustive labels)."""
    return parse_source(text, title=title, profile="reaweb")


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
    graph = parse(SIMPLE_AGENT, title="Test Agent")
    assert graph.node_count >= 3
    assert graph.edge_count >= 1
    # Should have start and end
    assert any(n.node_type == NodeType.START for n in graph.nodes)
    assert any(n.node_type == NodeType.END for n in graph.nodes)


def test_parse_has_loop():
    graph = parse(SIMPLE_AGENT, title="Test Agent")
    loops = [n for n in graph.nodes if n.node_type == NodeType.LOOP]
    assert len(loops) >= 1


def test_parse_has_decisions():
    graph = parse(SIMPLE_AGENT, title="Test Agent")
    decisions = [n for n in graph.nodes if n.node_type == NodeType.DECISION]
    assert len(decisions) >= 1


def test_parse_has_tool_calls():
    graph = parse(SIMPLE_AGENT, title="Test Agent")
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


# ── Profile tests ─────────────────────────────────────────────────────


def test_generic_profile_has_no_domain_knowledge():
    """The generic profile must not recognize ReaWeb tools."""
    graph = parse_source(SIMPLE_AGENT, title="Generic")
    tools = [n for n in graph.nodes if n.node_type == NodeType.TOOL]
    assert len(tools) == 0
    # But the control flow is still extracted
    assert any(n.node_type == NodeType.LOOP for n in graph.nodes)
    assert any(n.node_type == NodeType.DECISION for n in graph.nodes)


def test_reaweb_profile_recognizes_tools():
    graph = parse(SIMPLE_AGENT)
    tools = [n for n in graph.nodes if n.node_type == NodeType.TOOL]
    assert len(tools) >= 1


def test_get_profile_builtins():
    import pytest

    assert get_profile(None).name == "generic"
    assert get_profile("reaweb").name == "reaweb"
    assert get_profile(REAWEB_PROFILE) is REAWEB_PROFILE
    with pytest.raises(ValueError):
        get_profile("nope")


def test_load_profile_from_file(tmp_path=None):
    import tempfile as _tf

    with _tf.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir) / "my_profile.py"
        p.write_text(
            "PROFILE = {\n"
            "  'name': 'custom',\n"
            "  'tool_names': {'deploy': 'Deploy App'},\n"
            "  'phase_patterns': {'deploy': 2},\n"
            "}\n"
        )
        prof = load_profile(p)
        assert prof.name == "custom"
        assert prof.tool_names["deploy"] == ("Deploy App", "")

        src = '''
class Agent:
    def run(self):
        if action == "deploy":
            self.deploy()
'''
        graph = parse_source(src, title="Custom", profile=prof)
        tools = [n for n in graph.nodes if n.node_type == NodeType.TOOL]
        assert len(tools) == 1
        assert tools[0].label == "Deploy App"


def test_structural_phases_without_patterns():
    """Phased layout works for graphs with no phase hints at all."""
    graph = parse_source(SIMPLE_AGENT, title="Structural")  # generic profile
    result = phased_layout(graph)
    assert all(p.phase in (1, 2, 3) for p in result.positioned)
    # The while-loop cycle forces a phase 2; ancestors/descendants give 1 and 3
    phases = {p.phase for p in result.positioned}
    assert 2 in phases


# ── Determinism tests ─────────────────────────────────────────────────


def test_deterministic_output_with_seed():
    """Same input + same seed must produce byte-identical JSON."""
    graph = parse(SIMPLE_AGENT, title="Determinism")
    doc1 = to_excalidraw(graph, layout="phased", seed=42)
    doc2 = to_excalidraw(graph, layout="phased", seed=42)
    assert json.dumps(doc1, sort_keys=True) == json.dumps(doc2, sort_keys=True)


def test_different_seeds_differ():
    graph = parse(SIMPLE_AGENT, title="Seeds")
    doc1 = to_excalidraw(graph, seed=1)
    doc2 = to_excalidraw(graph, seed=2)
    ids1 = {e["id"] for e in doc1["elements"]}
    ids2 = {e["id"] for e in doc2["elements"]}
    assert ids1 != ids2


# ── SVG export tests ──────────────────────────────────────────────────


def test_to_svg_valid_xml():
    import xml.dom.minidom

    from agentflow.svg import to_svg

    graph = parse(SIMPLE_AGENT, title="SVG Test")
    svg = to_svg(graph, layout="phased")
    doc = xml.dom.minidom.parseString(svg)  # raises if malformed
    assert doc.documentElement.tagName == "svg"
    assert len(doc.getElementsByTagName("path")) >= 1   # arrows
    assert len(doc.getElementsByTagName("ellipse")) >= 1  # start/end
    assert len(doc.getElementsByTagName("polygon")) >= 1  # decisions
    assert "Budget" in svg or "Main Loop" in svg


def test_save_svg():
    from agentflow.svg import save_svg

    g = FlowGraph(title="Save SVG")
    g.add_node(Node(id="a", label="A"))
    g.add_edge(Edge(source="a", target="b"))
    g.add_node(Node(id="b", label="B"))

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "out.svg"
        result = save_svg(g, path)
        assert result.exists()
        assert "<svg" in result.read_text()


# ── Golden fixture tests ──────────────────────────────────────────────


GOLDEN_DIR = Path(__file__).parent / "golden"


def _build_fixture_graph() -> FlowGraph:
    """Deterministic input graph for golden fixtures (reaweb profile)."""
    return parse(SIMPLE_AGENT, title="Golden Fixture")


def _golden_bytes(layout: str, fmt: str) -> bytes:
    graph = _build_fixture_graph()
    if fmt == "excalidraw":
        doc = to_excalidraw(graph, layout=layout, seed=42)
        return json.dumps(doc, indent=2, ensure_ascii=False,
                          sort_keys=True).encode("utf-8")
    from agentflow.svg import to_svg

    return to_svg(graph, layout=layout).encode("utf-8")


@pytest.mark.parametrize("layout,fmt", [
    ("phased", "excalidraw"),
    ("hierarchical", "excalidraw"),
    ("phased", "svg"),
    ("hierarchical", "svg"),
])
def test_golden_fixtures(layout: str, fmt: str, request):
    """Output must match versioned fixtures byte-for-byte.

    Regenerate intentionally with:  pytest --update-golden
    """
    ext = "excalidraw" if fmt == "excalidraw" else "svg"
    fixture = GOLDEN_DIR / f"{layout}.{ext}"
    current = _golden_bytes(layout, fmt)

    if request.config.getoption("--update-golden"):
        GOLDEN_DIR.mkdir(exist_ok=True)
        fixture.write_bytes(current)
        pytest.skip(f"updated {fixture.name}")
        return

    assert fixture.exists(), (
        f"{fixture} missing — run 'pytest --update-golden' to create it"
    )
    assert current == fixture.read_bytes(), (
        f"output drift in {fixture.name}: regenerate with --update-golden "
        "only if the change is intentional"
    )


# ── Layout tests ──────────────────────────────────────────────────────


def test_hierarchical_layout():
    graph = parse(SIMPLE_AGENT, title="Test")
    result = hierarchical_layout(graph)
    assert len(result.positioned) == graph.node_count
    assert result.width > 0
    assert result.height > 0


def test_grid_layout():
    graph = parse(SIMPLE_AGENT, title="Test")
    result = grid_layout(graph)
    assert len(result.positioned) == graph.node_count


def test_phased_layout():
    graph = parse(SIMPLE_AGENT, title="Test")
    result = phased_layout(graph)
    assert len(result.positioned) == graph.node_count
    assert len(result.phase_boxes) == 3  # FASE 1, 2, 3
    # All nodes should have phase assigned
    for p in result.positioned:
        assert p.phase in (1, 2, 3)


def test_phased_layout_excalidraw():
    graph = parse(SIMPLE_AGENT, title="Phased Test")
    doc = to_excalidraw(graph, layout="phased")
    assert doc["type"] == "excalidraw"
    # Should have phase boxes (rectangles with dashed stroke)
    phase_boxes = [e for e in doc["elements"]
                   if e["type"] == "rectangle" and e.get("strokeStyle") == "dashed"
                   and e.get("strokeColor") == "#868e96"]
    assert len(phase_boxes) >= 1  # At least one phase box


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
    graph = parse(SIMPLE_AGENT, title="Full Pipeline Test")
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
    graph = parse(SIMPLE_AGENT, title="Save Pipeline")

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "agent_flow.excalidraw"
        save_excalidraw(graph, path)
        assert path.exists()

        data = json.loads(path.read_text())
        assert data["type"] == "excalidraw"
        assert len(data["elements"]) > 0


# ── Visual invariant tests ───────────────────────────────────────────


def _shape_ids(doc):
    return {e["id"] for e in doc["elements"] if e["type"] in ("rectangle", "diamond", "ellipse")}


def test_no_duplicate_feedback_arrows():
    """Edges rendered as feedback arrows must not be drawn twice."""
    graph = parse_source(SIMPLE_AGENT, title="Dedup Test")
    doc = to_excalidraw(graph, layout="phased")

    # Each (startBinding, endBinding) pair should appear at most once
    seen = set()
    for el in doc["elements"]:
        if el["type"] != "arrow":
            continue
        sb = (el.get("startBinding") or {}).get("elementId")
        eb = (el.get("endBinding") or {}).get("elementId")
        key = (sb, eb)
        assert key not in seen, f"duplicate arrow {key}"
        seen.add(key)


def test_text_fits_in_nodes():
    """Node dimensions must accommodate their measured label + detail."""
    from agentflow.layouts import DETAIL_FONT, LABEL_FONT, measure_text

    g = FlowGraph()
    long_label = "Generate Candidate For Long Running Subtask"
    long_detail = "LLM sub-agent genera HTML/CSS/JS\nexploration=True, target_h=0..N"
    g.add_node(Node(id="a", label=long_label, detail=long_detail,
                    node_type=NodeType.PROCESS))
    result = hierarchical_layout(g)
    p = result.positioned[0]
    lw, lh = measure_text(p.node.label, LABEL_FONT)
    _dw, dh = measure_text(p.node.detail, DETAIL_FONT)
    assert p.width >= lw
    assert p.height >= lh + dh


def test_diamond_sized_for_text():
    """Decision diamond bbox must inscribe its label (half-extents ≥ text)."""
    from agentflow.layouts import LABEL_FONT, measure_text

    g = FlowGraph()
    label = "Múltiples condiciones\nAND/OR combinadas?"
    g.add_node(Node(id="d", label=label, node_type=NodeType.DECISION))
    result = hierarchical_layout(g)
    p = result.positioned[0]
    lw, lh = measure_text(label, LABEL_FONT)
    assert p.width / 2 >= lw
    assert p.height / 2 >= lh


def test_diamond_capped_for_extreme_labels():
    """Verbose decisions must never exceed the diamond size cap."""
    from agentflow.layouts import DIAMOND_MAX_H, DIAMOND_MAX_W

    g = FlowGraph()
    huge = "Una condición larguísima con muchas palabras\nsegunda línea igual de larga\ny hasta una tercera"
    g.add_node(Node(id="d", label=huge, node_type=NodeType.DECISION))
    result = hierarchical_layout(g)
    p = result.positioned[0]
    assert p.width <= DIAMOND_MAX_W
    assert p.height <= DIAMOND_MAX_H


def test_feedback_slots_stagger_same_side():
    """Feedback arrows sharing a side must receive distinct slots."""
    from agentflow.geometry import assign_feedback_slots
    from agentflow.layouts import FeedbackArrow

    g = FlowGraph()
    g.add_node(Node(id="top", label="Top"))
    g.add_node(Node(id="mid1", label="Mid1"))
    g.add_node(Node(id="mid2", label="Mid2"))
    pos = {
        "top": PositionedNode(node=g.get_node("top"), x=400, y=80, width=200, height=80),
        "mid1": PositionedNode(node=g.get_node("mid1"), x=400, y=300, width=200, height=80),
        "mid2": PositionedNode(node=g.get_node("mid2"), x=400, y=500, width=200, height=80),
    }
    fb = [
        FeedbackArrow(source_id="mid1", target_id="top"),
        FeedbackArrow(source_id="mid2", target_id="top"),
    ]
    slots = assign_feedback_slots(fb, pos, canvas_width=1000)
    # Both route right of center → consecutive slots, no overlap
    assert slots[0] == 0
    assert slots[1] == 1


def test_phased_columns_do_not_overlap():
    """Main flow column must not intersect side (tools) or evolution columns."""
    graph = parse(SIMPLE_AGENT, title="Columns")
    result = phased_layout(graph)

    main = [p for p in result.positioned
            if p.node.node_type not in (NodeType.TOOL, NodeType.SUBPROCESS, NodeType.EVOLUTION)]
    side = [p for p in result.positioned
            if p.node.node_type in (NodeType.TOOL, NodeType.SUBPROCESS)]
    evo = [p for p in result.positioned if p.node.node_type == NodeType.EVOLUTION]

    def x_ranges(nodes):
        return [(p.x, p.x + p.width) for p in nodes]

    for m_range in x_ranges(main):
        for s_range in x_ranges(side) + x_ranges(evo):
            assert m_range[1] <= s_range[0] or s_range[1] <= m_range[0], \
                f"column overlap: main {m_range} vs other {s_range}"


def test_theme_dark_changes_colors():
    doc_dark = to_excalidraw(FlowGraph(title="T"), theme="dark", legend=False)
    doc_light = to_excalidraw(FlowGraph(title="T"), theme="light", legend=False)
    assert doc_dark["appState"]["viewBackgroundColor"] != \
        doc_light["appState"]["viewBackgroundColor"]


def test_legend_optional():
    g = FlowGraph(title="No Legend")
    g.add_node(Node(id="a", label="A"))
    doc = to_excalidraw(g, legend=False)
    texts = [e.get("text", "") for e in doc["elements"] if e["type"] == "text"]
    assert "LEGEND" not in texts

    doc2 = to_excalidraw(g, legend=True)
    texts2 = [e.get("text", "") for e in doc2["elements"] if e["type"] == "text"]
    assert "LEGEND" in texts2


# ── Repo overview tests ───────────────────────────────────────────────


def test_repo_overview_builds_graph():
    from agentflow.repo import build_repo_overview

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "agent_a.py").write_text(
            "class AgentA:\n    def run(self):\n        if x:\n            do_a()\n"
        )
        (root / "agent_b.py").write_text(
            "class AgentB:\n    def run(self):\n        for i in items:\n            do_b()\n"
        )
        (root / "empty.py").write_text("# nothing\n")
        graph = build_repo_overview(root)
        # Should have start, 2 module nodes, end
        assert graph.node_count == 4
        assert graph.edge_count >= 3
        assert any("agent_a" in n.id for n in graph.nodes)
        assert any("agent_b" in n.id for n in graph.nodes)


def test_repo_overview_empty_dir():
    from agentflow.repo import build_repo_overview

    with tempfile.TemporaryDirectory() as tmpdir:
        graph = build_repo_overview(Path(tmpdir))
        assert graph.node_count == 2  # start + end with "no agents" edge


def test_repo_overview_rejects_file():
    from agentflow.repo import build_repo_overview

    with tempfile.TemporaryDirectory() as tmpdir:
        f = Path(tmpdir) / "single.py"
        f.write_text("x = 1\n")
        with pytest.raises(ValueError):
            build_repo_overview(f)


def test_repo_overview_cli(tmp_path=None):
    import subprocess
    import sys

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        (root / "mod.py").write_text(
            "class MyAgent:\n    def run(self):\n        if ok:\n            act()\n"
        )
        out = Path(tmpdir) / "out.excalidraw"
        result = subprocess.run(
            [sys.executable, "-m", "agentflow.cli", "-i", str(root), "-o", str(out)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert out.exists()
        data = json.loads(out.read_text())
        assert data["type"] == "excalidraw"
