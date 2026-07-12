"""Append browser-created connections to the YAML's top-level ``edges:`` list.

The in-browser "Connect" mode is **append-only by design**: it can add
explicit edges but never delete or rewrite existing ones. Derived edges
(``args:``/``calls:``/...) are woven into hand-authored node mappings, so
removing an edge is a YAML edit -- which the live-reload loop already makes
fast. Keeping the write path append-only means this module can never mangle
content it doesn't own.

New entries land as compact flow-style mappings with ``$``-marked refs,
identical to what a hand author would write::

    edges:
      - {from: $preflight, to: $report, type: calls, label: validate}

Writes go through ruamel round-trip mode (shared with :mod:`layout_store`),
so every comment survives. If the document has no ``edges:`` list, one is
created -- placed above the machine-owned ``layout:`` block so hand-editable
content stays together.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ruamel.yaml.comments import CommentedMap, CommentedSeq

from .layout_store import _yaml
from .parser import SIGIL


def append_edges(
    path: str | Path, graph: dict[str, Any], new_edges: list[Any]
) -> int:
    """Append valid, novel edge specs to ``path``; return the number written.

    Each spec is ``{"from": id, "to": id, "type"?: str, "label"?: str}`` with
    unmarked node ids (the ``$`` is added on write). Mirrors
    ``merge_positions``' tolerance for stale client state: entries whose
    endpoints aren't nodes in ``graph``, or that exactly duplicate an existing
    edge (source, target, type, label -- derived or explicit), are silently
    skipped. The file is untouched when nothing survives the filter.
    """
    node_ids = {n["id"] for n in graph["nodes"]}
    seen = {
        (e["source"], e["target"], e.get("type"), e.get("label"))
        for e in graph["edges"]
    }

    accepted: list[tuple[str, str, str | None, str | None]] = []
    for spec in new_edges or []:
        if not isinstance(spec, dict):
            continue
        source = spec.get("from")
        target = spec.get("to")
        if source not in node_ids or target not in node_ids:
            continue
        type_ = str(spec["type"]) if spec.get("type") not in (None, "") else None
        label = str(spec["label"]) if spec.get("label") not in (None, "") else None
        key = (source, target, type_, label)
        if key in seen:
            continue
        seen.add(key)
        accepted.append((source, target, type_, label))
    if not accepted:
        return 0

    path = Path(path)
    yaml = _yaml()
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.load(fh)
    if data is None:
        data = CommentedMap()

    lst = data.get("edges")
    if not isinstance(lst, CommentedSeq):
        lst = CommentedSeq()
        if "edges" in data:
            data["edges"] = lst  # replace an empty/None placeholder in place
        elif "layout" in data:
            data.insert(list(data).index("layout"), "edges", lst)
        else:
            data["edges"] = lst

    for source, target, type_, label in accepted:
        entry = CommentedMap()
        entry["from"] = SIGIL + source
        entry["to"] = SIGIL + target
        if type_ is not None:
            entry["type"] = type_
        if label is not None:
            entry["label"] = label
        entry.fa.set_flow_style()
        lst.append(entry)

    with open(path, "w", encoding="utf-8") as fh:
        yaml.dump(data, fh)
    return len(accepted)
