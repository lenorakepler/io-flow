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


SKIN_SUFFIXES = (".css", ".js", ".html", ".j2")

# A skin's default sidebar template: `<name>.sidebar.html` (or `.html.j2`)
# beside `<name>.css`. Unlike `templates/<type>.sidebar.html` it is not keyed by
# node type -- it is the skin's layout for every node with no type-specific one.
SIDEBAR_SUFFIXES = (".sidebar.html", ".sidebar.html.j2")


def skin_assets(
    skin: str | Path | list[str | Path] | None,
) -> tuple[list[Path], list[Path], list[Path]]:
    """Resolve skin entries to their (css, js, sidebar-template) files, in order.

    An entry ending in ``.css``/``.js``/``.sidebar.html`` is a project-local
    file; anything else is a bundled skin name under ``assets/skins`` (every
    part optional). Skins are layered *on top of* the packaged assets (css
    appended after viewer.css; js injected right after templates.js), so a skin
    file holds only its overrides -- no need to fork the whole viewer.css /
    templates.js."""
    if not skin:
        return [], [], []
    entries = [skin] if isinstance(skin, (str, Path)) else list(skin)
    base = ASSETS / "skins"
    css_paths: list[Path] = []
    js_paths: list[Path] = []
    sidebar_paths: list[Path] = []
    for entry in entries:
        path = Path(entry)
        if path.suffix in SKIN_SUFFIXES:
            if not path.exists():
                raise FileNotFoundError(f"skin file not found: {path}")
            bucket = {".css": css_paths, ".js": js_paths}.get(path.suffix, sidebar_paths)
            bucket.append(path)
            continue
        found = False
        for suffix, bucket in ((".css", css_paths), (".js", js_paths),
                               *((s, sidebar_paths) for s in SIDEBAR_SUFFIXES)):
            candidate = base / f"{entry}{suffix}"
            if candidate.exists():
                bucket.append(candidate)
                found = True
        if not found:
            available = sorted({p.name.split(".")[0] for p in base.glob("*.*")}) \
                if base.exists() else []
            raise FileNotFoundError(
                f"unknown skin {str(entry)!r}; bundled skins: "
                f"{', '.join(available) or 'none'} "
                f"(a project-local skin file needs a .css, .js or .sidebar.html suffix)"
            )
    return css_paths, js_paths, sidebar_paths


def build_html(
    graph: dict[str, Any],
    css: str | Path | None = None,
    templates: str | Path | None = None,
    skin: str | Path | list[str | Path] | None = None,
) -> str:
    """Assemble the single-file HTML.

    ``css`` / ``templates`` optionally point at project-local files *replacing*
    the packaged ``viewer.css`` / ``templates.js``. ``skin`` is one entry or a
    list of them, *layered on top* in order -- a bundled skin name (e.g.
    ``codemap``) or a project-local ``.css``/``.js``/``.sidebar.html`` file --
    so overrides stack without forking the base assets.

    Any of these omitted here fall back to the diagram's own ``style:`` block
    (see the parser), so a YAML can carry its look; an explicit argument
    (typically a CLI flag) always wins.
    """
    style = graph.get("style") or {}
    if css is None:
        css = style.get("css")
    if templates is None:
        templates = style.get("templates")
    if skin is None:
        skin = style.get("skin")

    # Skin css is appended after the base css, in order, so later entries win.
    skin_css, skin_js, skin_sidebars = skin_assets(skin)

    # `templates` pointing at a *directory* means Jinja `<type>.html` templates;
    # a skin may also carry a default sidebar template. Render both here, ride
    # the results along on each node, and keep shipping the packaged
    # templates.js as the fallback for whatever has no template.
    from . import jinja_templates

    tpl_dir = templates if jinja_templates.is_template_dir(templates) else None
    if tpl_dir is not None or skin_sidebars:
        graph = jinja_templates.prerender(
            graph, tpl_dir, default_sidebar=skin_sidebars[-1] if skin_sidebars else None
        )
        if tpl_dir is not None:
            templates = None

    shell = _read("viewer.html")
    styles = Path(css).read_text(encoding="utf-8") if css else _read("viewer.css")
    for path in skin_css:
        styles = styles + "\n" + path.read_text(encoding="utf-8")

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
        # Skin JS overrides IOF.* right after templates.js, before the engine.
        if rel == "templates.js":
            for js_path in skin_js:
                scripts.append(
                    f"<script>\n{_safe_script_body(js_path.read_text(encoding='utf-8'))}\n</script>"
                )
    scripts_html = "\n".join(scripts)

    title = graph.get("title") or DEFAULT_TITLE
    out = shell.replace("/*__STYLES__*/", styles)
    out = out.replace("<!--__TITLE__-->", html.escape(str(title)))
    # `style` is a build-time concern (and holds local filesystem paths); keep
    # it out of the viewer JSON embedded in the artifact.
    graph_json = {k: v for k, v in graph.items() if k != "style"} if "style" in graph else graph
    out = out.replace("/*__GRAPH__*/", _inline_json(graph_json))
    out = out.replace("<!--__SCRIPTS__-->", scripts_html)
    return out


def write_html(
    graph: dict[str, Any],
    out_path: str | Path,
    css: str | Path | None = None,
    templates: str | Path | None = None,
    skin: str | Path | list[str | Path] | None = None,
) -> Path:
    out_path = Path(out_path)
    out_path.write_text(
        build_html(graph, css=css, templates=templates, skin=skin), encoding="utf-8"
    )
    return out_path
