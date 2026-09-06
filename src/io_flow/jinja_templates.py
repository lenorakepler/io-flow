"""Jinja node templates: a directory of ``<type>.html``, rendered at build time.

A node type is a declaration -- one entry in a ``types.yaml`` naming the type it
extends and a few Jinja fragments (``title``/``badge``/``meta``, or a whole
inline ``template``). Three layers merge, entry by entry: the packaged
``assets/templates/types.yaml``, a project's ``templates/types.yaml``, and a
diagram's own top-level ``types:`` block. A type too big for a line gets a
``<type>.html`` file -- or ``<type>.html.j2``, which editors highlight as Jinja
-- in the templates directory, which wins over its declaration. Either way it is
plain HTML with ``{{ }}``, no JavaScript. Rendering happens here, in Python, during
the build: the result rides along on the node as ``html`` and ``templates.js``
hands it straight to the engine. Nothing re-renders a node in the browser
(``engine/viewer.js`` mounts each node exactly once), so baking it in at build
time costs nothing and keeps the artifact free of template machinery.

There is no separate "base" concept: ``node`` and ``group`` are ordinary types
(rendered by ``node.html.j2`` / ``group.html.j2``) that anything may extend, and
their templates own the wrapper element -- classes, ``data-node-id`` and all.
Declaring is never required either: a type with neither a declaration nor a file
renders through ``group.html`` when something is parented to the node and
``node.html`` otherwise, since compound-ness is a state, not a type. That gives
structure without the group *look*; ``extends: group`` is how you ask for both.
``<type>.sidebar.html`` -- or a declaration's ``sidebar:`` string -- does the
same for the detail panel, independently: a type may have a body, a sidebar,
both, or neither.

Reuse is a base plus slots::

    # types.yaml
    queue: {badge: queue, meta: ["{{ data.depth }} waiting"]}

or, for a file, Jinja inheritance::

    {# templates/queue.html.j2 #}
    {% extends "node.html" %}

``assets/templates/`` ships ``node.html`` and ``group.html`` (plus
``_sidebar.html``, a fragment for sidebar templates -- sidebars are not types);
templates in the user's own directory shadow them by name. Every type-derived name comes from the *node's own* type, never from the
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
from .parser import EDGE_KEYS

BASES = ASSETS / "templates"

# `<type>.html` works, but `<type>.html.j2` is what editors recognize as Jinja
# (VS Code's Better Jinja maps *.html.j2; PyCharm's Jinja2 file type matches
# *.j2), so `{# #}` comments and tags highlight instead of reading as broken
# HTML. Both are accepted, everywhere.
TEMPLATE_SUFFIXES = (".html", ".html.j2")


class _Loader(FileSystemLoader):
    """FileSystemLoader that also serves declarations' inline ``template:``
    sources, and treats ``x.html`` and ``x.html.j2`` as one name.

    So ``{% extends "node.html" %}`` finds ``node.html.j2`` -- the inheritance
    line stays the same whichever suffix the file on disk wears, or whether the
    thing being extended is a file at all.
    """

    def __init__(self, searchpath):
        super().__init__(searchpath)
        self.inline: dict[str, str] = {}

    def get_source(self, environment, template):
        if template in self.inline:
            return self.inline[template], None, lambda: True
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


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    return [str(value)] if isinstance(value, str) else [str(v) for v in value]


def resolve_type(name: str, types: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    """Flatten a type's inheritance chain into (fields, extra css classes).

    ``extends:`` names another type -- there is no separate "base" concept.
    That inherits its fields (nearest declaration wins), its template, and its
    CSS class, so ``.node--<parent>`` rules apply to the child through the
    ordinary cascade while the child's own ``.node--<child>`` rules override
    them. ``class:`` adds classes without inheriting anything else; ``css:`` is
    not merged, since a child already picks it up via the parent's class.

    Structure needs no ``extends:``: a node with children renders through
    ``group.html`` regardless. Extending ``group`` is how you ask for its look.
    """
    chain: list[str] = []
    seen: set[str] = set()
    cur = name
    while True:
        if cur not in types:
            # Only an error when we got here by following an `extends:` --
            # an undeclared type is simply undeclared, and still renders.
            if chain:
                raise ValueError(
                    f"types.{name}: extends {cur!r}, which is not a declared type"
                )
            break
        if cur in seen:
            raise ValueError(f"types.{name}: extends cycle through {cur!r}")
        seen.add(cur)
        chain.append(cur)
        parent = (types[cur] or {}).get("extends")
        if not parent:
            break
        cur = str(parent)

    fields: dict[str, Any] = {}
    for step in reversed(chain):  # farthest ancestor first, so nearest wins
        fields.update(
            {k: v for k, v in (types[step] or {}).items() if k not in ("class", "css")}
        )
    # The chain itself: the caller renders through the nearest type in it that
    # has a template file, and infers node/group when none does.
    fields["chain"] = chain

    classes: list[str] = []
    for step in reversed(chain[1:]):  # ancestors; the node's own class is added by prerender
        classes.append(f"node--{step}")
        classes += _as_list((types[step] or {}).get("class"))
    classes += _as_list((types.get(name) or {}).get("class"))
    return fields, classes


def type_css(types: dict[str, dict[str, Any]], used: set[str]) -> str:
    """The `css:` blocks of the types in play, as `.node--<type> { ... }` rules.

    Ancestors first, so a child's rules win on source order (both selectors are
    a single class, so specificity can't decide it).
    """
    wanted: set[str] = set()
    for name in used:
        _fields, classes = resolve_type(name, types)
        wanted.add(name)
        wanted.update(c[len("node--"):] for c in classes if c.startswith("node--"))
    rules = []
    for name in sorted(wanted, key=lambda n: (len(resolve_type(n, types)[1]), n)):
        css = (types.get(name) or {}).get("css")
        if not css:
            continue
        css = str(css).strip()
        # Properties get wrapped in the type's selector; a block that already
        # writes its own selectors (`.node--x ul { ... }`) is emitted verbatim,
        # since wrapping it would nest the selector inside itself.
        rules.append(css if "{" in css else f".node--{name} {{ {css} }}")
    return "\n".join(rules)


def is_template_dir(templates: str | Path | None) -> bool:
    """True when ``templates`` points at a Jinja directory rather than a .js file."""
    return templates is not None and Path(templates).is_dir()


def prerender(
    graph: dict[str, Any],
    directory: str | Path | None = None,
    default_sidebar: str | Path | None = None,
) -> tuple[dict[str, Any], str]:
    """Return (graph copy with ``html``/``sidebar``/``classes`` per node, type css).

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
    # Packaged first (node.html, group.html), then the project's, which shadows
    # by name: a `templates/node.html.j2` of yours replaces io-flow's.
    have: dict[str, str] = {}
    for source in (BASES, directory):
        if source is None:
            continue
        for entry in sorted(source.iterdir()):
            key = template_key(entry.name)
            if key is not None:
                have[key] = entry.name

    types = load_types(directory, graph.get("types"))

    # `fields` is a node's own data: everything except the two reserved keys and
    # the relation blocks, which are wiring the viewer already draws as edges.
    # The parser records the document's relation names (`relations:` can add to
    # the built-ins), so a hand-built graph falls back to those built-ins.
    reserved = {"type", "label", *(graph.get("relation_keys") or EDGE_KEYS)}

    # A declaration's `template:` is a whole template written in the YAML. Name
    # it like a file so it can be extended, inherited and shadowed the same way:
    # a project's own `<type>.html` file wins, an inline template beats the
    # packaged one, and `{% extends "<type>.html" %}` finds whichever it is.
    for name, spec in types.items():
        if spec.get("template"):
            env.loader.inline[f"{name}.html"] = str(spec["template"])
            have[name] = f"{name}.html"
    if directory is not None:  # project files shadow inline templates
        for entry in sorted(directory.iterdir()):
            key = template_key(entry.name)
            if key is not None:
                have[key] = entry.name

    def context(node: dict[str, Any], classes: list[str] | None = None) -> dict[str, Any]:
        return {
            "node": node,
            "id": node["id"],
            "type": node["type"],
            "label": node.get("label") or node["id"],
            "data": node.get("data") or {},
            "fields": {
                k: v for k, v in (node.get("data") or {}).items() if k not in reserved
            },
            "parent": node.get("parent"),
            # The whole class attribute the wrapper should carry: `node`, this
            # node's own type, then everything it inherited.
            "classes": " ".join(["node", f"node--{node['type']}", *(classes or [])]),
        }

    def render(name: str, node: dict[str, Any], classes=None, **extra_ctx) -> str:
        try:
            return env.get_template(name).render(**context(node, classes), **extra_ctx)
        except TemplateError as exc:
            raise ValueError(
                f"{name}: {exc.__class__.__name__}: {exc} (rendering node ${node['id']})"
            ) from exc

    def render_source(source: str, node: dict[str, Any], where: str, classes=None,
                      **extra_ctx) -> str:
        """Render an inline Jinja string from a types.yaml declaration."""
        try:
            return env.from_string(source).render(context(node, classes), **extra_ctx)
        except TemplateError as exc:
            raise ValueError(
                f"types.yaml {node['type']}.{where}: {exc.__class__.__name__}: {exc} "
                f"(rendering node ${node['id']})"
            ) from exc

    # Compound-ness is a state, not a type: which base a node gets follows from
    # whether anything is parented to it, unless its declaration says otherwise.
    parents = {n.get("parent") for n in graph["nodes"] if n.get("parent") is not None}

    def slots_for(spec: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
        """A declaration's rendered ``title``/``badge``/``meta``.

        Passed to the bases, and to a type's own template file too, so a file
        extending a base inherits what its declaration already said and
        overrides only the block it cares about.
        """
        slots: dict[str, Any] = {}
        for slot in ("title", "badge"):
            if spec.get(slot):
                slots[slot] = Markup(render_source(spec[slot], node, slot).strip())
        # A meta line that renders blank is dropped -- that is how "show `cli`
        # only when there is one" stays a one-liner instead of a conditional.
        lines = [render_source(m, node, "meta").strip() for m in spec.get("meta") or []]
        slots["meta"] = [Markup(line) for line in lines if line]
        return slots

    def base_template(spec: dict[str, Any], node: dict[str, Any]) -> str:
        """The template a type renders through: the nearest one in its
        inheritance chain that exists, else the shape its children imply."""
        # The node's own type first -- a type with a template file but no
        # declaration has no chain to walk.
        for step in (node["type"], *(spec.get("chain") or [])):
            if step in have:
                return have[step]
        return "group.html" if node["id"] in parents else "node.html"

    def from_declaration(spec: dict[str, Any], node: dict[str, Any], classes) -> str:
        """Render a type through the template it inherits, with `title`/`badge`/
        `meta` filled in and any `blocks:` applied on top."""
        slots = slots_for(spec, node)
        parent = base_template(spec, node)
        blocks = spec.get("blocks") or {}
        if not blocks:
            return render(parent, node, classes, **slots)
        for name in blocks:
            if not str(name).replace("_", "").isalnum():
                raise ValueError(
                    f"types.yaml {node['type']}.blocks: {name!r} is not a block name"
                )
        # `blocks:` replaces a template's block outright, from YAML -- the same
        # {% extends %} + {% block %} child a template file would have been.
        source = f'{{% extends "{parent}" %}}' + "".join(
            f"{{% block {name} %}}{body}{{% endblock %}}" for name, body in blocks.items()
        )
        return render_source(source, node, "blocks", classes, **slots)

    nodes = []
    for node in graph["nodes"]:
        # Body: `<type>.html` file, else the type's declaration. Sidebar:
        # `<type>.sidebar.html` file, else the declaration's `sidebar:`, else a
        # skin's default sidebar template. Every layer is optional; whatever is
        # missing falls through to the packaged templates.js.
        spec, classes = resolve_type(node["type"], types)
        # No declaration is itself a declaration: an empty spec renders through
        # the template its children (or lack of them) imply.
        extra: dict[str, Any] = {"html": from_declaration(spec, node, classes)}
        sidebar = f"{node['type']}.sidebar"
        if sidebar in have:
            extra["sidebar"] = render(have[sidebar], node)
        elif spec.get("sidebar"):
            extra["sidebar"] = render_source(spec["sidebar"], node, "sidebar")
        elif default_sidebar is not None:
            extra["sidebar"] = render(default_sidebar.name, node)
        nodes.append({**node, **extra} if extra else node)
    css = type_css(types, {n["type"] for n in graph["nodes"]})
    return {**graph, "nodes": nodes}, css
