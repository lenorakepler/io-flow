"""edge_store: append-only browser connections into the YAML ``edges:`` list."""

from __future__ import annotations

import pytest

from io_flow import edge_store
from io_flow.parser import parse_file

YAML = """\
# top comment that must survive
nodes:
  $cfg:
    type: file   # inline comment
  $run:
    type: function
    args:
      c: $cfg
  $report:
    type: file
"""

YAML_WITH_EDGES_AND_LAYOUT = (
    YAML
    + """\
edges:
  - {from: $run, to: $report, type: returns}
layout:
  _topology: deadbeefdeadbeef
  cfg: [10, 20]
"""
)


@pytest.fixture
def src(tmp_path):
    p = tmp_path / "d.yaml"
    p.write_text(YAML, encoding="utf-8")
    return p


def test_appends_flow_style_marked_refs(src):
    graph = parse_file(src)
    n = edge_store.append_edges(
        src, graph, [{"from": "run", "to": "report", "type": "calls", "label": "go"}]
    )
    assert n == 1
    text = src.read_text(encoding="utf-8")
    assert "- {from: $run, to: $report, type: calls, label: go}" in text
    # The result must parse into exactly that edge.
    edges = {(e["source"], e["target"], e.get("type"), e.get("label")) for e in parse_file(src)["edges"]}
    assert ("run", "report", "calls", "go") in edges


def test_type_and_label_are_optional(src):
    graph = parse_file(src)
    edge_store.append_edges(src, graph, [{"from": "run", "to": "report"}])
    assert "- {from: $run, to: $report}" in src.read_text(encoding="utf-8")


def test_preserves_comments(src):
    graph = parse_file(src)
    edge_store.append_edges(src, graph, [{"from": "run", "to": "report"}])
    text = src.read_text(encoding="utf-8")
    assert "# top comment that must survive" in text
    assert "# inline comment" in text


def test_created_edges_list_lands_above_layout_block(tmp_path):
    src = tmp_path / "d.yaml"
    src.write_text(YAML + "layout:\n  _topology: deadbeefdeadbeef\n", encoding="utf-8")
    edge_store.append_edges(src, parse_file(src), [{"from": "run", "to": "report"}])
    text = src.read_text(encoding="utf-8")
    assert text.index("edges:") < text.index("layout:")


def test_appends_to_existing_edges_list(tmp_path):
    src = tmp_path / "d.yaml"
    src.write_text(YAML_WITH_EDGES_AND_LAYOUT, encoding="utf-8")
    edge_store.append_edges(src, parse_file(src), [{"from": "cfg", "to": "report"}])
    text = src.read_text(encoding="utf-8")
    assert "- {from: $run, to: $report, type: returns}" in text  # original kept
    assert "- {from: $cfg, to: $report}" in text
    assert text.count("edges:") == 1


def test_skips_unknown_ids_and_leaves_file_untouched(src):
    before = src.read_text(encoding="utf-8")
    n = edge_store.append_edges(
        src, parse_file(src), [{"from": "ghost", "to": "report"}, {"from": "run"}]
    )
    assert n == 0
    assert src.read_text(encoding="utf-8") == before


def test_skips_duplicates_of_existing_edges(tmp_path):
    src = tmp_path / "d.yaml"
    src.write_text(YAML_WITH_EDGES_AND_LAYOUT, encoding="utf-8")
    n = edge_store.append_edges(
        src,
        parse_file(src),
        [
            # duplicates the explicit edge already in the file
            {"from": "run", "to": "report", "type": "returns"},
            # duplicates the edge derived from `args: {c: $cfg}`
            {"from": "cfg", "to": "run", "type": "args"},
            # duplicated within the batch itself
            {"from": "cfg", "to": "report"},
            {"from": "cfg", "to": "report"},
        ],
    )
    assert n == 1
    assert src.read_text(encoding="utf-8").count("{from: $cfg, to: $report}") == 1
