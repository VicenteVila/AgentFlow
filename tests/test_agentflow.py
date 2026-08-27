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


# ── Mermaid + detail tests ────────────────────────────────────────────


def test_to_mermaid_valid_structure():
    from agentflow.mermaid import to_mermaid

    g = FlowGraph(title="Mermaid Test")
    g.add_node(Node(id="a", label="Start", node_type=NodeType.START))
    g.add_node(Node(id="b", label="Decide?", node_type=NodeType.DECISION))
    g.add_node(Node(id="c", label="End", node_type=NodeType.END))
    g.add_edge(Edge(source="a", target="b", label="go"))
    g.add_edge(Edge(source="b", target="c", label="yes"))

    text = to_mermaid(g)
    assert text.startswith("%%")
    assert "flowchart TD" in text
    assert "classDef evolution" in text
    # Decision uses {} shape
    assert "{" in text and "}" in text
    # Edge labels
    assert "go" in text


def test_to_mermaid_with_phased_layout():
    from agentflow.mermaid import to_mermaid

    graph = parse(SIMPLE_AGENT, title="Mermaid Phased")
    text = to_mermaid(graph, layout="phased")
    assert "flowchart TD" in text
    assert "subgraph" in text  # phases become subgraphs


def test_save_mermaid():
    from agentflow.mermaid import save_mermaid

    g = FlowGraph(title="Save Mermaid")
    g.add_node(Node(id="a", label="A"))
    g.add_node(Node(id="b", label="B"))
    g.add_edge(Edge(source="a", target="b"))

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "out.mmd"
        result = save_mermaid(g, path)
        assert result.exists()
        assert "flowchart TD" in result.read_text()


def test_detail_levels():
    from agentflow.layouts import with_detail_level
    from agentflow.mermaid import to_mermaid

    # Build a graph with rich details
    g = parse(SIMPLE_AGENT, title="Detail Test")
    # Ensure there's at least one node with detail
    assert any(n.detail for n in g.nodes)

    low = to_mermaid(g, detail="low")
    med = to_mermaid(g, detail="med")
    high = to_mermaid(g, detail="high")
    # Low should be shortest, high longest
    assert len(low) < len(med) < len(high)

    # with_detail_level directly
    g_low = with_detail_level(g, "low")
    assert all(not n.detail for n in g_low.nodes)
    g_med = with_detail_level(g, "med")
    for n in g_med.nodes:
        assert "\n" not in n.detail  # truncated to first line


def test_detail_affects_excalidraw_and_svg():
    g = parse(SIMPLE_AGENT, title="Detail SVG")
    low_doc = to_excalidraw(g, detail="low")
    high_doc = to_excalidraw(g, detail="high")
    # High has more text elements (details) than low
    low_texts = [e for e in low_doc["elements"] if e["type"] == "text"]
    high_texts = [e for e in high_doc["elements"] if e["type"] == "text"]
    assert len(high_texts) >= len(low_texts)

    from agentflow.svg import to_svg

    low_svg = to_svg(g, detail="low")
    high_svg = to_svg(g, detail="high")
    assert len(high_svg) > len(low_svg)


def test_mermaid_cli(tmp_path=None):
    import subprocess
    import sys

    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / "agent.py"
        src.write_text("class Agent:\n    def run(self):\n        if x:\n            do_a()\n")
        out = Path(tmpdir) / "out.mmd"
        result = subprocess.run(
            [sys.executable, "-m", "agentflow.cli", "-i", str(src), "-o", str(out), "-f", "mermaid", "--detail", "low"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert out.exists()
        assert "flowchart TD" in out.read_text()


# ── Diff tests ────────────────────────────────────────────────────────


def test_diff_graphs_added_removed():
    from agentflow.diff import diff_graphs

    old = FlowGraph(title="old")
    old.add_node(Node(id="a", label="A"))
    old.add_node(Node(id="b", label="B"))
    old.add_edge(Edge(source="a", target="b"))

    new = FlowGraph(title="new")
    new.add_node(Node(id="a", label="A"))
    new.add_node(Node(id="c", label="C"))
    new.add_edge(Edge(source="a", target="c"))

    merged = diff_graphs(old, new)
    by_id = {n.id: n for n in merged.nodes}
    assert by_id["a"].diff_status == "unchanged"
    assert by_id["b"].diff_status == "removed"
    assert by_id["c"].diff_status == "added"

    edge_status = {(e.source, e.target): e.diff_status for e in merged.edges}
    assert edge_status[("a", "b")] == "removed"
    assert edge_status[("a", "c")] == "added"


def test_diff_detects_changed_node():
    from agentflow.diff import diff_graphs

    old = FlowGraph(title="old")
    old.add_node(Node(id="a", label="Hello"))

    new = FlowGraph(title="new")
    new.add_node(Node(id="a", label="World"))

    merged = diff_graphs(old, new)
    assert merged.nodes[0].diff_status == "changed"


def test_diff_render_excalidraw_colors():
    from agentflow.diff import diff_graphs

    old = FlowGraph(title="old")
    old.add_node(Node(id="a", label="A"))
    old.add_node(Node(id="b", label="B"))
    old.add_edge(Edge(source="a", target="b"))

    new = FlowGraph(title="new")
    new.add_node(Node(id="a", label="A"))
    new.add_node(Node(id="c", label="C"))
    new.add_edge(Edge(source="a", target="c"))

    merged = diff_graphs(old, new)
    doc = to_excalidraw(merged, seed=42)

    # Added node should have diff green background
    added_shapes = [e for e in doc["elements"] if e.get("backgroundColor") == "#a7f3d0"]
    assert len(added_shapes) >= 1
    # Removed node should have diff red background (or at least one)
    removed_shapes = [e for e in doc["elements"] if e.get("backgroundColor") == "#fecaca"]
    assert len(removed_shapes) >= 1


def test_diff_render_mermaid_classes():
    from agentflow.diff import diff_graphs
    from agentflow.mermaid import to_mermaid

    old = FlowGraph(title="old")
    old.add_node(Node(id="a", label="A"))
    old.add_node(Node(id="b", label="B"))

    new = FlowGraph(title="new")
    new.add_node(Node(id="a", label="A"))
    new.add_node(Node(id="c", label="C"))

    merged = diff_graphs(old, new)
    text = to_mermaid(merged)
    assert ":::added" in text
    assert ":::removed" in text
    assert "classDef added" in text


def test_diff_cli(tmp_path=None):
    import subprocess
    import sys

    with tempfile.TemporaryDirectory() as tmpdir:
        old = Path(tmpdir) / "old.py"
        new = Path(tmpdir) / "new.py"
        old.write_text("class Agent:\n    def run(self):\n        if x:\n            do_a()\n")
        new.write_text("class Agent:\n    def run(self):\n        if x:\n            do_a()\n        if y:\n            do_b()\n")
        out = Path(tmpdir) / "diff.excalidraw"
        result = subprocess.run(
            [sys.executable, "-m", "agentflow.cli", "diff", str(old), str(new), "-o", str(out)],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert out.exists()
        data = json.loads(out.read_text())
        assert data["type"] == "excalidraw"
        # Also test mermaid diff
        out2 = Path(tmpdir) / "diff.mmd"
        result2 = subprocess.run(
            [sys.executable, "-m", "agentflow.cli", "diff", str(old), str(new), "-o", str(out2), "-f", "mermaid"],
            capture_output=True, text=True,
        )
        assert result2.returncode == 0
        assert ":::added" in out2.read_text()


# ── HTML interactive tests ────────────────────────────────────────────


def test_to_html_valid_structure():
    from agentflow.html import to_html

    g = FlowGraph(title="HTML Test")
    g.add_node(Node(id="a", label="Start", node_type=NodeType.START))
    g.add_node(Node(id="b", label="Decide?", node_type=NodeType.DECISION))
    g.add_edge(Edge(source="a", target="b"))

    html = to_html(g)
    assert "<!DOCTYPE html>" in html
    assert "<svg" in html
    assert 'data-node-id="a"' in html
    assert 'data-phase' in html
    assert 'id="search"' in html
    assert 'id="canvas"' in html
    assert "zoom-in" in html


def test_to_html_with_phased_layout():
    from agentflow.html import to_html

    graph = parse(SIMPLE_AGENT, title="HTML Phased")
    html = to_html(graph, layout="phased")
    assert "<!DOCTYPE html>" in html
    assert "FASE" in html or "phase" in html.lower()
    assert "search" in html.lower()


def test_to_html_with_links():
    from agentflow.html import to_html

    g = FlowGraph(title="Links Test")
    g.add_node(Node(id="comp_a", label="Component A"))
    g.add_node(Node(id="comp_b", label="Component B"))
    g.add_edge(Edge(source="comp_a", target="comp_b"))

    links = {"comp_a": "detail_a.html", "comp_b": "detail_b.html"}
    html = to_html(g, links=links)
    assert 'data-link="detail_a.html"' in html
    assert 'data-link="detail_b.html"' in html
    assert "el.style.cursor" in html  # drill-down JS injected


def test_to_html_without_links():
    from agentflow.html import to_html

    g = FlowGraph(title="No Links")
    g.add_node(Node(id="a", label="A"))
    html = to_html(g)
    assert "data-link" not in html
    assert "el.style.cursor" not in html


def test_to_mermaid_with_links():
    from agentflow.mermaid import to_mermaid

    g = FlowGraph(title="MMD Links")
    g.add_node(Node(id="comp_a", label="Comp A"))
    g.add_node(Node(id="comp_b", label="Comp B"))
    g.add_edge(Edge(source="comp_a", target="comp_b"))

    links = {"comp_a": "detail_a.mmd", "comp_b": "detail_b.mmd"}
    mmd = to_mermaid(g, links=links)
    assert 'click comp_a href "detail_a.mmd" "Abrir detalle"' in mmd
    assert 'click comp_b href "detail_b.mmd" "Abrir detalle"' in mmd
    assert "securityLevel" in mmd  # loose header injected


def test_to_mermaid_without_links():
    from agentflow.mermaid import to_mermaid

    g = FlowGraph(title="MMD No Links")
    g.add_node(Node(id="a", label="A"))
    mmd = to_mermaid(g)
    assert "click" not in mmd
    assert "securityLevel" not in mmd


def test_save_mermaid_links():
    from agentflow.mermaid import save_mermaid

    g = FlowGraph(title="Save MMD Links")
    g.add_node(Node(id="x", label="X"))
    links = {"x": "target.mmd"}
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "out.mmd"
        save_mermaid(g, path, links=links)
        content = path.read_text()
        assert 'click x href "target.mmd" "Abrir detalle"' in content


def test_mermaid_title_override():
    from agentflow.mermaid import to_mermaid

    g = FlowGraph(title="Old Title")
    g.add_node(Node(id="a", label="A"))
    mmd = to_mermaid(g, title="Custom Title")
    assert "Custom Title" in mmd
    assert "Old Title" not in mmd


def test_to_mermaid_html():
    from agentflow.mermaid import to_mermaid_html

    g = FlowGraph(title="HTML Wrapper")
    g.add_node(Node(id="a", label="A"))
    links = {"a": "next.html"}
    html = to_mermaid_html(g, links=links, title="Wrapper Test")
    assert "<!DOCTYPE html>" in html
    assert "mermaid.min.js" in html
    assert "securityLevel" in html
    assert "'loose'" in html
    assert 'click a href "next.html"' in html
    assert "Wrapper Test" in html


def test_save_mermaid_html():
    from agentflow.mermaid import save_mermaid_html

    g = FlowGraph(title="Save Wrapper")
    g.add_node(Node(id="x", label="X"))
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "out.html"
        save_mermaid_html(g, path, title="My Page")
        content = path.read_text()
        assert "<!DOCTYPE html>" in content
        assert "mermaid" in content.lower()


def test_mermaid_reserved_keywords_sanitized():
    from agentflow.mermaid import _sanitize_id, to_mermaid

    assert _sanitize_id("end") == "n_end"
    assert _sanitize_id("start") == "n_start"
    assert _sanitize_id("subgraph") == "n_subgraph"
    assert _sanitize_id("flowchart") == "n_flowchart"
    assert _sanitize_id("comp_0") == "comp_0"

    g = FlowGraph(title="Reserved Test")
    g.add_node(Node(id="start", label="Start", node_type=NodeType.START))
    g.add_node(Node(id="end", label="End", node_type=NodeType.END))
    g.add_edge(Edge(source="start", target="end"))
    mmd = to_mermaid(g)
    assert "n_end" in mmd
    assert "n_start" in mmd
    assert "\n    end([" not in mmd
    assert "\n    start([" not in mmd


def test_parser_extracts_class_methods():
    src = (
        "class MemoryDB:\n"
        "    def __init__(self):\n"
        "        pass\n"
        "    def upsert_run(self):\n"
        "        if self.ready:\n"
        "            self.conn.execute('insert')\n"
        "    def close(self):\n"
        "        self.conn.close()\n"
        "    def count_nodes(self):\n"
        "        return self.nodes\n"
    )
    g = parse_source(src)
    ids = {n.id for n in g.nodes}
    assert "fn_memorydb_upsert_run" in ids, f"Expected upsert_run in {ids}"
    assert "fn_memorydb_close" in ids, f"Expected close in {ids}"
    assert "fn_memorydb_count_nodes" in ids, f"Expected count_nodes in {ids}"
    assert "start" in ids
    assert len([i for i in ids if i.startswith("fn_memorydb")]) == 3


def test_save_html():
    from agentflow.html import save_html

    g = FlowGraph(title="Save HTML")
    g.add_node(Node(id="a", label="A"))
    g.add_node(Node(id="b", label="B"))
    g.add_edge(Edge(source="a", target="b"))

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "out.html"
        result = save_html(g, path)
        assert result.exists()
        text = result.read_text()
        assert "<!DOCTYPE html>" in text
        assert "<svg" in text
        assert "data-node-id" in text


def test_html_cli(tmp_path=None):
    import subprocess
    import sys

    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / "agent.py"
        src.write_text("class Agent:\n    def run(self):\n        if x:\n            do_a()\n")
        out = Path(tmpdir) / "out.html"
        result = subprocess.run(
            [sys.executable, "-m", "agentflow.cli", "-i", str(src), "-o", str(out), "-f", "html"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert out.exists()
        text = out.read_text()
        assert "<!DOCTYPE html>" in text
        assert "data-phase" in text


def test_html_diff():
    from agentflow.diff import diff_graphs
    from agentflow.html import to_html

    old = FlowGraph(title="old")
    old.add_node(Node(id="a", label="A"))
    new = FlowGraph(title="new")
    new.add_node(Node(id="a", label="A"))
    new.add_node(Node(id="b", label="B"))
    merged = diff_graphs(old, new)
    html = to_html(merged)
    assert 'data-node-id="b"' in html
    # Diff colors should be present in embedded SVG
    assert "#a7f3d0" in html or "added" in html.lower()


# ── Swimlane + edge semantics tests ───────────────────────────────────


def test_swimlane_layout():
    from agentflow.layouts import swimlane_layout

    graph = parse(SIMPLE_AGENT, title="Swimlane")
    result = swimlane_layout(graph)
    assert len(result.positioned) == graph.node_count
    assert len(result.lane_boxes) >= 1
    # Each node should have a lane
    assert all(p.group_id for p in result.positioned)
    # Lane boxes should not overlap?
    assert result.width > 0 and result.height > 0


def test_swimlane_has_expected_lanes():
    from agentflow.layouts import swimlane_layout

    g = FlowGraph(title="Lane Test")
    g.add_node(Node(id="a", label="Planner step", node_type=NodeType.PROCESS))
    g.add_node(Node(id="b", label="Tool call", node_type=NodeType.TOOL))
    g.add_node(Node(id="c", label="Memory update", node_type=NodeType.EVOLUTION))
    g.add_edge(Edge(source="a", target="b"))
    g.add_edge(Edge(source="b", target="c"))

    result = swimlane_layout(g)
    lane_ids = {p.group_id for p in result.positioned}
    assert "planner" in lane_ids
    assert "tools" in lane_ids
    assert "evolution" in lane_ids


def test_edge_semantic_colors():
    g = FlowGraph(title="Semantic")
    g.add_node(Node(id="a", label="A"))
    g.add_node(Node(id="b", label="B"))
    g.add_node(Node(id="c", label="C"))
    g.add_edge(Edge(source="a", target="b", label="YES"))
    g.add_edge(Edge(source="a", target="c", label="NO"))

    doc = to_excalidraw(g, seed=42)
    arrows = [e for e in doc["elements"] if e["type"] == "arrow"]
    colors = {e.get("strokeColor") for e in arrows}
    assert "#16a34a" in colors  # YES green
    assert "#dc2626" in colors  # NO red

    from agentflow.svg import to_svg

    svg = to_svg(g)
    assert "#16a34a" in svg
    assert "#dc2626" in svg


def test_swimlane_cli(tmp_path=None):
    import subprocess
    import sys

    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / "agent.py"
        src.write_text("class Agent:\n    def run(self):\n        if x:\n            do_a()\n        tool()\n")
        out = Path(tmpdir) / "out.excalidraw"
        result = subprocess.run(
            [sys.executable, "-m", "agentflow.cli", "-i", str(src), "-o", str(out), "-l", "swimlane"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert out.exists()
        data = json.loads(out.read_text())
        assert data["type"] == "excalidraw"

    # Also test mermaid swimlane
    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / "agent.py"
        src.write_text("class Agent:\n    def run(self):\n        if x:\n            do_a()\n")
        out = Path(tmpdir) / "out.mmd"
        result = subprocess.run(
            [sys.executable, "-m", "agentflow.cli", "-i", str(src), "-o", str(out), "-f", "mermaid", "-l", "swimlane"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "flowchart TD" in out.read_text()
        assert "subgraph" in out.read_text()


        assert result.returncode == 0
        assert "flowchart TD" in out.read_text()
        assert "subgraph" in out.read_text()


# ── V5: ASCII, DOT, palettes ──────────────────────────────────────────


def test_to_ascii():
    from agentflow.ascii import to_ascii

    g = FlowGraph(title="ASCII")
    g.add_node(Node(id="a", label="Start", node_type=NodeType.START))
    g.add_node(Node(id="b", label="Do it", node_type=NodeType.PROCESS))
    g.add_edge(Edge(source="a", target="b", label="go"))

    text = to_ascii(g)
    assert "Flow: ASCII" in text
    assert "START" in text
    assert "Do it" in text
    assert "go" in text


def test_to_ascii_detail_levels():
    from agentflow.ascii import to_ascii

    g = FlowGraph(title="Detail ASCII")
    g.add_node(Node(id="a", label="A", detail="line1\nline2", node_type=NodeType.PROCESS))
    low = to_ascii(g, detail="low")
    high = to_ascii(g, detail="high")
    assert len(high) > len(low)
    assert "line1" not in low
    assert "line1" in high


def test_to_dot():
    from agentflow.dot import to_dot

    g = FlowGraph(title="DOT")
    g.add_node(Node(id="a", label="Start", node_type=NodeType.START))
    g.add_node(Node(id="b", label="Decide?", node_type=NodeType.DECISION))
    g.add_edge(Edge(source="a", target="b", label="YES"))

    dot = to_dot(g)
    assert 'digraph "DOT"' in dot
    assert "Start" in dot
    assert "Decide?" in dot
    assert "YES" in dot
    assert "shape=ellipse" in dot
    assert "shape=diamond" in dot


def test_ascii_dot_cli(tmp_path=None):
    import subprocess
    import sys

    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / "agent.py"
        src.write_text("class Agent:\n    def run(self):\n        if x:\n            do_a()\n")
        for fmt, ext in [("ascii", ".txt"), ("dot", ".dot")]:
            out = Path(tmpdir) / f"out{ext}"
            result = subprocess.run(
                [sys.executable, "-m", "agentflow.cli", "-i", str(src), "-o", str(out), "-f", fmt],
                capture_output=True, text=True,
            )
            assert result.returncode == 0
            assert out.exists()
            assert len(out.read_text()) > 20


def test_palette_themes():
    g = FlowGraph(title="Palette")
    g.add_node(Node(id="a", label="A"))
    g.add_node(Node(id="b", label="B"))
    g.add_edge(Edge(source="a", target="b"))

    from agentflow.svg import to_svg

    light = to_svg(g, theme="light")
    pastel = to_svg(g, theme="pastel")
    neon = to_svg(g, theme="neon")
    mono = to_svg(g, theme="mono")
    assert light != pastel and light != neon and light != mono
    assert "#0a0a0a" in neon

    import subprocess
    import sys

    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / "a.py"
        src.write_text("class Agent:\n    def run(self):\n        pass\n")
        out = Path(tmpdir) / "out.svg"
        result = subprocess.run(
            [sys.executable, "-m", "agentflow.cli", "-i", str(src), "-o", str(out), "--palette", "neon"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "#0a0a0a" in out.read_text() or "#00ff88" in out.read_text()


# ── V6: sequence diagrams ─────────────────────────────────────────────

SEQ_SOURCE = '''
from core.planner import generate_plan
from tools.llm import llm_complete

class DeveloperAgent:
    def __init__(self):
        self.reviewer = ReviewerAgent()

    async def run(self):
        plan = generate_plan(task)
        result = llm_complete(prompt)
        ok = self.reviewer.check(result)
'''

SEQ_INSTANCE_SOURCE = '''
class Orchestrator:
    def run(self):
        planner = PlannerAgent()
        planner.generate_plan("task")
'''


def test_extract_interactions_imported_functions():
    from agentflow.sequence import extract_interactions

    ix = extract_interactions(SEQ_SOURCE)
    assert "Planner" in ix.actors
    assert "LLM" in ix.actors
    assert any(m.receiver == "Planner" and "generate_plan" in m.label for m in ix.messages)
    assert any(m.receiver == "LLM" for m in ix.messages)


def test_extract_interactions_instances():
    from agentflow.sequence import extract_interactions

    ix = extract_interactions(SEQ_INSTANCE_SOURCE, default_sender="Orchestrator")
    assert any(m.receiver == "Planner" for m in ix.messages)
    lines = [m.line for m in ix.messages]
    assert lines == sorted(lines)


def test_to_mermaid_sequence():
    from agentflow.sequence import extract_interactions, to_mermaid_sequence

    ix = extract_interactions(SEQ_SOURCE)
    text = to_mermaid_sequence(ix, title="Test")
    assert "sequenceDiagram" in text
    assert "participant Planner as Planner" in text
    assert "->>+" in text


def test_to_sequence_svg():
    from agentflow.sequence import extract_interactions, to_sequence_svg

    ix = extract_interactions(SEQ_INSTANCE_SOURCE, default_sender="Orchestrator")
    svg = to_sequence_svg(ix, title="Seq")
    assert "<svg" in svg
    assert 'stroke-dasharray="5 4"' in svg  # lifelines dashed
    import xml.dom.minidom

    xml.dom.minidom.parseString(svg)  # valid XML


def test_sequence_cli(tmp_path=None):
    import subprocess
    import sys

    with tempfile.TemporaryDirectory() as tmpdir:
        src = Path(tmpdir) / "agent.py"
        src.write_text(
            "from core.planner import generate_plan\n"
            "class MyAgent:\n    def run(self):\n        generate_plan('x')\n"
        )
        out_svg = Path(tmpdir) / "seq.svg"
        r1 = subprocess.run(
            [sys.executable, "-m", "agentflow.cli", "-i", str(src), "-o", str(out_svg), "-f", "sequence"],
            capture_output=True, text=True,
        )
        assert r1.returncode == 0
        assert out_svg.exists() and "<svg" in out_svg.read_text()

        out_mmd = Path(tmpdir) / "seq.mmd"
        r2 = subprocess.run(
            [sys.executable, "-m", "agentflow.cli", "-i", str(src), "-o", str(out_mmd), "-f", "mermaid-seq"],
            capture_output=True, text=True,
        )
        assert r2.returncode == 0
        assert "sequenceDiagram" in out_mmd.read_text()


# ── V7: sequence fragments (loop/alt/else) ────────────────────────────

SEQ_FRAGMENT_SOURCE = '''
from core.planner import generate_plan
from tools.llm import llm_complete

class DeveloperAgent:
    async def run(self):
        plan = generate_plan(task)
        if plan.need_repair:
            result = llm_complete(repair_prompt)
        elif plan.need_review:
            result = llm_complete(review_prompt)
        else:
            result = llm_complete(ok_prompt)
        while not result.ok:
            result = llm_complete(retry_prompt)
'''


def test_fragment_extraction():
    from agentflow.sequence import extract_interactions

    ix = extract_interactions(SEQ_FRAGMENT_SOURCE)
    # Should have alt (if), else (elif), else (else), loop (while)
    types = [f.type for f in ix.fragments]
    assert "alt" in types
    assert "loop" in types
    # Messages inside fragments exist
    assert len(ix.messages) >= 4


def test_fragment_mermaid():
    from agentflow.sequence import extract_interactions, to_mermaid_sequence

    ix = extract_interactions(SEQ_FRAGMENT_SOURCE)
    text = to_mermaid_sequence(ix, title="Fragments")
    assert "alt" in text
    assert "loop" in text
    assert "end" in text
    # Messages appear inside fragments
    assert "generate_plan" in text


def test_fragment_svg_valid():
    import xml.dom.minidom

    from agentflow.sequence import extract_interactions, to_sequence_svg

    ix = extract_interactions(SEQ_FRAGMENT_SOURCE)
    svg = to_sequence_svg(ix, title="Frag SVG")
    xml.dom.minidom.parseString(svg)  # valid XML
    # Fragment backgrounds rendered
    assert "[ALT]" in svg or "[LOOP]" in svg


def test_trivial_conditions_filtered():
    from agentflow.sequence import extract_interactions

    src = '''
class Agent:
    def run(self):
        if isinstance(result, dict):
            self.planner.do()
        if not ok:
            self.debugger.fix()
        if status == "success":
            self.memory.save()
'''
    ix = extract_interactions(src)
    # isinstance should be filtered, "not ok" should be filtered
    labels = [f.label for f in ix.fragments]
    assert not any("isinstance" in lbl for lbl in labels)


def test_orphan_else_filtered():
    from agentflow.sequence import extract_interactions

    src = '''
class Agent:
    def run(self):
        if True:
            self.planner.do()
        else:
            self.debugger.fix()
'''
    ix = extract_interactions(src)
    # else should exist since it has a matching alt
    # But a standalone else (without if) would be syntax error
    # Test that fragments have matching alt
    alt_count = sum(1 for f in ix.fragments if f.type == "alt")
    else_count = sum(1 for f in ix.fragments if f.type == "else")
    assert else_count <= alt_count  # no orphan else


# ── B1: framework profiles ────────────────────────────────────────────

LANGCHAIN_SOURCE = '''
from langchain.agents import AgentExecutor
from langchain.tools import Tool
from langchain.chains import LLMChain

class MyAgent:
    def __init__(self):
        self.chain = LLMChain()
        self.executor = AgentExecutor()

    def run(self):
        self.chain.invoke({"input": "hello"})
        self.executor.run(task)
'''


CREWAI_SOURCE = '''
from crewai import Agent, Crew, Task

class MyOrchestrator:
    def __init__(self):
        self.planner = Agent()
        self.crew = Crew()

    def run(self):
        self.planner.run("plan")
        self.crew.kickoff()
'''


AUTOGEN_SOURCE = '''
from autogen import AssistantAgent, UserProxyAgent, GroupChatManager

class MyChat:
    def __init__(self):
        self.assistant = AssistantAgent()
        self.proxy = UserProxyAgent()
        self.manager = GroupChatManager()

    def run(self):
        self.proxy.initiate_chat(self.assistant, message="hello")
'''


def test_langchain_profile_recognizes_chain():
    from agentflow.profiles import get_profile

    prof = get_profile("langchain")
    assert "AgentExecutor" in prof.agent_class_names
    assert "LLMChain" in prof.agent_class_names
    assert "invoke" in prof.tool_names


def test_crewai_profile_recognizes_crew():
    from agentflow.profiles import get_profile

    prof = get_profile("crewai")
    assert "Agent" in prof.agent_class_names
    assert "Crew" in prof.agent_class_names
    assert "kickoff" in prof.tool_names


def test_autogen_profile_recognizes_groupchat():
    from agentflow.profiles import get_profile

    prof = get_profile("autogen")
    assert "AssistantAgent" in prof.agent_class_names
    assert "GroupChatManager" in prof.agent_class_names
    assert "initiate_chat" in prof.tool_names


def test_langchain_sequence_profile():
    from agentflow.sequence import extract_interactions

    ix = extract_interactions(LANGCHAIN_SOURCE, profile="langchain")
    actors_lower = [a.lower() for a in ix.actors]
    # LLMChain → "LLM" or "Chain"; AgentExecutor → "Agent"
    assert any("chain" in a or "llm" in a for a in actors_lower)


def test_crewai_sequence_profile():
    from agentflow.sequence import extract_interactions

    ix = extract_interactions(CREWAI_SOURCE, profile="crewai")
    actors_lower = [a.lower() for a in ix.actors]
    # Crew → "Orchestrator"; Agent → "Agent"
    assert any("orchestrator" in a or "crew" in a or "agent" in a for a in actors_lower)


def test_autogen_sequence_profile():
    from agentflow.sequence import extract_interactions

    ix = extract_interactions(AUTOGEN_SOURCE, profile="autogen")
    actors_lower = [a.lower() for a in ix.actors]
    # AssistantAgent → "Assistant"; UserProxyAgent → "UserProxy"
    assert any("assistant" in a or "proxy" in a or "manager" in a for a in actors_lower)


def test_all_profiles_in_registry():
    from agentflow.profiles import PROFILES

    assert "generic" in PROFILES
    assert "reaweb" in PROFILES
    assert "langchain" in PROFILES
    assert "crewai" in PROFILES
    assert "autogen" in PROFILES


# ── v2.0: multi-file sequence analysis ────────────────────────────────

def test_merge_interactions_dedup():
    from agentflow.sequence import Interactions, Message, merge_interactions

    ix1 = Interactions(
        actors=["A", "B"],
        messages=[Message("A", "B", "do()", 1)],
    )
    ix2 = Interactions(
        actors=["B", "C"],
        messages=[Message("A", "B", "do()", 1), Message("B", "C", "fix()", 2)],
    )
    merged = merge_interactions([ix1, ix2])
    assert "A" in merged.actors
    assert "B" in merged.actors
    assert "C" in merged.actors
    assert len(merged.messages) == 2  # do() deduped


def test_multi_file_sequence(tmp_path):
    from agentflow.sequence import extract_interactions_multi

    f1 = tmp_path / "orchestrator.py"
    f1.write_text(
        "from planner import generate_plan\n"
        "class Orchestrator:\n"
        "    def run(self):\n"
        "        generate_plan('task')\n"
    )
    f2 = tmp_path / "planner.py"
    f2.write_text(
        "from tools.llm import llm_complete\n"
        "class PlannerAgent:\n"
        "    def generate_plan(self, task):\n"
        "        llm_complete('plan this')\n"
    )
    ix = extract_interactions_multi([f1, f2])
    # Should have actors from both files
    actors_lower = [a.lower() for a in ix.actors]
    assert any("orchestrator" in a or "planner" in a for a in actors_lower)


def test_extract_from_dir(tmp_path):
    from agentflow.sequence import extract_interactions_from_dir

    (tmp_path / "agent_a.py").write_text(
        "class AgentA:\n    def run(self):\n        pass\n"
    )
    (tmp_path / "agent_b.py").write_text(
        "class AgentB:\n    def run(self):\n        pass\n"
    )
    (tmp_path / "not_python.txt").write_text("ignore me\n")
    ix = extract_interactions_from_dir(tmp_path)
    actors_lower = [a.lower() for a in ix.actors]
    assert any("agenta" in a or "a" in a for a in actors_lower)
    assert any("agentb" in a or "b" in a for a in actors_lower)


def test_multi_file_mermaid(tmp_path):
    from agentflow.sequence import extract_interactions_multi, to_mermaid_sequence

    f1 = tmp_path / "orch.py"
    f1.write_text(
        "from planner import run_planner\n"
        "class Orch:\n    def run(self):\n        run_planner()\n"
    )
    f2 = tmp_path / "planner.py"
    f2.write_text(
        "def run_planner():\n    pass\n"
    )
    ix = extract_interactions_multi([f1, f2])
    text = to_mermaid_sequence(ix, title="Multi")
    assert "sequenceDiagram" in text


def test_build_import_actor_map():
    import ast

    from agentflow.sequence import _build_import_actor_map

    src = (
        "from core.planner import generate_plan\n"
        "from tools.llm import llm_complete\n"
        "from memory.store import store_data\n"
    )
    tree = ast.parse(src)
    m = _build_import_actor_map(tree)
    assert m.get("generate_plan") == "Planner"
    assert m.get("llm_complete") == "LLM"
    assert m.get("store_data") == "Memory"


# ── v2.0: match/case support ─────────────────────────────────────────

def test_match_case_parsing():
    """Parser handles Python 3.10+ match/case statements."""
    from agentflow.parser import parse_source

    src = '''
class Router:
    def run(self):
        match action:
            case "plan":
                self.planner.plan()
            case "debug":
                self.debugger.fix()
            case _:
                pass
'''
    graph = parse_source(src)
    labels = [n.label.lower() for n in graph.nodes]
    assert any("match" in lbl for lbl in labels)
    assert any("case" in lbl for lbl in labels)


def test_match_case_with_method():
    """match/case on method call."""
    from agentflow.parser import parse_source

    src = '''
class Agent:
    def run(self):
        match self.get_action():
            case "run":
                self.execute()
            case "stop":
                pass
'''
    graph = parse_source(src)
    labels = [n.label.lower() for n in graph.nodes]
    assert any("match" in lbl for lbl in labels)
