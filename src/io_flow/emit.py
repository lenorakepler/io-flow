"""Assemble the self-contained single-file HTML viewer.

Inlines the graph JSON, viewer CSS, all JS (vendored elkjs + panzoom, the
editable ``templates.js``, and the engine modules) into ``viewer.html``. The
output references no CDNs and makes zero network requests.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ASSETS = Path(__file__).resolve().parent / "assets"

# Load order matters: vendored globals first, then the editable template map,
# then engine modules, with the bootstrap (`viewer.js`) last.
SCRIPT_MANIFEST = [
    "vendor/elk.bundled.js",
    "vendor/panzoom.min.js",
    "templates.js",
    "engine/layout.js",
    "engine/edges.js",
    "engine/dim.js",
    "engine/pan.js",
    "engine/drag.js",
    "engine/save.js",
    "engine/viewer.js",
]


def _read(rel: str) -> str:
    return (ASSETS / rel).read_text(encoding="utf-8")


def _safe_script_body(js: str) -> str:
    """Neutralize any literal ``</script`` so inlining can't break the tag."""
    return js.replace("</script", "<\\/script")


def _inline_json(graph: dict[str, Any]) -> str:
    """JSON safe to embed in a <script type="application/json"> block."""
    text = json.dumps(graph, ensure_ascii=False)
    # Prevent `</script>` and `<!--` breakouts while staying valid JSON.
    return text.replace("<", "\\u003c")


def build_html(graph: dict[str, Any]) -> str:
    shell = _read("viewer.html")
    styles = _read("viewer.css")

    scripts = []
    for rel in SCRIPT_MANIFEST:
        path = ASSETS / rel
        if not path.exists():
            continue  # engine modules are added milestone-by-milestone
        scripts.append(f"<script>\n{_safe_script_body(path.read_text(encoding='utf-8'))}\n</script>")
    scripts_html = "\n".join(scripts)

    html = shell.replace("/*__STYLES__*/", styles)
    html = html.replace("/*__GRAPH__*/", _inline_json(graph))
    html = html.replace("<!--__SCRIPTS__-->", scripts_html)
    return html


def write_html(graph: dict[str, Any], out_path: str | Path) -> Path:
    out_path = Path(out_path)
    out_path.write_text(build_html(graph), encoding="utf-8")
    return out_path
