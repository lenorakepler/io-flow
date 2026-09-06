"""Jinja node templates: a directory of ``<type>.html``, rendered at build time.

A node type is a declaration -- one entry in a ``types.yaml`` naming a base and
a few Jinja fragments (``title``/``badge``/``meta``, or a whole inline
``template``). Three layers merge, entry by entry: the packaged
``assets/templates/types.yaml``, a project's ``templates/types.yaml``, and a
diagram's own top-level ``types:`` block. A type too big for a line gets a
``<type>.html`` file -- or ``<type>.html.j2``, which editors highlight as Jinja
-- in the templates directory, which wins over its declaration. Either way it is
plain HTML with ``{{ }}``, no JavaScript. Rendering happens here, in Python, during
the build: the result rides along on the node as ``html`` and ``templates.js``
hands it straight to the engine. Nothing re-renders a node in the browser
(``engine/viewer.js`` mounts each node exactly once), so baking it in at build
time costs nothing and keeps the artifact free of template machinery.

Declaring is never required: a type with neither a declaration nor a file
renders the base its children call for -- ``_compound`` when something is
parented to the node, ``_simple`` otherwise -- since compound-ness is a state,
not a type. An ``extends:`` in the declaration overrides that inference.
``<type>.sidebar.html`` -- or a declaration's ``sidebar:`` string -- does the
same for the detail panel, independently: a type may have a body, a sidebar,
both, or neither.

Reuse is a base plus slots::

    # types.yaml
    queue: {badge: queue, meta: ["{{ data.depth }} waiting"]}

or, for a file, Jinja inheritance::

    {# templates/queue.html.j2 #}
    {% extends "_simple.html" %}

``assets/templates/`` ships ``_simple.html``, ``_compound.html`` and
``_sidebar.html`` as bases; templates in the user's own directory shadow them by
name. Every type-derived name comes from the *node's own* type, never from the
template it inherited:
the wrapper's ``node--<type>`` class is set by the engine from ``node.type``,
and ``{{ type }}`` inside a template is likewise the node's own, so one shared
structure still renders per-type classes and badges.

CSS is unchanged: style a type with a ``.node--<type>`` rule via ``style: skin:``
(or ``css:``), same as any other type.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import ChainableUndefined, Environment, FileSystemLoader, TemplateError
from markupsafe import Markup
from ruamel.yaml import YAML

from .emit import ASSETS

BASES = ASSETS / "templates"

# `<type>.html` works, but `<type>.html.j2` is what editors recognize as Jinja
# (VS Code's Better Jinja maps *.html.j2; PyCharm's Jinja2 file type matches
# *.j2), so `{# #}` comments and tags highlight instead of reading as broken
# HTML. Both are accepted, everywhere.
TEMPLATE_SUFFIXES = (".html", ".html.j2")


class _Loader(FileSystemLoader):
    """FileSystemLoader that treats ``x.html`` and ``x.html.j2`` as one name.

    So ``{% extends "_simple.html" %}`` finds ``_simple.html.j2`` -- the
    inheritance line stays the same whichever suffix the file on disk wears.
    """

    def get_source(self, environment, template):
        try:
            return super().get_source(environment, template)
        except Exception:
            for a, b in ((".html", ".html.j2"), (".html.j2", ".html")):
                if template.endswith(a):
                    return super().get_source(environment, template[: -len(a)] + b)
            raise


def template_key(name: str) -> str | None:
    """``queue.html.j2`` -> ``queue``; ``None`` if it isn't a template file."""
    for suffix in TEMPLATE_SUFFIXES:
        if name.endswith(suffix) and len(name) > len(suffix):
            return name[: -len(suffix)]
    return None


TYPES_FILE = "types.yaml"


def load_types(
    directory: Path | None, diagram_types: dict[str, Any] | None = None
) -> dict[str, dict[str, Any]]:
    """Merge type declarations: packaged, then the project's ``templates/
    types.yaml``, then the diagram's own ``types:`` block.

    Entry by entry -- a later entry replaces the earlier one of that name
    outright, so a type is described in one place, not assembled from three.
    """
    yaml = YAML(typ="safe")
    types: dict[str, dict[str, Any]] = {}
    for path in (BASES / TYPES_FILE, directory / TYPES_FILE if directory else None):
        if path is None or not path.exists():
            continue
        loaded = yaml.load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise ValueError(f"{path}: must be a mapping of type name -> declaration")
        types.update({str(k): dict(v or {}) for k, v in loaded.items()})
    types.update({str(k): dict(v or {}) for k, v in (diagram_types or {}).items()})
    return types


def is_template_dir(templates: str | Path | None) -> bool:
    """True when ``templates`` points at a Jinja directory rather than a .js file."""
    return templates is not None and Path(templates).is_dir()


def prerender(
    graph: dict[str, Any],
    directory: str | Path | None = None,
    default_sidebar: str | Path | None = None,
) -> dict[str, Any]:
    """Return a copy of ``graph`` with ``html``/``sidebar`` on every templated node.

    ``default_sidebar`` is a skin's sidebar template (see ``emit.skin_assets``),
    used for any node whose type has no ``<type>.sidebar.html`` of its own.
    Nodes with no template at all are passed through untouched, so the packaged
    ``templates.js`` still renders them.
    """
    directory = Path(directory) if directory is not None else None
    default_sidebar = Path(default_sidebar) if default_sidebar is not None else None
    search = [str(p) for p in (directory, default_sidebar.parent if default_sidebar else None)
              if p is not None]
    env = Environment(
        loader=_Loader([*search, str(BASES)]),
        autoescape=True,
        # A missing YAML field is empty, not an error -- `data.loc` on a node
        # without one is the normal case, and chaining keeps `{% if %}` honest.
        undefined=ChainableUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    # {"queue": "queue.html.j2", "queue.sidebar": "queue.sidebar.html", ...} --
    # keyed by the part before the suffix, so both spellings look the same here.
    have = (
        {key: p.name for p in sorted(directory.iterdir())
         if (key := template_key(p.name)) is not None}
        if directory is not None
        else {}
    )

    types = load_types(directory, graph.get("types"))

    def context(node: dict[str, Any]) -> dict[str, Any]:
        return {
            "node": node,
            "id": node["id"],
            "type": node["type"],
            "label": node.get("label") or node["id"],
            "data": node.get("data") or {},
            "parent": node.get("parent"),
        }

    def render(name: str, node: dict[str, Any], **extra_ctx) -> str:
        try:
            return env.get_template(name).render(**context(node), **extra_ctx)
        except TemplateError as exc:
            raise ValueError(
                f"{name}: {exc.__class__.__name__}: {exc} (rendering node ${node['id']})"
            ) from exc

    def render_source(source: str, node: dict[str, Any], where: str) -> str:
        """Render an inline Jinja string from a types.yaml declaration."""
        try:
            return env.from_string(source).render(context(node))
        except TemplateError as exc:
            raise ValueError(
                f"types.yaml {node['type']}.{where}: {exc.__class__.__name__}: {exc} "
                f"(rendering node ${node['id']})"
            ) from exc

    # Compound-ness is a state, not a type: which base a node gets follows from
    # whether anything is parented to it, unless its declaration says otherwise.
    parents = {n.get("parent") for n in graph["nodes"] if n.get("parent") is not None}

    def from_declaration(spec: dict[str, Any], node: dict[str, Any]) -> str:
        """Render a type's declaration: an inline body, or a base plus slots."""
        if spec.get("template"):
            return render_source(spec["template"], node, "template")
        slots: dict[str, Any] = {}
        for slot in ("title", "badge"):
            if spec.get(slot):
                slots[slot] = Markup(render_source(spec[slot], node, slot).strip())
        # A meta line that renders blank is dropped -- that is how "show `cli`
        # only when there is one" stays a one-liner instead of a conditional.
        lines = [render_source(m, node, "meta").strip() for m in spec.get("meta") or []]
        slots["meta"] = [Markup(line) for line in lines if line]
        base = spec.get("extends") or (
            "_compound" if node["id"] in parents else "_simple"
        )
        return render(f"{base}.html", node, **slots)

    nodes = []
    for node in graph["nodes"]:
        # Body: `<type>.html` file, else the type's declaration. Sidebar:
        # `<type>.sidebar.html` file, else the declaration's `sidebar:`, else a
        # skin's default sidebar template. Every layer is optional; whatever is
        # missing falls through to the packaged templates.js.
        spec = types.get(node["type"]) or {}
        extra = {}
        if node["type"] in have:
            extra["html"] = render(have[node["type"]], node)
        else:
            # No declaration is itself a declaration: an empty spec renders the
            # base its children (or lack of them) call for.
            extra["html"] = from_declaration(spec, node)
        sidebar = f"{node['type']}.sidebar"
        if sidebar in have:
            extra["sidebar"] = render(have[sidebar], node)
        elif spec.get("sidebar"):
            extra["sidebar"] = render_source(spec["sidebar"], node, "sidebar")
        elif default_sidebar is not None:
            extra["sidebar"] = render(default_sidebar.name, node)
        nodes.append({**node, **extra} if extra else node)
    return {**graph, "nodes": nodes}
