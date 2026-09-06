"""YAML -> normalized recursive graph model.

Grammar: **$name means node, everywhere.** A key starting with ``$`` declares a
node; a ``$``-marked key or string value inside a relation block references
one. Everything else in a node's mapping is a free-form property shown in the
sidebar (and available to templates). One rule covers declaration, nesting,
and reference::

    defaults:
      class: method            # untyped children of a class are methods
    nodes:
      $configfile: {type: file, cli: --config}
      $Config:
        type: class
        loc: src/config.py     # <- not reserved, not $-marked: free data
        $from_yaml:            # <- child node; id "from_yaml"
          args: {path: $configfile}

The output model is a flat list of nodes (each carrying a ``parent`` pointer so
the structure is recursive) plus a flat list of edges::

    {
      "nodes": [{"id", "type", "parent", "label", "data"}, ...],
      "edges": [{"source", "target", "type"?, "label"?}, ...],
    }

Rules:

* **Ids are names.** A node's id is its ``$``-stripped name, and names are
  globally unique -- one flat namespace regardless of nesting. Identity is
  decoupled from location: regrouping a node never changes its id, so
  references (and saved layouts) survive reorganization. When two things
  naturally share a name, pick unique names yourself -- dots carry no
  structural meaning, so ``$Config.run`` and ``$Runner.run`` are just two
  names -- and use ``label:`` for the display name. Labels default to the
  name.
* **Types are free-form.** ``type:`` maps straight to a viewer template +
  ``.node--<type>`` CSS class; no registration anywhere. Untyped nodes get a
  type from the ``defaults:`` block (parent type -> child type, ``_root`` for
  top-level nodes), falling back to what the node structurally is: ``"group"``
  when it holds children, ``"node"`` when it doesn't.
* **References are self-marking.** Inside a relation block, whichever side of
  an entry wears the ``$`` is the reference; the parser never guesses from
  position. Unmarked strings are always literals -- free text can never spawn
  a phantom edge. An unmarked string that *exactly matches* a node id draws an
  ``UnmarkedReferenceWarning`` (a forgotten ``$`` silently drops an edge
  otherwise). Both sides ``$``-marked is an error.
* **The unmarked side of a key-side ref annotates the edge by type.** A
  string is label text (``calls: {$plot: "make figures"}``), a number is a
  flow weight (``calls: {$plot: 42}``) that the viewer renders as stroke
  width (see the ``diagram: edgeWidth:`` block). Explicit ``edges:`` entries
  take an optional numeric ``weight:`` alongside ``type``/``label``.
* **Explicit ``edges:`` lists may live at top level or inside any node.**
  Inside a node, an omitted ``from``/``to`` defaults to the declaring node.
  Placement is organization only and never changes meaning: references are
  always global names. (``edges`` is therefore a reserved key in node
  mappings.)
* **``steps:`` is a list of children whose position is their identity.** The
  id is the parent's plus the index (``$stages2``) and the index rides along
  as ``number`` in the node's data, so an ordered pipeline needs no name per
  stage. Items are ordinary node specs (a bare string is its label); untyped
  ones default to ``step``. Reordering renumbers -- that is the trade.
  ``autoedges:`` beside the list chains each step to the next (``true`` types
  them ``next``; a string names the type).
* **Two-pass.** Every node id is collected first, then references are
  resolved, so forward references work regardless of document order.
* Unresolved ``$refs`` emit a loud ``UnresolvedReferenceWarning`` listing
  close candidates -- a plausible-but-wrong diagram is worse than a noisy one.

Extending the vocabulary (none of it touches this module):

* New **node types** are free-form ``type:`` values (+ optional template/CSS).
* New **containers** are just nodes with ``$``-children; compound-ness is a
  state, not a type.
* New **edge semantics** are one entry in the document's ``relations:`` block
  (or, for built-ins, ``EDGE_KEYS`` below). Because references self-mark,
  a relation declares only its ``direction``.

The ``children:``-fence grammar this replaced is documented in
GRAMMAR_ALTERNATIVES.md, including a revert recipe.
"""

from __future__ import annotations

import difflib
import warnings
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from .emit import SKIN_SUFFIXES

SIGIL = "$"
DEFAULT_TYPE = "node"


class DuplicateNodeError(ValueError):
    """Raised when two nodes would share the same name (names are global)."""


class UnresolvedReferenceWarning(UserWarning):
    """A ``$``-marked reference did not match any known node id."""


class UnmarkedReferenceWarning(UserWarning):
    """An unmarked literal in a relation block exactly matches a node id."""


# Built-in relation kinds: name -> direction.
#
# "in":  data flows from the referenced node INTO the owner
#        (edge source = referenced id, target = owner).
# "out": the owner points AT the referenced node
#        (edge source = owner, target = referenced id).
#
# Because references are $-marked, a relation needs no "key or value?" axis:
# whichever side of an entry wears the $ is the reference; the unmarked side
# is a literal (arg name, label text, or default value).
#
# The relation name doubles as the edge's ``type`` tag, which the viewer
# exposes as an ``edge--<type>`` CSS class.
EDGE_KEYS: dict[str, str] = {
    "args": "in",
    "calls": "out",
    "returns": "out",
}

# Box faces an edge endpoint may be pinned to (``anchor:`` blocks).
ANCHOR_SIDES = ("left", "right", "top", "bottom")


def _anchor_spec(value: Any, where: str) -> dict[str, str]:
    """Validate ``anchor: {from: side, to: side}`` (both ends optional).

    ``from``/``to`` name the *rendered edge's* source and target endpoint,
    matching the keys of explicit edges; sides are box faces. An undeclared
    end keeps the viewer's automatic (dominant-axis) choice.
    """
    if not isinstance(value, dict):
        raise ValueError(
            f"{where}: anchor must be a mapping like {{from: bottom, to: top}}"
        )
    unknown = set(value) - {"from", "to"}
    if unknown:
        raise ValueError(
            f"{where}: unknown anchor key(s) {', '.join(sorted(map(str, unknown)))}; "
            f"expected 'from' and/or 'to'"
        )
    out: dict[str, str] = {}
    for end in ("from", "to"):
        side = value.get(end)
        if side is None:
            continue
        side = str(side)
        if side not in ANCHOR_SIDES:
            raise ValueError(
                f"{where}: anchor {end} must be one of {', '.join(ANCHOR_SIDES)}, "
                f"got {side!r}"
            )
        out[end] = side
    if not out:
        raise ValueError(f"{where}: anchor declares neither 'from' nor 'to'")
    return out


def _edge_keys_for(data: dict[str, Any]) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Built-in EDGE_KEYS plus any registered in the document's ``relations:``.

    A diagram can declare new relationship kinds without touching this module::

        relations:
          emits:    {direction: out}
          reads:    {direction: in}
          inherits: {direction: out, anchor: {from: top, to: bottom}}

    Each registered name becomes usable on any node exactly like ``calls:``,
    tags its edges with ``type: <name>`` (so ``edge--<name>`` is stylable from
    CSS), and follows the same resolve/warn rules. An ``anchor:`` on the
    relation is stamped onto every edge it derives (re-registering a built-in
    name works, so ``calls`` can carry a default anchor too). Returns
    ``(name -> direction, name -> anchor spec)``.
    """
    keys = dict(EDGE_KEYS)
    anchors: dict[str, dict[str, str]] = {}
    for name, spec in (data.get("relations", {}) or {}).items():
        spec = spec or {}
        if "ref" in spec:
            raise ValueError(
                f"relations.{name}: 'ref' is obsolete -- references are "
                f"$-marked, so either side of an entry may hold the reference"
            )
        direction = str(spec.get("direction", "out"))
        if direction not in ("in", "out"):
            raise ValueError(
                f"relations.{name}: direction must be 'in' or 'out', got {direction!r}"
            )
        keys[str(name)] = direction
        if spec.get("anchor") is not None:
            anchors[str(name)] = _anchor_spec(spec["anchor"], f"relations.{name}")
    return keys, anchors


def parse_file(path: str | Path) -> dict[str, Any]:
    """Parse a YAML file at ``path`` into the graph model."""
    path = Path(path)
    yaml = YAML(typ="safe")
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.load(fh)
    graph = parse(data or {})
    # Default the HTML title to the source filename; an explicit YAML
    # ``title:`` (set in parse()) takes precedence.
    graph.setdefault("title", f"io-flow: {path.stem}")
    # Resolve style: paths relative to the YAML's directory (not the CWD), so
    # `io-flow edit` run from anywhere finds them. `~` expands; absolute paths
    # pass through. A skin entry without a .css/.js suffix is a bundled name,
    # not a path, and is left alone.
    style = graph.get("style")
    if style:
        def _resolve(val: str) -> str:
            p = Path(val).expanduser()
            return str(p if p.is_absolute() else path.parent / p)

        for key in ("css", "templates"):
            if style.get(key):
                style[key] = _resolve(style[key])
        if style.get("skin"):
            style["skin"] = [
                _resolve(s) if Path(s).suffix in SKIN_SUFFIXES else s
                for s in style["skin"]
            ]
    return graph


def _strip(ref: str) -> str:
    return ref[len(SIGIL) :]


def parse(data: dict[str, Any]) -> dict[str, Any]:
    """Parse an already-loaded YAML mapping into the graph model."""
    nodes: list[dict[str, Any]] = []
    seen: set[str] = set()

    edge_keys, relation_anchors = _edge_keys_for(data)

    defaults = data.get("defaults", {}) or {}
    if not isinstance(defaults, dict):
        raise ValueError(f"defaults: must be a mapping of parent type -> child type")

    def default_type(parent_type: str | None, fallback: str = DEFAULT_TYPE) -> str:
        key = parent_type if parent_type is not None else "_root"
        return str(defaults.get(key, fallback))

    # Reference sites recorded during the walk and resolved in pass 2.
    # Each entry: (owner_node_id, edge_type, ref, annotation, context_key)
    # where `annotation` is the unmarked side of a key-side ref (str = label,
    # number = weight) and `context_key` only serves warning messages for
    # value-side refs.
    sites: list[tuple[str, str, str, Any, str | None]] = []
    # Unmarked strings in relation blocks, checked in pass 2 against node ids
    # (a forgotten $ silently drops an edge; make that loud).
    literals: list[tuple[str, str, str]] = []  # (owner, edge_type, text)
    # Explicit `edges:` entries, top-level (owner None) or declared inside a
    # node (owner = that node's id, filling an omitted from/to endpoint).
    explicit: list[tuple[str | None, Any]] = []

    def record_explicit(owner: str | None, block: Any) -> None:
        where = f"on {SIGIL}{owner}" if owner else "at top level"
        if not isinstance(block, list):
            raise ValueError(f"edges: {where} must be a list of edge mappings")
        for espec in block:
            explicit.append((owner, espec))

    def record_edges(node_id: str, spec: dict[str, Any]) -> None:
        """Queue every relation-block entry on ``spec`` for pass 2."""
        for edge_type in edge_keys:
            for key, value in (spec.get(edge_type, {}) or {}).items():
                key = str(key)
                key_ref = key.startswith(SIGIL)
                value_ref = isinstance(value, str) and value.startswith(SIGIL)
                if key_ref and value_ref:
                    raise ValueError(
                        f"{edge_type} entry {key}: {value} on {SIGIL}{node_id}: both "
                        f"sides are $-marked; exactly one side may be the reference"
                    )
                if key_ref:
                    # Unmarked value annotates the edge: a string is label
                    # text ("" = none), a number is a flow weight.
                    sites.append((node_id, edge_type, _strip(key), value, None))
                elif value_ref:
                    # Unmarked key is a name for the connection (arg name).
                    sites.append((node_id, edge_type, _strip(value), None, key))
                else:
                    # Pure literal entry (e.g. a default value); no edge. Pass 2
                    # warns if either side exactly matches a node id.
                    literals.append((node_id, edge_type, key))
                    if isinstance(value, str):
                        literals.append((node_id, edge_type, value))

    def add_node(
        name: str,
        spec: Any,
        parent_id: str | None,
        parent_type: str | None,
        fallback_type: str = DEFAULT_TYPE,
    ) -> None:
        if not name:
            raise ValueError(
                f"invalid node name {SIGIL!r}"
                + (" under " + parent_id if parent_id else "")
                + ": names must be non-empty"
            )
        spec = spec or {}
        if not isinstance(spec, dict):
            raise ValueError(f"node {SIGIL}{name}: spec must be a mapping, got {spec!r}")
        # The name IS the id: one flat, global namespace. Nesting sets the
        # `parent` pointer only, so regrouping never changes identity.
        node_id = name
        if node_id in seen:
            raise DuplicateNodeError(
                f"duplicate node name {SIGIL}{node_id}: names are global, even "
                f"inside different parents. Rename one (dots are fine, e.g. "
                f"{SIGIL}Config.{node_id}) and set 'label: {node_id}' to keep "
                f"the display name."
            )
        seen.add(node_id)

        label = spec.get("label")
        children = {k: v for k, v in spec.items() if str(k).startswith(SIGIL)}
        # An untyped node falls back to what it structurally *is*: `group` when
        # it holds children, `node` when it doesn't. It renders through
        # group.html either way -- compound-ness is a state -- but carrying the
        # type means `.node--group` styling applies too. A `defaults:` entry
        # still wins, as does the `step` fallback inside a `steps:` list.
        if fallback_type == DEFAULT_TYPE and (children or spec.get("steps")):
            fallback_type = "group"
        node_type = (
            str(spec["type"]) if spec.get("type") is not None
            else default_type(parent_type, fallback_type)
        )
        # `edges` is reserved inside a node: a locally-declared explicit-edge
        # list (an omitted from/to defaults to this node), not sidebar data.
        if "edges" in spec:
            record_explicit(node_id, spec["edges"])
        node_data = {
            str(k): v
            for k, v in spec.items()
            if not str(k).startswith(SIGIL) and k not in ("edges", "steps", "autoedges")
        }
        nodes.append(
            {
                "id": node_id,
                "type": node_type,
                "parent": parent_id,
                # label defaults to the name; the name stays the unique,
                # addressable key.
                "label": label if label is not None else name,
                "data": _plain(node_data),
            }
        )
        record_edges(node_id, spec)
        # `steps:` is a list of children whose position is their identity: the
        # id is the parent's plus the index, so `$stages2` addresses the third
        # one, and `number` carries that index into templates. An item is an
        # ordinary node spec otherwise -- it can carry $children, edges, its own
        # type, or override `number` for display without moving its id.
        steps = spec.get("steps")
        auto = spec.get("autoedges")
        if steps is not None:
            if not isinstance(steps, list):
                raise ValueError(
                    f"{SIGIL}{node_id}.steps: must be a list of step mappings, got {steps!r}"
                )
            for i, step in enumerate(steps):
                if isinstance(step, str):  # bare string: the step's label
                    step = {"label": step}
                add_node(f"{node_id}{i}", {"number": i, **(step or {})}, node_id, node_type, "step")
            # `autoedges:` draws the chain the order already implies: each step
            # to the next one. A string names the edge type (`.edge--<type>`);
            # `true` uses `next`. Steps stay free to declare edges of their own.
            if auto:
                record_explicit(node_id, [
                    {
                        "from": f"{SIGIL}{node_id}{i}",
                        "to": f"{SIGIL}{node_id}{i + 1}",
                        "type": auto if isinstance(auto, str) else "next",
                    }
                    for i in range(len(steps) - 1)
                ])
        elif auto:
            raise ValueError(
                f"{SIGIL}{node_id}.autoedges: only means something beside a `steps:` "
                f"list -- there is no order to chain without one"
            )
        for child_key, child_spec in children.items():
            add_node(_strip(str(child_key)), child_spec, node_id, node_type)

    for key, spec in (data.get("nodes", {}) or {}).items():
        key = str(key)
        if not key.startswith(SIGIL):
            raise ValueError(
                f"nodes.{key}: top-level entries under nodes: must be node "
                f"declarations ({SIGIL}{key}); there is no node to attach data to"
            )
        add_node(_strip(key), spec, None, None)

    # --- Pass 2: resolve reference sites into edges ---------------------------
    node_ids = set(seen)
    edges: list[dict[str, str]] = []

    def _warn_unresolved(ref: str, detail: str) -> None:
        candidates = difflib.get_close_matches(ref, node_ids, n=5, cutoff=0.4)
        hint = f" Did you mean: {', '.join(SIGIL + c for c in candidates)}?" if candidates else ""
        warnings.warn(
            f"unresolved reference {SIGIL}{ref} {detail} (no node with that id).{hint}",
            UnresolvedReferenceWarning,
            stacklevel=3,
        )

    for owner, edge_type, ref, annotation, context_key in sites:
        if ref not in node_ids:
            where = f"for {owner}.{context_key}" if context_key else f"({edge_type}) from {owner}"
            _warn_unresolved(ref, where)
            continue
        direction = edge_keys[edge_type]
        source, target = (ref, owner) if direction == "in" else (owner, ref)
        edge: dict[str, Any] = {"source": source, "target": target, "type": edge_type}
        if isinstance(annotation, bool):
            pass  # a bool is a literal default value, not a label or weight
        elif isinstance(annotation, (int, float)):
            edge["weight"] = annotation
        elif isinstance(annotation, str) and annotation:
            edge["label"] = annotation
        if edge_type in relation_anchors:
            edge["anchor"] = relation_anchors[edge_type]
        edges.append(edge)

    for owner, edge_type, text in literals:
        if text in node_ids:
            warnings.warn(
                f"literal {text!r} in {edge_type} of {owner} exactly matches node "
                f"{SIGIL}{text} but is unmarked, so no edge was made. Write "
                f"{SIGIL}{text} if you meant a reference (ignore this if it is "
                f"just a name or literal value).",
                UnmarkedReferenceWarning,
                stacklevel=2,
            )

    # --- Pass 2b: explicit edges ----------------------------------------------
    # A direct alternative to deriving edges from relation blocks:
    #   edges:
    #     - {from: $a, to: $b, type: calls, label: "..."}
    # `from`/`to` are $-marked node refs (direction as written); `type` is a
    # free tag (conventionally a relation name); `label` is optional. The list
    # may live at top level or inside a node, where an omitted from/to
    # defaults to the declaring node. Placement never changes meaning: refs
    # are always global names.
    if data.get("edges") is not None:
        record_explicit(None, data["edges"])
    for owner, spec in explicit:
        spec = _plain(spec) or {}
        source = spec.get("from")
        dest = spec.get("to")
        if owner is None and (not source or not dest):
            raise ValueError(
                f"explicit edge {spec!r} must have both 'from' and 'to' node "
                f"references (only edges declared inside a node may omit one)"
            )
        if not source and not dest:
            raise ValueError(
                f"edge {spec!r} on {SIGIL}{owner}: at least one of 'from'/'to' "
                f"is required (the omitted side defaults to the declaring node)"
            )
        unmarked = [str(r) for r in (source, dest) if r is not None and not str(r).startswith(SIGIL)]
        if unmarked:
            raise ValueError(
                f"explicit edge {spec!r}: from/to are node references "
                f"and must be $-marked ({', '.join(SIGIL + u for u in unmarked)})"
            )
        source = _strip(str(source)) if source is not None else owner
        dest = _strip(str(dest)) if dest is not None else owner
        missing = [nid for nid in (source, dest) if nid not in node_ids]
        if missing:
            for nid in missing:
                _warn_unresolved(nid, f"in {SIGIL}{source} -> {SIGIL}{dest}")
            continue
        edge = {"source": source, "target": dest}
        if spec.get("type") is not None:
            edge["type"] = str(spec["type"])
        label = spec.get("label")
        if isinstance(label, str) and label:
            edge["label"] = label
        weight = spec.get("weight")
        if weight is not None:
            if isinstance(weight, bool) or not isinstance(weight, (int, float)):
                raise ValueError(
                    f"explicit edge {spec!r}: weight must be a number, got {weight!r}"
                )
            edge["weight"] = weight
        # Endpoint pinning: an explicit anchor wins; otherwise a typed edge
        # inherits its relation's default anchor, so explicit `inherits`
        # entries render like derived ones.
        if spec.get("anchor") is not None:
            edge["anchor"] = _anchor_spec(spec["anchor"], f"explicit edge {spec!r}")
        elif edge.get("type") in relation_anchors:
            edge["anchor"] = relation_anchors[edge["type"]]
        edges.append(edge)

    # --- Pass 2c: dedupe --------------------------------------------------------
    # An explicit edge repeating a derived one would render as two stacked
    # paths. Same (source, target) with *different* types is meaningful (a
    # calls b AND returns to b) and is kept.
    unique: list[dict[str, str]] = []
    seen_edges: set[tuple] = set()
    for edge in edges:
        key = (
            edge["source"],
            edge["target"],
            edge.get("type"),
            edge.get("label"),
            edge.get("weight"),
        )
        if key in seen_edges:
            continue
        seen_edges.add(key)
        unique.append(edge)

    graph: dict[str, Any] = {"nodes": nodes, "edges": unique}
    # Which node keys were relation blocks rather than free data -- built-ins
    # plus anything `relations:` registered. Templates use it (as `fields`) to
    # list a node's own data without the wiring; build-time only.
    graph["relation_keys"] = sorted(edge_keys)
    title = data.get("title")
    if isinstance(title, str) and title.strip():
        graph["title"] = title.strip()
    # Optional per-diagram layout config, passed through verbatim for the
    # viewer's layout engine (direction / algorithm / spacing / raw elk map).
    diagram = data.get("diagram")
    if isinstance(diagram, dict):
        graph["diagram"] = _plain(diagram)
    # Optional per-diagram styling: `skin` entries layered on top and/or
    # project-local `css`/`templates` files replacing the packaged assets. Same
    # knobs as the CLI's --skin/--css/--templates, so a diagram can carry its
    # own look; a CLI flag still overrides. Paths are resolved relative to the
    # YAML file in parse_file (parse() alone has no file to resolve against).
    # Not passed to the viewer -- consumed by emit at build time.
    # Optional per-diagram node type declarations, same shape as a project's
    # templates/types.yaml (see jinja_templates): {type: {extends/title/badge/
    # meta/template/sidebar}}. Merged over the packaged and project ones at
    # build time, so a diagram can describe a type it alone uses without a
    # template file anywhere. Declaring is never *required* -- an undeclared
    # type still renders. Build-time only; not passed to the viewer.
    types = data.get("types")
    if types is not None:
        if not isinstance(types, dict):
            raise ValueError("types: must be a mapping of type name -> declaration")
        bad = [k for k, v in types.items() if not isinstance(v, dict)]
        if bad:
            raise ValueError(
                f"types.{bad[0]}: must be a mapping "
                f"(extends/title/badge/meta/template/sidebar)"
            )
        graph["types"] = {str(k): _plain(v) for k, v in types.items()}

    style = data.get("style")
    if style is not None:
        if not isinstance(style, dict):
            raise ValueError("style: must be a mapping of css/templates/skin")
        unknown = set(map(str, style)) - {"css", "templates", "skin"}
        if unknown:
            raise ValueError(
                f"style: unknown key(s) {', '.join(sorted(unknown))}; "
                f"expected css, templates, skin"
            )
        style_out = {k: str(style[k]) for k in ("css", "templates") if style.get(k) is not None}
        # skin: one entry or a list, layered in order. A bare name is a bundled
        # skin; an entry ending .css/.js is a project-local file (see
        # emit.skin_assets).
        skin = style.get("skin")
        if skin is not None:
            if isinstance(skin, str):
                skin = [skin]
            if not isinstance(skin, list) or not all(isinstance(x, str) for x in skin):
                raise ValueError(
                    "style.skin: must be a skin name/file or a list of them"
                )
            if skin:
                style_out["skin"] = list(skin)
        if style_out:
            graph["style"] = style_out
    return graph


def _plain(value: Any) -> Any:
    """Recursively convert ruamel containers into plain dict/list/scalars."""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value
