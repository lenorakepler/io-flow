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
renders the base its children call for -- ``_group`` when something is
parented to the node, ``_node`` otherwise -- since compound-ness is a state,
not a type. An ``extends:`` in the declaration overrides that inference.
``<type>.sidebar.html`` -- or a declaration's ``sidebar:`` string -- does the
same for the detail panel, independently: a type may have a body, a sidebar,
both, or neither.

Reuse is a base plus slots::

    # types.yaml
    queue: {badge: queue, meta: ["{{ data.depth }} waiting"]}

or, for a file, Jinja inheritance::

    {# templates/queue.html.j2 #}
    {% extends "_node.html" %}

``assets/templates/`` ships ``_node.html``, ``_group.html`` and
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

    So ``{% extends "_node.html" %}`` finds ``_node.html.j2`` -- the
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


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    return [str(value)] if isinstance(value, str) else [str(v) for v in value]


def resolve_type(name: str, types: dict[str, dict[str, Any]]) -> tuple[dict[str, Any], list[str]]:
    """Flatten a type's inheritance chain into (fields, extra css classes).

    ``extends:`` names either a base template (``_node``/``_group``) or another
    *type*. Naming a type inherits its fields -- nearest declaration wins -- and
    its CSS class, so ``.node--<parent>`` rules apply to the child through the
    ordinary cascade and the child's own ``.node--<child>`` rules override them.
    ``class:`` adds classes without inheriting anything else; ``css:`` is not
    merged, since a child already picks it up via the parent's class.
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
                    f"types.{name}: extends {cur!r}, which is neither a declared "
                    f"type nor a base (bases start with '_')"
                )
            break
        if cur in seen:
            raise ValueError(f"types.{name}: extends cycle through {cur!r}")
        seen.add(cur)
        chain.append(cur)
        parent = (types[cur] or {}).get("extends")
        if not parent or str(parent).startswith("_"):
            break
        cur = str(parent)

    fields: dict[str, Any] = {}
    for step in reversed(chain):  # farthest ancestor first, so nearest wins
        fields.update(
            {k: v for k, v in (types[step] or {}).items() if k not in ("class", "css")}
        )
    # The base is the nearest explicit `_base` in the chain; without one the
    # caller infers it from whether the node has children.
    fields["extends"] = next(
        (
            str(e)
            for step in chain
            if (e := (types[step] or {}).get("extends")) and str(e).startswith("_")
        ),
        None,
    )

    classes: list[str] = []
    for step in reversed(chain[1:]):  # ancestors only; own class comes from the engine
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
        if css:
            rules.append(f".node--{name} {{ {str(css).strip()} }}")
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

    def from_declaration(spec: dict[str, Any], node: dict[str, Any]) -> str:
        """Render a type's declaration: an inline body, or a base plus slots."""
        if spec.get("template"):
            return render_source(spec["template"], node, "template")
        base = spec.get("extends") or ("_group" if node["id"] in parents else "_node")
        slots = slots_for(spec, node)
        blocks = spec.get("blocks") or {}
        if not blocks:
            return render(f"{base}.html", node, **slots)
        # `blocks:` replaces a base's block outright, from YAML -- reaching the
        # slots the sugar doesn't cover (`children`, `_sidebar`'s `rows`) and
        # letting `{{ super() }}` append to the default. Same thing a template
        # file does with {% extends %}, so build exactly that and render it.
        for name in blocks:
            if not str(name).replace("_", "").isalnum():
                raise ValueError(
                    f"types.yaml {node['type']}.blocks: {name!r} is not a block name"
                )
        source = f'{{% extends "{base}.html" %}}' + "".join(
            f"{{% block {name} %}}{body}{{% endblock %}}" for name, body in blocks.items()
        )
        try:
            return env.from_string(source).render(context(node), **slots)
        except TemplateError as exc:
            raise ValueError(
                f"types.yaml {node['type']}.blocks: {exc.__class__.__name__}: {exc} "
                f"(rendering node ${node['id']})"
            ) from exc

    nodes = []
    for node in graph["nodes"]:
        # Body: `<type>.html` file, else the type's declaration. Sidebar:
        # `<type>.sidebar.html` file, else the declaration's `sidebar:`, else a
        # skin's default sidebar template. Every layer is optional; whatever is
        # missing falls through to the packaged templates.js.
        spec, classes = resolve_type(node["type"], types)
        extra: dict[str, Any] = {"classes": classes} if classes else {}
        if node["type"] in have:
            extra["html"] = render(have[node["type"]], node, **slots_for(spec, node))
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
    css = type_css(types, {n["type"] for n in graph["nodes"]})
    return {**graph, "nodes": nodes}, css
