"""YAML -> normalized recursive graph model.

The model is a flat list of nodes (each carrying a ``parent`` pointer so the
structure is recursive from day one) plus a flat list of edges::

    {
      "nodes": [{"id", "type", "parent", "label", "data"}, ...],
      "edges": [{"source", "target", "type"?, "label"?}, ...],
    }

Edge derivation is deliberately conservative (see PLAN.md §3.1):

* **Two-pass.** Every node id is collected first, then references are resolved,
  so forward references work regardless of document order.
* References are only looked for in a **registry** of positions (``EDGE_KEYS``
  below, plus class ``attributes:`` values). ``value:``, ``cli:`` and
  ``description:`` are never scanned, so their free text can never spawn a
  phantom edge.
* Matches are **exact** against the set of collected node ids.
* **Duplicate ids are a hard error** (``DuplicateNodeError``).
* Unresolved references emit a loud ``UnresolvedReferenceWarning`` that lists
  close candidates -- a plausible-but-wrong diagram is worse than a noisy one.

Extending the vocabulary:

* New **edge semantics** ("reads", "emits", ...) are one entry in ``EDGE_KEYS``.
* New **nestable containers** are one entry in ``MEMBER_KEYS`` (plus a template
  + CSS rule on the viewer side).
* New **input node types** need no parser change at all -- ``type:`` on an
  input entry is free-form and maps straight to a template/CSS class.
"""

from __future__ import annotations

import difflib
import warnings
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML


class DuplicateNodeError(ValueError):
    """Raised when two nodes would share the same (possibly qualified) id."""


class UnresolvedReferenceWarning(UserWarning):
    """A value in a reference position did not match any known node id."""


# Reference-position registry: spec key -> (direction, ref_position).
#
# direction  "in":  data flows from the referenced node INTO the owner
#                   (edge source = referenced id, target = owner).
#            "out": the owner points AT the referenced node
#                   (edge source = owner, target = referenced id).
# ref_pos    "value": the entry's *values* are the references (keys are arg
#                     names; non-string values are literal defaults, skipped
#                     silently).
#            "key":   the entry's *keys* are the references (values are
#                     optional edge-label text; "" means no label).
#
# The spec key doubles as the edge's ``type`` tag, which the viewer exposes as
# an ``edge--<type>`` CSS class.
EDGE_KEYS: dict[str, tuple[str, str]] = {
    "args": ("in", "value"),
    "calls": ("out", "key"),
    "returns": ("out", "key"),
}


def _edge_keys_for(data: dict[str, Any]) -> dict[str, tuple[str, str]]:
    """Built-in EDGE_KEYS plus any registered in the document's ``relations:``.

    A diagram can declare new relationship kinds without touching this module::

        relations:
          emits:  {direction: out}            # ref: key is the default
          reads:  {direction: in, ref: value}

    Each registered name becomes usable on any function/method/group exactly
    like ``calls:``, tags its edges with ``type: <name>`` (so ``edge--<name>``
    is stylable from CSS), and follows the same resolve/warn rules.
    """
    keys = dict(EDGE_KEYS)
    for name, spec in (data.get("relations", {}) or {}).items():
        spec = spec or {}
        direction = str(spec.get("direction", "out"))
        ref = str(spec.get("ref", "key"))
        if direction not in ("in", "out"):
            raise ValueError(
                f"relations.{name}: direction must be 'in' or 'out', got {direction!r}"
            )
        if ref not in ("key", "value"):
            raise ValueError(f"relations.{name}: ref must be 'key' or 'value', got {ref!r}")
        keys[str(name)] = (direction, ref)
    return keys


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
    return graph


def parse(data: dict[str, Any]) -> dict[str, Any]:
    """Parse an already-loaded YAML mapping into the graph model."""
    nodes: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Reference sites recorded during the first pass and resolved in the
    # second. Each entry: (owner_node_id, edge_type, ref, label, context_key)
    # where `context_key` only serves the warning message for "value" refs.
    sites: list[tuple[str, str, Any, Any, str | None]] = []

    def add_node(
        node_id: str,
        node_type: str,
        parent: str | None,
        node_data: Any,
        label: str | None = None,
    ) -> None:
        if node_id in seen:
            raise DuplicateNodeError(
                f"duplicate node id {node_id!r}: node ids (including qualified "
                f"class members like 'Config.from_yaml') must be unique"
            )
        seen.add(node_id)
        # `id` stays the unique, addressable key; `label` is the display name and
        # defaults to it (methods show only their short, unqualified name).
        if label is None:
            label = node_id.split(".")[-1] if node_type == "method" else node_id
        nodes.append(
            {
                "id": node_id,
                "type": node_type,
                "parent": parent,
                "label": label,
                "data": _plain(node_data) if node_data is not None else {},
            }
        )

    top = data.get("nodes", {}) or {}
    edge_keys = _edge_keys_for(data)

    def record_edges(node_id: str, spec: dict[str, Any]) -> None:
        """Queue every edge-key position on ``spec`` for resolution in pass 2."""
        for edge_type, (_direction, ref_pos) in edge_keys.items():
            for key, value in (spec.get(edge_type, {}) or {}).items():
                if ref_pos == "value":
                    sites.append((node_id, edge_type, value, None, str(key)))
                else:
                    sites.append((node_id, edge_type, str(key), value, None))

    def add_function(fname: str, fspec: Any, parent: str | None) -> None:
        fspec = fspec or {}
        add_node(fname, "function", parent, fspec, label=fspec.get("label"))
        record_edges(fname, fspec)

    def add_class(cname: str, cspec: Any, parent: str | None) -> None:
        cspec = cspec or {}
        class_data = {k: v for k, v in cspec.items() if k not in ("attributes", "methods")}
        add_node(cname, "class", parent, class_data, label=cspec.get("label"))

        attributes = cspec.get("attributes")
        if attributes is not None:
            attr_id = f"{cname}.attributes"
            add_node(attr_id, "attributes", cname, attributes)
            # Attribute values are "in" references, same semantics as args.
            for key, value in (attributes or {}).items():
                sites.append((attr_id, "args", value, None, str(key)))

        for mname, mspec in (cspec.get("methods", {}) or {}).items():
            mspec = mspec or {}
            mid = f"{cname}.{mname}"
            add_node(mid, "method", cname, mspec, label=mspec.get("label"))
            record_edges(mid, mspec)

    def add_group(gname: str, gspec: Any, parent: str | None) -> None:
        gspec = gspec or {}
        group_data = {k: v for k, v in gspec.items() if k not in MEMBER_KEYS}
        add_node(gname, "group", parent, group_data, label=gspec.get("label"))
        # A group may itself participate in edges ("sometimes a function itself").
        record_edges(gname, gspec)
        add_members(gspec, gname)

    # Nestable-member registry: section key under a container -> adder. Adding
    # a new container/member kind is one entry here (+ template & CSS).
    MEMBER_KEYS: dict[str, Any] = {
        "classes": add_class,
        "functions": add_function,
        "groups": add_group,
    }

    def add_members(container: dict[str, Any], parent: str | None) -> None:
        """Add the members nested directly under ``container``."""
        for section, adder in MEMBER_KEYS.items():
            for name, spec in (container.get(section, {}) or {}).items():
                adder(name, spec, parent)

    # --- Pass 1a: input nodes (files / options / parameters / ...) ------------
    for name, spec in (top.get("input", {}) or {}).items():
        spec = spec or {}
        node_type = spec.get("type", "input")
        add_node(name, node_type, None, spec, label=spec.get("label"))

    # --- Pass 1b: classes / functions / groups (recursive compounds) ----------
    add_members(top, None)

    # --- Pass 2: resolve reference sites into edges ---------------------------
    node_ids = set(seen)
    edges: list[dict[str, str]] = []

    def _warn_unresolved(ref: str, detail: str) -> None:
        candidates = difflib.get_close_matches(ref, node_ids, n=5, cutoff=0.4)
        hint = f" Did you mean: {', '.join(candidates)}?" if candidates else ""
        warnings.warn(
            f"unresolved reference {ref!r} {detail} (no node with that id).{hint}",
            UnresolvedReferenceWarning,
            stacklevel=3,
        )

    for owner, edge_type, ref, label, context_key in sites:
        direction, ref_pos = edge_keys[edge_type]
        # Only strings can name a node. Non-strings (numbers, bools) in a
        # value-ref position are literal defaults, not references -- skip
        # silently.
        if not isinstance(ref, str):
            continue
        if ref not in node_ids:
            where = f"for {owner}.{context_key}" if context_key else f"({edge_type}) from {owner}"
            _warn_unresolved(ref, where)
            continue
        source, target = (ref, owner) if direction == "in" else (owner, ref)
        edge: dict[str, str] = {"source": source, "target": target, "type": edge_type}
        if isinstance(label, str) and label:
            edge["label"] = label
        edges.append(edge)

    # --- Pass 2b: explicit top-level edges ------------------------------------
    # A direct alternative to deriving edges from EDGE_KEYS positions:
    #   edges:
    #     - {from: a, to: b, type: calls, label: "..."}
    # `from`/`to` are node ids (direction as written); `type` is a free tag
    # (conventionally an EDGE_KEYS name); `label` is optional.
    for spec in data.get("edges") or []:
        spec = _plain(spec) or {}
        source = spec.get("from")
        dest = spec.get("to")
        if not source or not dest:
            raise ValueError(
                f"explicit edge {spec!r} must have both 'from' and 'to' node ids"
            )
        missing = [nid for nid in (source, dest) if nid not in node_ids]
        if missing:
            for nid in missing:
                _warn_unresolved(nid, f"in {source} -> {dest}")
            continue
        edge = {"source": source, "target": dest}
        if spec.get("type") is not None:
            edge["type"] = str(spec["type"])
        label = spec.get("label")
        if isinstance(label, str) and label:
            edge["label"] = label
        edges.append(edge)

    # --- Pass 2c: dedupe --------------------------------------------------------
    # An explicit edge repeating a derived one would render as two stacked
    # paths. Same (source, target) with *different* types is meaningful (a
    # calls b AND returns to b) and is kept.
    unique: list[dict[str, str]] = []
    seen_edges: set[tuple] = set()
    for edge in edges:
        key = (edge["source"], edge["target"], edge.get("type"), edge.get("label"))
        if key in seen_edges:
            continue
        seen_edges.add(key)
        unique.append(edge)

    graph: dict[str, Any] = {"nodes": nodes, "edges": unique}
    title = data.get("title")
    if isinstance(title, str) and title.strip():
        graph["title"] = title.strip()
    # Optional per-diagram layout config, passed through verbatim for the
    # viewer's layout engine (direction / algorithm / spacing / raw elk map).
    diagram = data.get("diagram")
    if isinstance(diagram, dict):
        graph["diagram"] = _plain(diagram)
    return graph


def _plain(value: Any) -> Any:
    """Recursively convert ruamel containers into plain dict/list/scalars."""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value
