"""Jinja node templates: a directory of ``<type>.html``, rendered at build time.

Pointing ``--templates`` (or ``style: templates:``) at a *directory* instead of a
``.js`` file makes ``<type>.html`` -- or ``<type>.html.j2``, which editors
highlight as Jinja -- the template for nodes of that type: plain HTML with
``{{ }}``, no JavaScript. Rendering happens here, in Python, during
the build: the result rides along on the node as ``html`` and ``templates.js``
hands it straight to the engine. Nothing re-renders a node in the browser
(``engine/viewer.js`` mounts each node exactly once), so baking it in at build
time costs nothing and keeps the artifact free of template machinery.

A type with no ``<type>.html`` falls through to the packaged ``templates.js``
map, so the two surfaces mix freely -- convert one type at a time.
``<type>.sidebar.html`` does the same for the detail panel, independently: a
type may have a body template, a sidebar template, both, or neither.

Reuse is Jinja inheritance. A new type that looks like an existing one is a
one-line file::

    {# templates/queue.html #}
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

    def render(name: str, node: dict[str, Any]) -> str:
        try:
            return env.get_template(name).render(
                node=node,
                id=node["id"],
                type=node["type"],
                label=node.get("label") or node["id"],
                data=node.get("data") or {},
                parent=node.get("parent"),
            )
        except TemplateError as exc:
            raise ValueError(
                f"{name}: {exc.__class__.__name__}: {exc} (rendering node ${node['id']})"
            ) from exc

    nodes = []
    for node in graph["nodes"]:
        # `<type>.html` is the node body; `<type>.sidebar.html` is its detail
        # panel. Both are opt-in per type and independent -- a type can have
        # either, both, or neither -- and a skin's default sidebar covers the
        # types that named no sidebar template of their own.
        extra = {}
        if node["type"] in have:
            extra["html"] = render(have[node["type"]], node)
        sidebar = f"{node['type']}.sidebar"
        if sidebar in have:
            extra["sidebar"] = render(have[sidebar], node)
        elif default_sidebar is not None:
            extra["sidebar"] = render(default_sidebar.name, node)
        nodes.append({**node, **extra} if extra else node)
    return {**graph, "nodes": nodes}
