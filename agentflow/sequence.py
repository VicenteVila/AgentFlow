"""Multi-agent sequence diagram support.

Extracts interactions between agents from Python source (calls on
instances of ``*Agent`` classes or attributes whose name contains an
actor keyword), then renders them as:

- Mermaid ``sequenceDiagram`` (renders on GitHub)
- Standalone SVG with lifelines and ordered arrows

Heuristics (documented, deterministic):
- Actors: classes named ``*Agent`` / ``*Orchestrator`` defined in the file,
  plus module-level instances (``planner = PlannerAgent()``).
- Messages: ``instance.method(...)`` calls inside methods of the main class,
  and ``self.<actor>.method(...)`` chains. Ordered by line number.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass, field
from pathlib import Path

ACTOR_SUFFIXES = ("Agent", "Orchestrator")
_ACTOR_NAME_HINTS = ("planner", "developer", "debugger", "orchestrator",
                     "designer", "agent", "scout", "reviewer", "llm", "memory")


@dataclass
class Message:
    sender: str
    receiver: str
    label: str
    line: int


@dataclass
class Interactions:
    actors: list[str] = field(default_factory=list)
    messages: list[Message] = field(default_factory=list)

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


def _is_actor_class_name(name: str) -> bool:
    return any(name.endswith(suf) for suf in ACTOR_SUFFIXES)


def _looks_like_actor(name: str) -> bool:
    low = name.lower()
    return any(hint in low for hint in _ACTOR_NAME_HINTS)


def extract_interactions(source: str, default_sender: str | None = None) -> Interactions:
    """Parse *source* and extract actors + ordered messages."""
    tree = ast.parse(source)
    interactions = Interactions()

    # 1. Actor classes defined in the file
    class_names: set[str] = set()
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef) and (_is_actor_class_name(node.name) or _looks_like_actor(node.name)):
            class_names.add(node.name)
            short = node.name.replace("Agent", "").replace("Orchestrator", "") or node.name
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
            if cls_name and (cls_name[:1].isupper() and (_is_actor_class_name(cls_name) or _looks_like_actor(cls_name))):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        short = cls_name.replace("Agent", "").replace("Orchestrator", "") or cls_name
                        instance_to_actor[target.id] = short
                        if short not in interactions.actors:
                            interactions.actors.append(short)

    # 2b. Imported functions from actor-ish modules:
    #     `from cogniteam.core.planner import generate_plan` → Planner
    func_to_actor: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            mod_low = node.module.lower()
            hit = None
            for hint in _ACTOR_NAME_HINTS:
                if hint in mod_low:
                    # Prefer the deepest segment containing the hint
                    for seg in reversed(node.module.split(".")):
                        if hint in seg.lower():
                            hit = seg
                            break
                    break
            if hit:
                import re as _re
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

    # 4. Find messages inside methods/functions
    def visit_body(body: list[ast.stmt], current_sender: str) -> None:
        for stmt in body:
            for node in ast.walk(stmt):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    recv_node = node.func.value
                    method = node.func.attr
                    receiver = None
                    if isinstance(recv_node, ast.Name) and recv_node.id in instance_to_actor:
                        receiver = instance_to_actor[recv_node.id]
                    elif isinstance(recv_node, ast.Attribute) and _looks_like_actor(recv_node.attr):
                        receiver = recv_node.attr.replace("_", " ").title()
                    if receiver and receiver != current_sender:
                        interactions.messages.append(Message(
                            sender=current_sender, receiver=receiver,
                            label=f"{method}()", line=node.lineno,
                        ))
                elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                    if node.func.id in func_to_actor:
                        receiver = func_to_actor[node.func.id]
                        if receiver != current_sender:
                            interactions.messages.append(Message(
                                sender=current_sender, receiver=receiver,
                                label=f"{node.func.id}()", line=node.lineno,
                            ))

    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            visit_body(node.body, sender)

    for cls in ast.iter_child_nodes(tree):
        if isinstance(cls, ast.ClassDef):
            cls_sender = cls.name.replace("Agent", "").replace("Orchestrator", "") or cls.name
            for item in cls.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    visit_body(item.body, cls_sender)

    # Deduplicate consecutive identical messages, keep order
    deduped: list[Message] = []
    for m in sorted(interactions.messages, key=lambda m: m.line):
        if deduped and (deduped[-1].sender, deduped[-1].receiver, deduped[-1].label) == (m.sender, m.receiver, m.label):
            continue
        deduped.append(m)
    interactions.messages = deduped

    return interactions


def extract_from_file(path: str | Path, default_sender: str | None = None) -> Interactions:
    return extract_interactions(
        Path(path).read_text(encoding="utf-8"), default_sender=default_sender
    )


# ── Mermaid rendering ─────────────────────────────────────────────────


def to_mermaid_sequence(interactions: Interactions, title: str = "") -> str:
    """Render interactions as a Mermaid ``sequenceDiagram``."""
    lines: list[str] = []
    if title:
        safe = title.replace('"', "'").replace("\n", " ")
        lines.append(f"%% {safe}")
    lines.append("sequenceDiagram")
    for p in interactions.all_participants:
        alias = p.replace(" ", "_")
        lines.append(f"    participant {alias} as {p}")
    lines.append("")
    for m in interactions.messages:
        s = m.sender.replace(" ", "_")
        r = m.receiver.replace(" ", "_")
        label = m.label.replace('"', "'")
        lines.append(f"    {s}->>+{r}: {label}")
        lines.append(f"    {r}-->>-{s}: done")
    return "\n".join(lines) + "\n"


# ── SVG rendering ──────────────────────────────────────────────────────

_LANE_W = 200
_MSG_H = 56
_TOP = 110
_FONT = "Helvetica, Arial, sans-serif"


def to_sequence_svg(interactions: Interactions, title: str = "") -> str:
    """Render interactions as a standalone SVG sequence diagram."""
    participants = interactions.all_participants
    n = max(len(participants), 1)
    width = max(n * _LANE_W + 80, 640)
    height = _TOP + max(len(interactions.messages), 1) * _MSG_H + 80

    xs = {p: 60 + i * _LANE_W + _LANE_W // 2 for i, p in enumerate(participants)}

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

    # Messages in order
    for i, m in enumerate(interactions.messages):
        y = _TOP + 30 + i * _MSG_H
        x1 = xs.get(m.sender, xs[participants[0]])
        x2 = xs.get(m.receiver, xs[participants[-1]])
        color = "#2563eb" if x2 > x1 else "#dc2626"
        esc_l = m.label.replace("&", "&amp;").replace("<", "&lt;")
        mx = (x1 + x2) / 2
        parts.append(
            f'<line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" stroke="{color}" '
            f'stroke-width="2" marker-end="url(#seq-arrow)"/>'
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
