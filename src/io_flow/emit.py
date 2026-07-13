"""Assemble the self-contained single-file HTML viewer.

Inlines the graph JSON, viewer CSS, all JS (vendored elkjs + panzoom, the
editable ``templates.js``, and the engine modules) into ``viewer.html``. The
output references no CDNs and makes zero network requests.
"""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

DEFAULT_TITLE = "io-flow diagram"

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
    "engine/resize.js",
    "engine/save.js",
    "engine/connect.js",
    "engine/anchors.js",
    "engine/live.js",
    "engine/collapse.js",
    "engine/ui.js",
    "engine/a11y.js",
    "engine/viewer.js",
]

# elkjs is ~1.6 MB. When every node position is pinned (layout mode
# "restore") the browser never runs ELK, so it can be omitted entirely.
ELK_ASSET = "vendor/elk.bundled.js"


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


def elk_omitted(graph: dict[str, Any]) -> bool:
    """True when the artifact can ship without elkjs (all positions pinned)."""
    return (graph.get("_layout") or {}).get("mode") == "restore"


def _skin_assets(skin: str) -> tuple[Path | None, Path | None]:
    """Resolve a bundled skin name to its (css, js) delta files (either optional).

    A skin is layered *on top of* the packaged assets (css appended after
    viewer.css; js injected right after templates.js), so a skin file holds only
    its overrides -- no need to fork the whole viewer.css / templates.js."""
    base = ASSETS / "skins"
    css_path, js_path = base / f"{skin}.css", base / f"{skin}.js"
    if not css_path.exists() and not js_path.exists():
        available = sorted(p.stem for p in base.glob("*.css")) if base.exists() else []
        raise FileNotFoundError(
            f"unknown skin {skin!r}; bundled skins: {', '.join(available) or 'none'}"
        )
    return (css_path if css_path.exists() else None,
            js_path if js_path.exists() else None)


def build_html(
    graph: dict[str, Any],
    css: str | Path | None = None,
    templates: str | Path | None = None,
    skin: str | None = None,
) -> str:
    """Assemble the single-file HTML.

    ``css`` / ``templates`` optionally point at project-local files *replacing*
    the packaged ``viewer.css`` / ``templates.js``. ``skin`` names a bundled
    skin (e.g. ``codemap``) *layered on top* -- additive css + a sidebar/JS
    override -- without forking the base assets.
    """
    shell = _read("viewer.html")
    styles = Path(css).read_text(encoding="utf-8") if css else _read("viewer.css")

    skin_css, skin_js = _skin_assets(skin) if skin else (None, None)
    if skin_css is not None:
        styles = styles + "\n" + skin_css.read_text(encoding="utf-8")

    scripts = []
    for rel in SCRIPT_MANIFEST:
        if rel == ELK_ASSET and elk_omitted(graph):
            continue
        path = Path(templates) if (rel == "templates.js" and templates) else ASSETS / rel
        if not path.exists():
            raise FileNotFoundError(
                f"engine asset missing: {path} (broken install or manifest drift)"
            )
        scripts.append(f"<script>\n{_safe_script_body(path.read_text(encoding='utf-8'))}\n</script>")
        # A skin's JS overrides IOF.* right after templates.js, before the engine.
        if rel == "templates.js" and skin_js is not None:
            scripts.append(f"<script>\n{_safe_script_body(skin_js.read_text(encoding='utf-8'))}\n</script>")
    scripts_html = "\n".join(scripts)

    title = graph.get("title") or DEFAULT_TITLE
    out = shell.replace("/*__STYLES__*/", styles)
    out = out.replace("<!--__TITLE__-->", html.escape(str(title)))
    out = out.replace("/*__GRAPH__*/", _inline_json(graph))
    out = out.replace("<!--__SCRIPTS__-->", scripts_html)
    return out


def write_html(
    graph: dict[str, Any],
    out_path: str | Path,
    css: str | Path | None = None,
    templates: str | Path | None = None,
    skin: str | None = None,
) -> Path:
    out_path = Path(out_path)
    out_path.write_text(build_html(graph, css=css, templates=templates, skin=skin), encoding="utf-8")
    return out_path
