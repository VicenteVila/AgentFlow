"""Property-based / fuzz tests for the AgentFlow parser.

Uses Hypothesis to generate random Python source code and verify that the
parser, sequence extractor, and renderers never crash (only on valid code).
"""

from __future__ import annotations

import hypothesis.strategies as st
from hypothesis import given, settings

from agentflow.ascii import to_ascii
from agentflow.dot import to_dot
from agentflow.mermaid import to_mermaid
from agentflow.models import NodeType
from agentflow.parser import parse_source
from agentflow.sequence import (
    extract_interactions,
    to_mermaid_sequence,
    to_sequence_svg,
)

# ── Strategies ────────────────────────────────────────────────────────

# Valid Python identifiers
IDENT = st.from_regex(r"[A-Za-z_][A-Za-z0-9_]{0,20}", fullmatch=True).filter(
    lambda s: s not in {"True", "False", "None", "and", "or", "not", "if", "else",
                         "while", "for", "class", "def", "return", "import", "from",
                         "as", "try", "except", "finally", "with", "lambda", "yield",
                         "global", "nonlocal", "assert", "del", "pass", "break",
                         "continue", "raise", "in", "is", "async", "await"}
)

# Simple expressions that are always valid Python
SIMPLE_EXPR = st.one_of(
    st.integers(min_value=-100, max_value=100),
    st.just("True"),
    st.just("False"),
    st.just("None"),
    st.just("self"),
    st.just("x"),
    st.just("result"),
)

# A statement that is always valid inside a method body (already indented)
SAFE_STMT = st.one_of(
    st.tuples(IDENT, SIMPLE_EXPR).map(lambda t: f"{t[0]} = {t[1]}"),
    st.just("return None"),
    st.just("return True"),
    st.just("return self"),
    st.tuples(IDENT, SIMPLE_EXPR).map(lambda t: f"self.{t[0]} = {t[1]}"),
    st.just("pass"),
    st.tuples(IDENT).map(lambda t: f"{t[0]}()"),
    st.tuples(IDENT).map(lambda t: f"self.{t[0]}()"),
)


@st.composite
def agent_method_body(draw):
    """Generate a method body with 1-3 safe statements."""
    n = draw(st.integers(min_value=1, max_value=3))
    stmts = draw(st.lists(SAFE_STMT, min_size=n, max_size=n))
    return "\n    ".join(stmts)


@st.composite
def simple_agent_class(draw):
    """Generate a minimal valid agent class."""
    cls_name = draw(IDENT.filter(lambda s: s[0].isupper()))
    method_body = draw(agent_method_body())
    return (
        f"class {cls_name}:\n"
        f"    def run(self):\n"
        f"        {method_body}"
    )


@st.composite
def agent_with_init(draw):
    """Generate an agent class with __init__ and run."""
    cls_name = draw(IDENT.filter(lambda s: s[0].isupper()))
    init_body = draw(agent_method_body())
    run_body = draw(agent_method_body())
    return (
        f"class {cls_name}:\n"
        f"    def __init__(self):\n"
        f"        {init_body}\n"
        f"    def run(self):\n"
        f"        {run_body}"
    )


@st.composite
def multi_agent_source(draw):
    """Generate source with 1-3 agent-like classes."""
    n = draw(st.integers(min_value=1, max_value=3))
    classes = []
    for _ in range(n):
        cls = draw(st.one_of(simple_agent_class(), agent_with_init()))
        classes.append(cls)
    return "\n\n".join(classes)


# ── Tests ─────────────────────────────────────────────────────────────


@given(source=simple_agent_class())
@settings(max_examples=50, deadline=None)
def test_parser_never_crashes(source: str):
    """Parser should not crash on any valid Python class with a run method."""
    graph = parse_source(source, title="Fuzz")
    assert graph.title == "Fuzz"
    assert len(graph.nodes) >= 2  # at least start + end


@given(source=agent_with_init())
@settings(max_examples=50, deadline=None)
def test_parser_with_init(source: str):
    """Parser handles __init__ + run without crashing."""
    graph = parse_source(source)
    assert len(graph.nodes) >= 2


@given(source=multi_agent_source())
@settings(max_examples=50, deadline=None)
def test_parser_multi_agent(source: str):
    """Parser handles multiple classes."""
    graph = parse_source(source)
    assert len(graph.nodes) >= 2


@given(source=multi_agent_source())
@settings(max_examples=50, deadline=None)
def test_sequence_never_crashes(source: str):
    """Sequence extraction should not crash on valid Python."""
    ix = extract_interactions(source)
    assert isinstance(ix.actors, list)
    assert isinstance(ix.messages, list)
    assert isinstance(ix.fragments, list)


@given(source=multi_agent_source())
@settings(max_examples=50, deadline=None)
def test_mermaid_seq_never_crashes(source: str):
    """Mermaid sequence rendering should not crash."""
    ix = extract_interactions(source)
    text = to_mermaid_sequence(ix, title="Fuzz Seq")
    assert "sequenceDiagram" in text


@given(source=multi_agent_source())
@settings(max_examples=50, deadline=None)
def test_svg_seq_never_crashes(source: str):
    """SVG sequence rendering should not crash."""
    import xml.dom.minidom

    ix = extract_interactions(source)
    svg = to_sequence_svg(ix, title="Fuzz SVG")
    xml.dom.minidom.parseString(svg)  # valid XML


@given(source=multi_agent_source())
@settings(max_examples=50, deadline=None)
def test_mermaid_flow_never_crashes(source: str):
    """Mermaid flowchart rendering should not crash."""
    graph = parse_source(source)
    text = to_mermaid(graph)
    assert "flowchart" in text.lower() or len(text) == 0


@given(source=multi_agent_source())
@settings(max_examples=50, deadline=None)
def test_ascii_never_crashes(source: str):
    """ASCII rendering should not crash."""
    graph = parse_source(source)
    text = to_ascii(graph)
    assert isinstance(text, str)


@given(source=multi_agent_source())
@settings(max_examples=50, deadline=None)
def test_dot_never_crashes(source: str):
    """DOT rendering should not crash."""
    graph = parse_source(source)
    text = to_dot(graph)
    assert isinstance(text, str)
    if text:
        assert "digraph" in text


@given(source=simple_agent_class())
@settings(max_examples=50, deadline=None)
def test_parser_node_types_valid(source: str):
    """All nodes have valid NodeType values."""
    graph = parse_source(source)
    valid_types = {t.value for t in NodeType}
    for node in graph.nodes:
        assert node.node_type.value in valid_types, f"Invalid type: {node.node_type}"


@given(source=multi_agent_source())
@settings(max_examples=50, deadline=None)
def test_sequence_deterministic(source: str):
    """Sequence extraction is deterministic (same source → same output)."""
    ix1 = extract_interactions(source)
    ix2 = extract_interactions(source)
    assert ix1.actors == ix2.actors
    assert len(ix1.messages) == len(ix2.messages)
    assert len(ix1.fragments) == len(ix2.fragments)
    for m1, m2 in zip(ix1.messages, ix2.messages, strict=True):
        assert m1.sender == m2.sender
        assert m1.receiver == m2.receiver
        assert m1.line == m2.line
