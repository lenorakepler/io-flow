"""Read/merge the ``layout:`` block, with a topology hash gate.

All writes go through ruamel.yaml round-trip mode so the comment-heavy source
YAML survives a save-back untouched. Positions are stored parent-relative --
exactly the coordinate space the viewer uses (`state.pos`) -- as compact
flow-style ``nodeid: [x, y]`` entries under a ``layout:`` mapping, keyed by a
``_topology`` hash. Compound nodes (classes/groups) store ``[x, y, w, h]`` so
a manually resized container keeps its size across restores.

Restore policy (applied by :func:`annotate_graph`):
  * saved hash matches current topology  -> restore positions, browser skips ELK
  * saved hash differs                    -> ELK re-layout with saved positions
                                             as hints + a "topology changed" notice
  * no saved layout                       -> plain ELK
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq


def _yaml() -> YAML:
    y = YAML()  # round-trip mode: preserves comments, order, styles
    y.preserve_quotes = True
    y.width = 4096  # don't wrap our flow-style position lists
    return y


def topology_hash(graph: dict[str, Any]) -> str:
    """Stable short hash of the node-id set + edge pairs."""
    ids = sorted(n["id"] for n in graph["nodes"])
    edges = sorted((e["source"], e["target"]) for e in graph["edges"])
    payload = json.dumps({"nodes": ids, "edges": edges}, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def _num(v: Any) -> Any:
    """Keep whole numbers as ints so the YAML stays clean (`[50, 117]`)."""
    f = float(v)
    return int(f) if f.is_integer() else round(f, 1)


def read_layout(path: str | Path) -> dict[str, Any] | None:
    """Return ``{'hash': str|None, 'positions': {id: [x, y]}}`` or ``None``."""
    path = Path(path)
    if not path.exists():
        return None
    with open(path, "r", encoding="utf-8") as fh:
        data = _yaml().load(fh)
    if not data:
        return None
    lay = data.get("layout")
    if not isinstance(lay, dict):
        return None
    positions: dict[str, list[float]] = {}
    hash_ = None
    for key, value in lay.items():
        if key == "_topology":
            hash_ = str(value)
            continue
        try:
            nums = [float(v) for v in list(value)[:4]]
        except (TypeError, ValueError):
            continue
        if len(nums) < 2:
            continue
        # [x, y] for leaves, [x, y, w, h] for resized compounds.
        positions[str(key)] = nums
    return {"hash": hash_, "positions": positions}


def annotate_graph(graph: dict[str, Any], path: str | Path) -> dict[str, Any]:
    """Attach a ``_layout`` directive to the graph for the viewer to consume."""
    saved = read_layout(path)
    current = topology_hash(graph)

    if saved and saved.get("hash") == current:
        graph["_layout"] = {"mode": "restore", "positions": saved["positions"], "notice": None}
    elif saved:
        saved_ids = set(saved["positions"].keys())
        current_ids = {n["id"] for n in graph["nodes"]}
        added = len(current_ids - saved_ids)
        removed = len(saved_ids - current_ids)
        parts = []
        if added:
            parts.append(f"{added} node{'s' if added != 1 else ''} added")
        if removed:
            parts.append(f"{removed} node{'s' if removed != 1 else ''} removed")
        detail = ", ".join(parts) if parts else "edges changed"
        notice = f"Topology changed ({detail}); saved layout approximated."
        graph["_layout"] = {"mode": "elk", "positions": saved["positions"], "notice": notice}
    else:
        graph["_layout"] = {"mode": "elk", "positions": {}, "notice": None}
    return graph


def merge_positions(
    path: str | Path, graph: dict[str, Any], positions: dict[str, Any]
) -> None:
    """Merge ``{id: [x, y]}`` into the YAML's ``layout:`` block, in place.

    Preserves every existing comment (verified in tests, not by eye).
    """
    path = Path(path)
    yaml = _yaml()
    with open(path, "r", encoding="utf-8") as fh:
        data = yaml.load(fh)
    if data is None:
        data = CommentedMap()

    lay = data.get("layout")
    if not isinstance(lay, CommentedMap):
        lay = CommentedMap()
        data["layout"] = lay
    else:
        lay.clear()  # regenerate contents; the block itself is machine-owned

    lay["_topology"] = topology_hash(graph)
    for node in graph["nodes"]:
        p = positions.get(node["id"])
        # Silently ignore positions for ids not in the graph (stale client
        # state) and malformed entries.
        try:
            vals = [_num(v) for v in list(p)[: 4 if len(p) >= 4 else 2]]
        except (TypeError, ValueError):
            continue
        if len(vals) < 2:
            continue
        seq = CommentedSeq(vals)
        seq.fa.set_flow_style()
        lay[node["id"]] = seq

    with open(path, "w", encoding="utf-8") as fh:
        yaml.dump(data, fh)
