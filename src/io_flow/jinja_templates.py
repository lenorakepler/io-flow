"""Jinja node templates: a directory of ``<type>.html``, rendered at build time.

Pointing ``--templates`` (or ``style: templates:``) at a *directory* instead of a
``.js`` file makes ``<type>.html`` the template for nodes of that type -- plain
HTML with ``{{ }}``, no JavaScript. Rendering happens here, in Python, during
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


def is_template_dir(templates: str | Path | None) -> bool:
    """True when ``templates`` points at a Jinja directory rather than a .js file."""
    return templates is not None and Path(templates).is_dir()


def prerender(graph: dict[str, Any], directory: str | Path) -> dict[str, Any]:
    """Return a copy of ``graph`` with ``html``/``sidebar`` on every templated node.

    Nodes whose type has neither template are passed through untouched, so the
    packaged ``templates.js`` still renders them.
    """
    directory = Path(directory)
    env = Environment(
        loader=FileSystemLoader([str(directory), str(BASES)]),
        autoescape=True,
        # A missing YAML field is empty, not an error -- `data.loc` on a node
        # without one is the normal case, and chaining keeps `{% if %}` honest.
        undefined=ChainableUndefined,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    have = {p.name for p in directory.glob("*.html")}

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
        # either, both, or neither.
        extra = {
            key: render(name, node)
            for key, name in (
                ("html", f"{node['type']}.html"),
                ("sidebar", f"{node['type']}.sidebar.html"),
            )
            if name in have
        }
        nodes.append({**node, **extra} if extra else node)
    return {**graph, "nodes": nodes}
