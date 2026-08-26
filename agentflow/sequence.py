"""Multi-agent sequence diagram support.

Extracts interactions between agents from Python source (calls on
instances of ``*Agent`` classes or attributes whose name contains an
actor keyword), then renders them as:

- Mermaid ``sequenceDiagram`` (renders on GitHub) with ``loop``/``alt``/``else``
- Standalone SVG with lifelines, ordered arrows, and colored fragments

Heuristics (documented, deterministic):
- Actors: classes named ``*Agent`` / ``*Orchestrator`` defined in the file,
  plus module-level instances (``planner = PlannerAgent()``).
- Messages: ``instance.method(...)`` calls inside methods of the main class,
  and ``self.<actor>.method(...)`` chains. Ordered by line number.
- Fragments: ``if``/``elif``/``else`` → ``alt``/``else``; ``while``/``for`` → ``loop``.
"""

from __future__ import annotations

import ast
import re as _re
from dataclasses import dataclass, field
from pathlib import Path

from agentflow.profiles import Profile, get_profile

ACTOR_SUFFIXES = ("Agent", "Orchestrator")
_ACTOR_NAME_HINTS = ("planner", "developer", "debugger", "orchestrator",
                     "designer", "agent", "scout", "reviewer", "llm", "memory")


# ── Data model ────────────────────────────────────────────────────────


@dataclass
class Message:
    sender: str
    receiver: str
    label: str
    line: int


@dataclass
class Fragment:
    """A control-flow fragment wrapping a group of messages.

    Types:
    - ``loop``  : ``while`` / ``for``  (``loop ... end``)
    - ``alt``   : ``if`` / ``elif``    (``alt ... else ... end``)
    - ``else``  : ``else`` branch     (inside a preceding ``alt``)
    """
    type: str  # "loop" | "alt" | "else"
    label: str
    begin_line: int
    end_line: int = 0  # filled during extraction


@dataclass
class Interactions:
    actors: list[str] = field(default_factory=list)
    messages: list[Message] = field(default_factory=list)
    fragments: list[Fragment] = field(default_factory=list)

    @property
    def all_participants(self) -> list[str]:
        seen: list[str] = []
        for a in self.actors:
            if a not in seen:
                seen.append(a)
        for m in self.messages:
            for who in (m.sender, m.receiver):
                if who not in seen:
                    seen.append(who)
        return seen


# ── Actor detection helpers ────────────────────────────────────────────


def _is_actor_class_name(name: str) -> bool:
    return any(name.endswith(suf) for suf in ACTOR_SUFFIXES)


def _looks_like_actor(name: str) -> bool:
    low = name.lower()
    return any(hint in low for hint in _ACTOR_NAME_HINTS)


# ── Fragment extraction ───────────────────────────────────────────────


def _try_unwrap_call(stmt: ast.stmt) -> ast.Call | None:
    """Return the Call inside an Expr, unwrapping Await if needed."""
    if isinstance(stmt, ast.Expr):
        val = stmt.value
        if isinstance(val, ast.Await):
            val = val.value
        if isinstance(val, ast.Call):
            return val
    return None


def _extract_fragments_from_if(
    node: ast.If,
    lines: list[Fragment],
    depth: int,
) -> None:
    """Walk ``if``/``elif``/``else`` chains → flat ``alt``/``else`` fragments.

    ``elif`` is flattened: the ``else`` of one ``if`` that itself is an
    ``If`` is treated as the next ``elif`` branch, sharing one ``alt`` block.
    """
    if depth > 6:
        return

    # Collect all branch labels in the chain
    branches: list[tuple[str, list[ast.stmt], int]] = []
    current: ast.If | None = node
    while current:
        label = ast.unparse(current.test) if hasattr(ast, "unparse") else "condition"
        branches.append((label, current.body, current.lineno))
        orelse = current.orelse
        if len(orelse) == 1 and isinstance(orelse[0], ast.If):
            current = orelse[0]
        elif orelse:
            branches.append(("else", orelse, orelse[0].lineno))
            current = None
        else:
            current = None

    # Emit one alt + else markers; recurse only into branch bodies
    for i, (label, body, lineno) in enumerate(branches):
        if i == 0:
            lines.append(Fragment(type="alt", label=label, begin_line=lineno))
        else:
            lines.append(Fragment(type="else", label=label, begin_line=lineno))
        _collect_fragments(body, lines, depth + 1)


def _collect_fragments(body: list[ast.stmt], lines: list[Fragment], depth: int) -> None:
    """Collect fragment boundary markers by walking a statement list."""
    if depth > 6:
        return
    for stmt in body:
        if isinstance(stmt, ast.If):
            _extract_fragments_from_if(stmt, lines, depth)
        elif isinstance(stmt, (ast.While, ast.For, ast.AsyncFor)):
            if isinstance(stmt, ast.While):
                test = stmt.test
                if isinstance(test, ast.Constant) and test.value is True:
                    label = "while True"
                else:
                    label = ast.unparse(test) if hasattr(ast, "unparse") else "loop"
            else:
                target = stmt.target
                label = f"for {target.id}" if isinstance(target, ast.Name) else "for"
            lines.append(Fragment(type="loop", label=label, begin_line=stmt.lineno))
            _collect_fragments(stmt.body, lines, depth + 1)


# ── Main extraction ───────────────────────────────────────────────────


def _is_significant_condition(label: str) -> bool:
    """Return True if the condition is significant enough to show as a fragment.

    Filters out trivial type checks, format validations, and attribute tests
    that clutter agent sequence diagrams.
    """
    low = label.lower().strip()
    # Skip trivial isinstance/hasattr/type checks
    if low.startswith("isinstance") or low.startswith("hasattr"):
        return False
    # Skip simple attribute existence / None checks
    if low.startswith("not ") and " " not in low[4:]:
        return False
    if low in ("true", "false", "none"):
        return False
    # Skip string equality checks for format/type validation
    # e.g. expected_format == 'json', output.get('success')
    if "==" in low and any(k in low for k in ("format", "type", "mode", "status")):
        return False
    if low.endswith("in available") or low.endswith("in expected"):
        return False
    # Skip dict key checks: output.get('success'), isinstance(output, dict)
    if "output" in low and ("get(" in low or "dict" in low or "success" in low or "result" in low):
        return False
    # Skip simple variable checks: if valid, if ok, if result
    if low in ("valid", "ok", "result", "done", "success", "passed", "failed"):
        return False
    # Skip checks on m/match objects
    return not (low.startswith("m ") or low.startswith("m.") or low.startswith("m and"))


def extract_interactions(source: str, default_sender: str | None = None, *, profile: str | Profile | None = None) -> Interactions:
    """Parse *source* and extract actors + ordered messages + fragments."""
    prof = get_profile(profile) if profile else None
    tree = ast.parse(source)
    interactions = Interactions()

    # Profile's agent class names (for framework-specific detection)
    prof_agent_names: dict[str, str] = prof.agent_class_names if prof else {}

    # 1. Actor classes defined in the file
    class_names: set[str] = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef) and (
            _is_actor_class_name(node.name)
            or _looks_like_actor(node.name)
            or node.name in prof_agent_names
        ):
            class_names.add(node.name)
            short = prof_agent_names.get(
                node.name,
                node.name.replace("Agent", "").replace("Orchestrator", "") or node.name,
            )
            if short not in interactions.actors:
                interactions.actors.append(short)

    # 2. Module-level instances: var = ActorClass()
    instance_to_actor: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            func = node.value.func
            cls_name = None
            if isinstance(func, ast.Name):
                cls_name = func.id
            elif isinstance(func, ast.Attribute):
                cls_name = func.attr
            if cls_name and (
                cls_name[:1].isupper()
                and (
                    _is_actor_class_name(cls_name)
                    or _looks_like_actor(cls_name)
                    or cls_name in prof_agent_names
                )
            ):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        short = prof_agent_names.get(
                            cls_name,
                            cls_name.replace("Agent", "").replace("Orchestrator", "") or cls_name,
                        )
                        instance_to_actor[target.id] = short
                        if short not in interactions.actors:
                            interactions.actors.append(short)
                    elif isinstance(target, ast.Attribute) and isinstance(target.value, ast.Name):
                        # self.chain = LLMChain() → map "chain" (stripped "self.")
                        attr_name = target.attr
                        short = prof_agent_names.get(
                            cls_name,
                            cls_name.replace("Agent", "").replace("Orchestrator", "") or cls_name,
                        )
                        instance_to_actor[attr_name] = short
                        if short not in interactions.actors:
                            interactions.actors.append(short)

    # 2b. Imported functions from actor-ish modules
    func_to_actor: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            mod_low = node.module.lower()
            hit = None
            for hint in _ACTOR_NAME_HINTS:
                if hint in mod_low:
                    for seg in reversed(node.module.split(".")):
                        if hint in seg.lower():
                            hit = seg
                            break
                    break
            if hit:
                actor = _re.sub(r"[ _-]?agents?$", "", hit, flags=_re.IGNORECASE)
                actor = actor.replace("_", " ").strip().title() or "Agent"
                if actor.lower() == "llm":
                    actor = "LLM"
                for alias in node.names:
                    func_to_actor[alias.asname or alias.name] = actor
                if actor not in interactions.actors:
                    interactions.actors.append(actor)

    # 3. Main sender
    sender = default_sender
    if not sender:
        if class_names:
            main_cls = sorted(class_names)[0]
            sender = main_cls.replace("Agent", "").replace("Orchestrator", "") or main_cls
        else:
            sender = "Self"
    if sender not in interactions.actors:
        interactions.actors.insert(0, sender)

    # 4. Find messages + fragments inside methods/functions
    raw_messages: list[Message] = []
    raw_fragments: list[Fragment] = []

    def _extract_message(call: ast.Call, current_sender: str) -> None:
        func = call.func
        receiver = None
        label = ""
        if isinstance(func, ast.Attribute):
            recv_node = func.value
            method = func.attr
            if isinstance(recv_node, ast.Name) and recv_node.id in instance_to_actor:
                receiver = instance_to_actor[recv_node.id]
                label = f"{method}()"
            elif isinstance(recv_node, ast.Attribute):
                # self.chain.invoke() → look up "chain" in instance_to_actor
                inner = recv_node.attr
                if inner in instance_to_actor:
                    receiver = instance_to_actor[inner]
                    label = f"{method}()"
                elif _looks_like_actor(inner):
                    receiver = inner.replace("_", " ").title()
                    label = f"{method}()"
        elif isinstance(func, ast.Name):
            if func.id in func_to_actor:
                receiver = func_to_actor[func.id]
                label = f"{func.id}()"
        if receiver and receiver != current_sender:
            raw_messages.append(Message(sender=current_sender, receiver=receiver,
                                       label=label, line=call.lineno))

    def visit_body(body: list[ast.stmt], current_sender: str) -> None:
        for stmt in body:
            # Extract messages from expressions
            call = _try_unwrap_call(stmt)
            if call:
                _extract_message(call, current_sender)
            # Also walk nested calls
            for node in ast.walk(stmt):
                if node is not stmt and isinstance(node, ast.Call):
                    _extract_message(node, current_sender)

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            visit_body(node.body, sender)
            _collect_fragments(node.body, raw_fragments, 0)

    for cls in ast.iter_child_nodes(tree):
        if isinstance(cls, ast.ClassDef):
            cls_sender = cls.name.replace("Agent", "").replace("Orchestrator", "") or cls.name
            for item in cls.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    visit_body(item.body, cls_sender)
                    _collect_fragments(item.body, raw_fragments, 0)

    # 5. Sort messages by line; only remove exact duplicate lines
    interactions.messages = sorted(
        {m.line: m for m in raw_messages}.values(),
        key=lambda m: m.line,
    )

    # 6. Deduplicate + filter trivial/empty fragments, sort by line
    frag_deduped: list[Fragment] = []
    seen_f: set[tuple[str, str]] = set()
    for f in sorted(raw_fragments, key=lambda f: f.begin_line):
        key = (f.type, f.label)
        if key in seen_f:
            continue
        # Skip trivial conditions (isinstance, simple attribute checks)
        if f.type == "alt" and not _is_significant_condition(f.label):
            continue
        seen_f.add(key)
        frag_deduped.append(f)
    # Set end_line: each fragment ends at the next fragment's begin_line,
    # or at the last message line
    max_line = max((m.line for m in interactions.messages), default=0)
    for i, frag in enumerate(frag_deduped):
        frag.end_line = frag_deduped[i + 1].begin_line if i + 1 < len(frag_deduped) else max_line

    # Remove fragments that contain no messages (pure validation logic)
    msg_lines = {m.line for m in interactions.messages}
    frag_deduped = [
        f for f in frag_deduped
        if any(f.begin_line <= ml <= f.end_line for ml in msg_lines)
    ]

    # Remove orphaned 'else' fragments (no preceding 'alt' in the list)
    cleaned: list[Fragment] = []
    for f in frag_deduped:
        if f.type == "else" and not any(
            af.type == "alt" and af.begin_line < f.begin_line for af in cleaned
        ):
            continue
        cleaned.append(f)
    frag_deduped = cleaned

    interactions.fragments = frag_deduped

    return interactions


def extract_from_file(path: str | Path, default_sender: str | None = None, *, profile: str | Profile | None = None) -> Interactions:
    return extract_interactions(
        Path(path).read_text(encoding="utf-8"), default_sender=default_sender, profile=profile
    )


# ── Mermaid rendering ─────────────────────────────────────────────────


def to_mermaid_sequence(interactions: Interactions, title: str = "") -> str:
    """Render interactions as a Mermaid ``sequenceDiagram`` with fragments."""
    lines: list[str] = []
    if title:
        safe = title.replace('"', "'").replace("\n", " ")
        lines.append(f"%% {safe}")
    lines.append("sequenceDiagram")
    for p in interactions.all_participants:
        alias = p.replace(" ", "_")
        lines.append(f"    participant {alias} as {p}")
    lines.append("")

    # Sort fragments by begin_line
    frags = sorted(interactions.fragments, key=lambda f: f.begin_line)

    if not frags:
        # No fragments: emit messages directly
        for m in interactions.messages:
            _emit_mermaid_msg(lines, m)
        return "\n".join(lines) + "\n"

    # Emit with fragments in line order
    emitted: set[int] = set()
    indent = "    "
    frag_idx = [0]
    nesting = [0]

    def _emit_frags_up_to(line: int) -> None:
        while frag_idx[0] < len(frags):
            f = frags[frag_idx[0]]
            if f.begin_line > line:
                break
            alias_f = f.label.replace('"', "'")[:60]
            if f.type == "loop":
                lines.append(f"{indent}loop {alias_f}")
                nesting[0] += 1
            elif f.type == "alt":
                lines.append(f"{indent}alt {alias_f}")
                nesting[0] += 1
            elif f.type == "else":
                # else is a branch inside the current alt, not a new nesting level
                lines.append(f"{indent}else {alias_f}")
            frag_idx[0] += 1

    def _close_all() -> None:
        while nesting[0] > 0:
            lines.append(f"{indent}end")
            nesting[0] -= 1

    # Build sorted events: fragment opens + messages
    events: list[tuple[int, int, object]] = []
    for f in frags:
        events.append((f.begin_line, 0, f))
    for m in interactions.messages:
        events.append((m.line, 1, m))
    events.sort(key=lambda e: (e[0], e[1]))

    for line, kind, obj in events:
        if kind == 0:
            _emit_frags_up_to(line)
        elif kind == 1 and obj.line not in emitted:
            _emit_mermaid_msg(lines, obj)
            emitted.add(obj.line)

    _close_all()

    # Emit any remaining messages not inside fragments
    for m in interactions.messages:
        if m.line not in emitted:
            _emit_mermaid_msg(lines, m)

    return "\n".join(lines) + "\n"


def _emit_mermaid_msg(lines: list[str], m: Message) -> None:
    s = m.sender.replace(" ", "_")
    r = m.receiver.replace(" ", "_")
    label = m.label.replace('"', "'")
    lines.append(f"    {s}->>+{r}: {label}")
    lines.append(f"    {r}-->>-{s}: done")


# ── SVG rendering ──────────────────────────────────────────────────────

_LANE_W = 200
_MSG_H = 56
_TOP = 110
_FONT = "Helvetica, Arial, sans-serif"

_FRAGMENT_COLORS: dict[str, tuple[str, str]] = {
    "loop": ("#dbeafe", "#2563eb"),   # blue background/border
    "alt":  ("#fef9c3", "#ca8a04"),   # yellow background/border
    "else": ("#f0fdf4", "#16a34a"),   # green background/border
}


def to_sequence_svg(interactions: Interactions, title: str = "") -> str:
    """Render interactions as a standalone SVG sequence diagram with fragments."""
    participants = interactions.all_participants
    n = max(len(participants), 1)
    # Adaptive lane width for many actors
    lane_w = max(_LANE_W, min(300, 1200 // n))
    width = max(n * lane_w + 80, 640)
    height = _TOP + max(len(interactions.messages), 1) * _MSG_H + 80

    xs = {p: 60 + i * lane_w + lane_w // 2 for i, p in enumerate(participants)}

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}">'
    )
    parts.append('<defs><marker id="seq-arrow" viewBox="0 0 10 10" refX="9" refY="5" '
                 'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
                 '<path d="M 0 1 L 9 5 L 0 9 z" fill="#495057"/></marker></defs>')
    parts.append('<rect width="100%" height="100%" fill="#ffffff"/>')

    if title:
        esc = title.replace("&", "&amp;").replace("<", "&lt;")
        parts.append(f'<text x="40" y="40" font-family="{_FONT}" font-size="20" '
                     f'font-weight="bold" fill="#1e1e1e">{esc}</text>')

    # Lifelines
    for p in participants:
        x = xs[p]
        esc_p = p.replace("&", "&amp;").replace("<", "&lt;")
        parts.append(
            f'<rect x="{x - 70}" y="{_TOP - 45}" width="140" height="34" rx="8" '
            f'fill="#ede9fe" stroke="#7c3aed" stroke-width="2"/>'
        )
        parts.append(f'<text x="{x}" y="{_TOP - 23}" font-family="{_FONT}" font-size="13" '
                     f'fill="#1e1e1e" text-anchor="middle">{esc_p}</text>')
        bottom = _TOP + max(len(interactions.messages), 1) * _MSG_H + 10
        parts.append(f'<line x1="{x}" y1="{_TOP}" x2="{x}" y2="{bottom}" '
                     f'stroke="#adb5bd" stroke-width="1.5" stroke-dasharray="5 4"/>')

    # Build line→y index
    msg_y: dict[int, float] = {}
    for i, m in enumerate(interactions.messages):
        msg_y[m.line] = _TOP + 30 + i * _MSG_H

    # Render fragment backgrounds
    frags = sorted(interactions.fragments, key=lambda f: f.begin_line)
    frag_pad_y = 12
    for frag in frags:
        # Find messages inside this fragment
        inner_lines = [ml for ml in msg_y if frag.begin_line <= ml <= frag.end_line]
        if not inner_lines:
            continue
        y_min = min(msg_y[ml] for ml in inner_lines) - frag_pad_y - 16
        y_max = max(msg_y[ml] for ml in inner_lines) + frag_pad_y + 8
        x_min = min(xs.values()) - 60
        x_max = max(xs.values()) + 60
        bg, stroke = _FRAGMENT_COLORS.get(frag.type, ("#f8f9fa", "#868e96"))
        # Draw background rect
        parts.append(
            f'<rect x="{x_min}" y="{y_min}" width="{x_max - x_min}" '
            f'height="{y_max - y_min}" rx="6" fill="{bg}" '
            f'stroke="{stroke}" stroke-width="1.5" stroke-dasharray="6 3" opacity="0.85"/>'
        )
        # Label in top-left
        esc_l = frag.label.replace("&", "&amp;").replace("<", "&lt;")[:50]
        parts.append(
            f'<text x="{x_min + 8}" y="{y_min + 16}" font-family="{_FONT}" '
            f'font-size="10" fill="{stroke}" font-weight="bold">'
            f'[{frag.type.upper()}] {esc_l}</text>'
        )

    # Messages in order
    for i, m in enumerate(interactions.messages):
        y = msg_y[m.line]
        x1 = xs.get(m.sender, xs[participants[0]])
        x2 = xs.get(m.receiver, xs[participants[-1]])
        # Semantic color: left→right blue, right→left red
        color = "#2563eb" if x2 > x1 else "#dc2626"
        # Check if message is inside a loop fragment → dashed
        in_loop = any(f.type == "loop" and f.begin_line <= m.line <= f.end_line
                      for f in frags)
        dash = ' stroke-dasharray="6 3"' if in_loop else ""
        esc_l = m.label.replace("&", "&amp;").replace("<", "&lt;")
        mx = (x1 + x2) / 2
        parts.append(
            f'<line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" stroke="{color}" '
            f'stroke-width="2"{dash} marker-end="url(#seq-arrow)"/>'
        )
        parts.append(f'<text x="{mx}" y="{y - 8}" font-family="{_FONT}" font-size="12" '
                     f'fill="#495057" text-anchor="middle">{esc_l}</text>')
        parts.append(f'<text x="30" y="{y + 4}" font-family="{_FONT}" font-size="10" '
                     f'fill="#adb5bd">{i + 1}. L{m.line}</text>')

    parts.append("</svg>")
    return "".join(parts)


def save_sequence_svg(interactions: Interactions, output_path: str | Path,
                      title: str = "") -> Path:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_sequence_svg(interactions, title=title), encoding="utf-8")
    return path
