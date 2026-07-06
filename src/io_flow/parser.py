"""YAML -> normalized recursive graph model.

The model is a flat list of nodes (each carrying a ``parent`` pointer so the
structure is recursive from day one) plus a flat list of edges::

    {
      "nodes": [{"id", "type", "parent", "data"}, ...],
      "edges": [{"source", "target"}, ...],
    }

Edge derivation is deliberately conservative (see PLAN.md §3.1):

* **Two-pass.** Every node id is collected first, then references are resolved,
  so forward references work regardless of document order.
* References are only looked for in a **whitelist** of positions -- class
  ``attributes:`` values and method/function ``args:`` values. ``value:``,
  ``cli:`` and ``description:`` are never scanned, so their free text can never
  spawn a phantom edge.
* Matches are **exact** against the set of collected node ids.
* **Duplicate ids are a hard error** (``DuplicateNodeError``).
* Unresolved references emit a loud ``UnresolvedReferenceWarning`` that lists
  close candidates -- a plausible-but-wrong diagram is worse than a noisy one.
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


def parse_file(path: str | Path) -> dict[str, Any]:
    """Parse a YAML file at ``path`` into the graph model."""
    yaml = YAML(typ="safe")
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.load(fh)
    return parse(data or {})


def parse(data: dict[str, Any]) -> dict[str, Any]:
    """Parse an already-loaded YAML mapping into the graph model."""
    nodes: list[dict[str, Any]] = []
    seen: set[str] = set()

    # Reference sites recorded during the first pass and resolved in the second.
    # Each entry: (target_node_id, ref_key, ref_value)
    ref_sites: list[tuple[str, str, Any]] = []

    def add_node(node_id: str, node_type: str, parent: str | None, node_data: Any) -> None:
        if node_id in seen:
            raise DuplicateNodeError(
                f"duplicate node id {node_id!r}: node ids (including qualified "
                f"class members like 'Config.from_yaml') must be unique"
            )
        seen.add(node_id)
        nodes.append(
            {
                "id": node_id,
                "type": node_type,
                "parent": parent,
                "data": _plain(node_data) if node_data is not None else {},
            }
        )

    top = data.get("nodes", {}) or {}

    # --- Pass 1a: input nodes (files / options / parameters / ...) ------------
    for name, spec in (top.get("input", {}) or {}).items():
        spec = spec or {}
        node_type = spec.get("type", "input")
        add_node(name, node_type, None, spec)

    # --- Pass 1b: classes (compound parents) + their children -----------------
    for cname, cspec in (top.get("classes", {}) or {}).items():
        cspec = cspec or {}
        class_data = {k: v for k, v in cspec.items() if k not in ("attributes", "methods")}
        add_node(cname, "class", None, class_data)

        attributes = cspec.get("attributes")
        if attributes is not None:
            attr_id = f"{cname}.attributes"
            add_node(attr_id, "attributes", cname, attributes)
            for key, value in (attributes or {}).items():
                ref_sites.append((attr_id, key, value))

        for mname, mspec in (cspec.get("methods", {}) or {}).items():
            mspec = mspec or {}
            mid = f"{cname}.{mname}"
            add_node(mid, "method", cname, mspec)
            for key, value in (mspec.get("args", {}) or {}).items():
                ref_sites.append((mid, key, value))

    # --- Pass 1c: functions ---------------------------------------------------
    for fname, fspec in (top.get("functions", {}) or {}).items():
        fspec = fspec or {}
        add_node(fname, "function", None, fspec)
        for key, value in (fspec.get("args", {}) or {}).items():
            ref_sites.append((fname, key, value))

    # --- Pass 2: resolve references into edges --------------------------------
    node_ids = set(seen)
    edges: list[dict[str, str]] = []
    for target, key, value in ref_sites:
        # Only strings can name a node. Non-strings (numbers, bools) in an arg
        # position are literal defaults, not references -- skip silently.
        if not isinstance(value, str):
            continue
        if value in node_ids:
            edges.append({"source": value, "target": target})
        else:
            candidates = difflib.get_close_matches(value, node_ids, n=5, cutoff=0.4)
            hint = f" Did you mean: {', '.join(candidates)}?" if candidates else ""
            warnings.warn(
                f"unresolved reference {value!r} for {target}.{key} "
                f"(no node with that id).{hint}",
                UnresolvedReferenceWarning,
                stacklevel=2,
            )

    return {"nodes": nodes, "edges": edges}


def _plain(value: Any) -> Any:
    """Recursively convert ruamel containers into plain dict/list/scalars."""
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(v) for v in value]
    return value
