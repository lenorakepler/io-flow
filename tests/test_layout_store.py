"""M5 acceptance tests: layout persistence preserves comments and restores."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from io_flow import layout_store
from io_flow.parser import parse_file

EXAMPLE = Path(__file__).resolve().parents[1] / "example_input.yaml"


@pytest.fixture
def yaml_copy(tmp_path):
    dst = tmp_path / "input.yaml"
    shutil.copy(EXAMPLE, dst)
    return dst


def _original_comment_lines():
    text = EXAMPLE.read_text(encoding="utf-8")
    return [ln for ln in text.splitlines() if ln.lstrip().startswith("#")]


def test_topology_hash_stable_and_edge_sensitive():
    g = parse_file(EXAMPLE)
    h1 = layout_store.topology_hash(g)
    h2 = layout_store.topology_hash(parse_file(EXAMPLE))
    assert h1 == h2

    g2 = parse_file(EXAMPLE)
    g2["nodes"].append({"id": "zzz_new", "type": "file", "parent": None, "data": {}})
    assert layout_store.topology_hash(g2) != h1


def test_topology_hash_is_parent_sensitive():
    """Names survive regrouping, but parent-relative positions don't -- a
    reparent must invalidate exact restore."""
    g = parse_file(EXAMPLE)
    h1 = layout_store.topology_hash(g)

    g2 = parse_file(EXAMPLE)
    for n in g2["nodes"]:
        if n["id"] == "plot":  # lives in $postprocess; hoist to top level
            n["parent"] = None
    assert layout_store.topology_hash(g2) != h1


def test_merge_preserves_every_comment(yaml_copy):
    graph = parse_file(yaml_copy)
    positions = {n["id"]: [10 + i, 20 + i] for i, n in enumerate(graph["nodes"])}
    layout_store.merge_positions(yaml_copy, graph, positions)

    after = yaml_copy.read_text(encoding="utf-8")
    for comment in _original_comment_lines():
        assert comment in after, f"comment lost: {comment!r}"


def test_merge_writes_compact_flow_style_block(yaml_copy):
    graph = parse_file(yaml_copy)
    positions = {"file1": [50, 117], "Config": [252, 193]}
    layout_store.merge_positions(yaml_copy, graph, positions)

    text = yaml_copy.read_text(encoding="utf-8")
    assert "layout:" in text
    assert "_topology:" in text
    # flow-style, integer, no wrapping
    assert "file1: [50, 117]" in text
    assert "Config: [252, 193]" in text


def test_round_trip_restore_matches(yaml_copy):
    graph = parse_file(yaml_copy)
    positions = {"file1": [50, 117], "from_yaml": [16, 117]}
    layout_store.merge_positions(yaml_copy, graph, positions)

    saved = layout_store.read_layout(yaml_copy)
    assert saved["hash"] == layout_store.topology_hash(graph)
    assert saved["positions"]["file1"] == [50.0, 117.0]
    assert saved["positions"]["from_yaml"] == [16.0, 117.0]


def test_annotate_restore_when_hash_matches(yaml_copy):
    graph = parse_file(yaml_copy)
    layout_store.merge_positions(yaml_copy, graph, {"file1": [1, 2]})

    fresh = parse_file(yaml_copy)
    layout_store.annotate_graph(fresh, yaml_copy)
    assert fresh["_layout"]["mode"] == "restore"
    assert fresh["_layout"]["notice"] is None
    assert fresh["_layout"]["positions"]["file1"] == [1.0, 2.0]


def test_anchor_overrides_round_trip(yaml_copy):
    graph = parse_file(yaml_copy)
    # preflight -> report (calls) is a real edge in the example.
    key = "preflight>report:calls"
    layout_store.merge_positions(
        yaml_copy, graph, {"file1": [1, 2]}, anchors={key: {"from": "bottom", "to": "top"}}
    )

    text = yaml_copy.read_text(encoding="utf-8")
    assert "_anchors:" in text

    saved = layout_store.read_layout(yaml_copy)
    assert saved["anchors"][key] == {"from": "bottom", "to": "top"}

    fresh = parse_file(yaml_copy)
    layout_store.annotate_graph(fresh, yaml_copy)
    assert fresh["_layout"]["anchors"][key] == {"from": "bottom", "to": "top"}

    # Comments survive an anchor-bearing save too.
    for comment in _original_comment_lines():
        assert comment in text, f"comment lost: {comment!r}"


def test_anchor_overrides_sanitized_and_stale_dropped(yaml_copy):
    graph = parse_file(yaml_copy)
    layout_store.merge_positions(
        yaml_copy,
        graph,
        {"file1": [1, 2]},
        anchors={
            "ghost>nowhere": {"from": "left"},  # no such edge: dropped
            "preflight>report:calls": {"from": "middle", "to": "top"},  # bad side dropped
            "do_run>preflight:calls": {"sideways": "left"},  # no valid ends: dropped
        },
    )
    saved = layout_store.read_layout(yaml_copy)
    assert saved["anchors"] == {"preflight>report:calls": {"to": "top"}}


def test_edge_key_includes_type_when_present():
    assert layout_store.edge_key({"source": "a", "target": "b"}) == "a>b"
    assert layout_store.edge_key({"source": "a", "target": "b", "type": "calls"}) == "a>b:calls"


def test_annotate_elk_with_notice_when_topology_changes(yaml_copy):
    graph = parse_file(yaml_copy)
    layout_store.merge_positions(yaml_copy, graph, {"file1": [1, 2]})

    # Add a new input node to change topology, keeping the saved layout block.
    text = yaml_copy.read_text(encoding="utf-8")
    text = text.replace("nodes:\n", "nodes:\n  $newnode: {type: file}\n", 1)
    yaml_copy.write_text(text, encoding="utf-8")

    changed = parse_file(yaml_copy)
    layout_store.annotate_graph(changed, yaml_copy)
    assert changed["_layout"]["mode"] == "elk"
    assert changed["_layout"]["notice"] is not None
    assert "added" in changed["_layout"]["notice"]


def test_annotate_plain_elk_when_no_layout(yaml_copy):
    graph = parse_file(yaml_copy)
    layout_store.annotate_graph(graph, yaml_copy)
    assert graph["_layout"]["mode"] == "elk"
    assert graph["_layout"]["notice"] is None
    assert graph["_layout"]["positions"] == {}


def test_compound_size_round_trips(yaml_copy):
    """Compounds save [x, y, w, h]; leaves stay [x, y]."""
    graph = parse_file(yaml_copy)
    positions = {"Config": [252, 193, 320, 240], "file1": [50, 117]}
    layout_store.merge_positions(yaml_copy, graph, positions)

    text = yaml_copy.read_text(encoding="utf-8")
    assert "Config: [252, 193, 320, 240]" in text
    assert "file1: [50, 117]" in text

    saved = layout_store.read_layout(yaml_copy)
    assert saved["positions"]["Config"] == [252.0, 193.0, 320.0, 240.0]
    assert saved["positions"]["file1"] == [50.0, 117.0]


def test_malformed_position_entries_are_skipped(yaml_copy):
    graph = parse_file(yaml_copy)
    layout_store.merge_positions(
        yaml_copy, graph, {"file1": [1, 2], "Config": None, "do_run": [5]}
    )
    saved = layout_store.read_layout(yaml_copy)
    assert saved["positions"] == {"file1": [1.0, 2.0]}
