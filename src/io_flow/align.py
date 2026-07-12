"""Snap almost-aligned saved positions to exact alignment.

``io-flow align`` post-processes the machine-owned ``layout:`` block after a
hand-arranging session: left edges (x) and top edges (y) that landed within a
tolerance of each other collapse to their common value, turning "roughly a
column" into a column. The file stays the source of truth -- run it while
``io-flow edit`` is serving and the browser live-reloads to show the snap.

Positions are parent-relative, so clustering happens per coordinate space:
only siblings (nodes sharing a parent, with top-level nodes sharing the root)
are ever compared. Comparing a child of one compound against an unrelated
top-level node would "align" numbers with different origins and scatter the
diagram instead.

Each cluster snaps to its rounded mean, so no value moves more than the
tolerance in one run. Snapping can occasionally pull a cluster into range of
its neighbor (a chain of near-misses); a re-run tightens those, and the CLI
reports how many values moved so convergence is visible. Compound entries
``[x, y, w, h]`` keep their size; only the position snaps. The topology hash
covers nodes and edges, not positions, so aligning never knocks a diagram out
of exact-restore mode.
"""

from __future__ import annotations

from typing import Any

Move = tuple[str, str, float, float]  # (node_id, axis, old, new)


def snap_positions(
    graph: dict[str, Any],
    positions: dict[str, list[float]],
    tolerance: float = 8.0,
) -> tuple[dict[str, list[float]], list[Move]]:
    """Return ``(new_positions, moves)`` with sibling x/y clusters snapped.

    ``positions`` is the ``read_layout`` shape (``{id: [x, y]}``, compounds
    ``[x, y, w, h]``) and is not mutated. Ids not in ``graph`` (stale saved
    entries) pass through untouched, mirroring ``merge_positions``.
    """
    parent_of = {n["id"]: n.get("parent") for n in graph["nodes"]}
    new = {nid: list(vals) for nid, vals in positions.items()}

    siblings: dict[Any, list[str]] = {}
    for nid in positions:
        if nid in parent_of:
            siblings.setdefault(parent_of[nid], []).append(nid)

    moves: list[Move] = []
    for ids in siblings.values():
        for index, axis in ((0, "x"), (1, "y")):
            snapped = _snap_axis([(nid, positions[nid][index]) for nid in ids], tolerance)
            for nid, target in snapped.items():
                moves.append((nid, axis, positions[nid][index], target))
                new[nid][index] = target
    moves.sort()
    return new, moves


def _snap_axis(entries: list[tuple[str, float]], tolerance: float) -> dict[str, float]:
    """Cluster values whose spread stays within ``tolerance``; snap each
    cluster of 2+ to its rounded mean. Returns only values that change."""
    out: dict[str, float] = {}
    cluster: list[tuple[str, float]] = []

    def flush() -> None:
        if len(cluster) < 2:
            return
        target = float(round(sum(v for _, v in cluster) / len(cluster)))
        for nid, v in cluster:
            if v != target:
                out[nid] = target

    for nid, v in sorted(entries, key=lambda t: (t[1], t[0])):
        if cluster and v - cluster[0][1] > tolerance:
            flush()
            cluster = []
        cluster.append((nid, v))
    flush()
    return out
