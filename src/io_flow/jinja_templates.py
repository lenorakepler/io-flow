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

Reuse is Jinja inheritance. A new type that looks like an existing one is a
one-line file::

    {# templates/queue.html #}
    {% extends "_simple.html" %}

``assets/templates/`` ships ``_simple.html`` and ``_compound.html`` as bases;
templates in the user's own directory shadow them by name. Every type-derived
name comes from the *node's own* type, never from the template it inherited:
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
    """Return a copy of ``graph`` with an ``html`` string on every templated node.

    Nodes whose type has no ``<type>.html`` are passed through untouched, so the
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
    nodes = []
    for node in graph["nodes"]:
        name = f"{node['type']}.html"
        if name not in have:
            nodes.append(node)
            continue
        try:
            html = env.get_template(name).render(
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
        nodes.append({**node, "html": html})
    return {**graph, "nodes": nodes}
