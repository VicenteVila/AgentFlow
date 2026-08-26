"""Render a FlowGraph as a self-contained interactive HTML page.

The page embeds the SVG diagram (with data-phase / data-node-id attributes)
and adds vanilla JS for pan/zoom, phase/group toggles and text search.
No external dependencies — the file works offline via ``file://``.
"""

from __future__ import annotations

from pathlib import Path

from agentflow.svg import to_svg

_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; font-family: system-ui, -apple-system, Segoe UI, sans-serif; background: {page_bg}; color: #212529; }}
  header {{ padding: 14px 20px; background: #fff; border-bottom: 1px solid #dee2e6; display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }}
  header h1 {{ margin: 0; font-size: 18px; font-weight: 600; flex: 1; min-width: 200px; }}
  #controls {{ display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }}
  #controls input[type="search"] {{ padding: 6px 10px; border: 1px solid #ced4da; border-radius: 6px; font-size: 13px; width: 200px; }}
  #controls button {{ padding: 6px 10px; border: 1px solid #ced4da; border-radius: 6px; background: #fff; cursor: pointer; font-size: 12px; }}
  #controls button.active {{ background: #1971c2; color: #fff; border-color: #1971c2; }}
  #controls button:hover {{ background: #e9ecef; }}
  #controls button.active:hover {{ background: #1864ab; }}
  #canvas {{ overflow: hidden; width: 100%; height: calc(100vh - 60px); background: {canvas_bg}; cursor: grab; position: relative; }}
  #canvas svg {{ transform-origin: 0 0; display: block; }}
  #canvas.grabbing {{ cursor: grabbing; }}
  .search-match {{ outline: 2px solid #ffd43b; outline-offset: 2px; filter: drop-shadow(0 0 6px #ffd43b); }}
  .dimmed {{ opacity: 0.15 !important; pointer-events: none; }}
  #zoom-hint {{ position: absolute; bottom: 12px; right: 12px; background: rgba(255,255,255,0.9); padding: 6px 10px; border-radius: 6px; font-size: 11px; color: #495057; border: 1px solid #dee2e6; }}
</style>
</head>
<body>
<header>
  <h1>{title}</h1>
  <div id="controls">
    <input type="search" id="search" placeholder="Buscar nodo…" autocomplete="off">
    <span id="phase-toggles"></span>
    <button id="zoom-in" title="Zoom +">+</button>
    <button id="zoom-out" title="Zoom −">−</button>
    <button id="zoom-reset" title="Reset">Reset</button>
  </div>
</header>
<div id="canvas">{svg}</div>
<div id="zoom-hint">Rueda: zoom · Arrastra: pan · Click fase: colapsar</div>
<script>
(function() {{
  const canvas = document.getElementById('canvas');
  const svg = canvas.querySelector('svg');
  let scale = 1, tx = 0, ty = 0, isPanning = false, startX = 0, startY = 0;

  function updateTransform() {{
    svg.style.transform = `translate(${{tx}}px, ${{ty}}px) scale(${{scale}})`;
  }}

  canvas.addEventListener('wheel', e => {{
    e.preventDefault();
    const delta = e.deltaY > 0 ? 0.9 : 1.1;
    const newScale = Math.min(Math.max(scale * delta, 0.2), 5);
    // Zoom toward cursor
    const rect = canvas.getBoundingClientRect();
    const cx = e.clientX - rect.left;
    const cy = e.clientY - rect.top;
    tx = cx - (cx - tx) * (newScale / scale);
    ty = cy - (cy - ty) * (newScale / scale);
    scale = newScale;
    updateTransform();
  }}, {{ passive: false }});

  canvas.addEventListener('mousedown', e => {{
    isPanning = true;
    startX = e.clientX - tx;
    startY = e.clientY - ty;
    canvas.classList.add('grabbing');
  }});
  window.addEventListener('mousemove', e => {{
    if (!isPanning) return;
    tx = e.clientX - startX;
    ty = e.clientY - startY;
    updateTransform();
  }});
  window.addEventListener('mouseup', () => {{
    isPanning = false;
    canvas.classList.remove('grabbing');
  }});

  document.getElementById('zoom-in').onclick = () => {{ scale = Math.min(scale * 1.25, 5); updateTransform(); }};
  document.getElementById('zoom-out').onclick = () => {{ scale = Math.max(scale * 0.8, 0.2); updateTransform(); }};
  document.getElementById('zoom-reset').onclick = () => {{ scale = 1; tx = 0; ty = 0; updateTransform(); }};

  // Search
  const search = document.getElementById('search');
  const nodeEls = Array.from(svg.querySelectorAll('[data-node-id]'));
  search.addEventListener('input', () => {{
    const q = search.value.trim().toLowerCase();
    nodeEls.forEach(el => {{
      const txt = (el.textContent || '').toLowerCase();
      const match = q && txt.includes(q);
      el.classList.toggle('search-match', match);
      if (q && !match && el.hasAttribute('data-node-id')) {{
        // Dim non-matches only when query active
        // Keep dimming subtle: only dim text, not shapes? Dim both for clarity
      }}
    }});
    // Dim non-matching nodes when searching
    if (q) {{
      const matchedIds = new Set(nodeEls.filter(el => el.classList.contains('search-match')).map(el => el.getAttribute('data-node-id')));
      nodeEls.forEach(el => {{
        const id = el.getAttribute('data-node-id');
        if (!matchedIds.has(id)) el.classList.add('dimmed');
        else el.classList.remove('dimmed');
      }});
    }} else {{
      nodeEls.forEach(el => el.classList.remove('dimmed', 'search-match'));
    }}
  }});

  // Phase / group toggles — collect unique values
  const phaseVals = [...new Set(Array.from(svg.querySelectorAll('[data-phase]')).map(el => el.getAttribute('data-phase')).filter(v => v && v !== '0'))];
  const groupVals = [...new Set(Array.from(svg.querySelectorAll('[data-group]')).map(el => el.getAttribute('data-group')).filter(v => v))];
  const toggleContainer = document.getElementById('phase-toggles');
  const idToPhase = new Map();
  svg.querySelectorAll('[data-node-id][data-phase]').forEach(el => {{
    const id = el.getAttribute('data-node-id');
    if (!idToPhase.has(id)) idToPhase.set(id, el.getAttribute('data-phase'));
  }});
  svg.querySelectorAll('[data-node-id][data-group]').forEach(el => {{
    const id = el.getAttribute('data-node-id');
    if (!idToPhase.has(id + ':group')) idToPhase.set(id + ':group', el.getAttribute('data-group'));
  }});

  function makeToggle(label, key, attr) {{
    const btn = document.createElement('button');
    btn.textContent = label;
    btn.classList.add('active');
    btn.dataset.key = key;
    btn.dataset.attr = attr;
    btn.onclick = () => {{
      btn.classList.toggle('active');
      const hide = !btn.classList.contains('active');
      svg.querySelectorAll(`[${{attr}}="${{CSS.escape(key)}}"]`).forEach(el => {{
        el.style.opacity = hide ? '0.12' : '';
        el.style.pointerEvents = hide ? 'none' : '';
      }});
      // For edges, hide if either endpoint phase is collapsed
      if (attr === 'data-phase' || attr === 'data-group') {{
        const collapsed = new Set(Array.from(toggleContainer.querySelectorAll('button:not(.active)')).map(b => b.dataset.key));
        svg.querySelectorAll('path[data-source]').forEach(path => {{
          const src = path.getAttribute('data-source');
          const tgt = path.getAttribute('data-target');
          const srcPhase = idToPhase.get(src) || idToPhase.get(src + ':group');
          const tgtPhase = idToPhase.get(tgt) || idToPhase.get(tgt + ':group');
          const shouldHide = collapsed.has(srcPhase) || collapsed.has(tgtPhase) || collapsed.has(path.getAttribute(attr));
          path.style.opacity = shouldHide ? '0.12' : '';
          path.style.pointerEvents = shouldHide ? 'none' : '';
        }});
      }}
    }};
    return btn;
  }}

  phaseVals.forEach(v => toggleContainer.appendChild(makeToggle(`FASE ${{v}}`, v, 'data-phase')));
  groupVals.forEach(v => toggleContainer.appendChild(makeToggle(v, v, 'data-group')));
}})();
</script>
</body>
</html>
"""


def to_html(
    graph,
    layout: str = "hierarchical",
    theme: str = "light",
    legend: bool = True,
    detail: str = "high",
) -> str:
    """Render *graph* as a self-contained interactive HTML page."""
    # Theme-aware page background
    page_bg = "#f8f9fa" if theme == "light" else "#0f0f0f"
    # SVG already carries its own canvas background; keep page slightly different
    svg_text = to_svg(graph, layout=layout, theme=theme, legend=legend, detail=detail)
    # Ensure SVG has an id for JS targeting (inject if missing)
    if 'id="diagram"' not in svg_text:
        svg_text = svg_text.replace("<svg ", '<svg id="diagram" ', 1)
    # Derive canvas background from theme for the wrapper
    from agentflow.layouts import get_theme
    pal = get_theme(theme)
    canvas_bg = pal["canvas_background"]
    return _HTML_TEMPLATE.format(
        title=graph.title,
        svg=svg_text,
        page_bg=page_bg,
        canvas_bg=canvas_bg,
    )


def save_html(
    graph,
    output_path: str | Path,
    layout: str = "hierarchical",
    theme: str = "light",
    legend: bool = True,
    detail: str = "high",
) -> Path:
    """Save an interactive HTML file for *graph*."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        to_html(graph, layout=layout, theme=theme, legend=legend, detail=detail),
        encoding="utf-8",
    )
    return path
