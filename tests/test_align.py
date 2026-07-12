"""align: snap almost-aligned saved positions, per sibling coordinate space."""

from __future__ import annotations

import pytest

from io_flow import align, layout_store
from io_flow.cli import main
from io_flow.parser import parse, parse_file

YAML = """\
# top comment that must survive
nodes:
  $a: {type: file}   # inline comment
  $b: {type: file}
  $c: {type: file}
  $g:
    type: group
    $ga: {}
    $gb: {}
"""


def _graph():
    return parse(
        {
            "nodes": {
                "$a": {},
                "$b": {},
                "$c": {},
                "$g": {"type": "group", "$ga": {}, "$gb": {}},
            }
        }
    )


def test_near_column_snaps_to_rounded_mean():
    positions = {"a": [206, 10], "b": [210, 100], "c": [214, 200]}
    new, moves = align.snap_positions(_graph(), positions, tolerance=8)
    assert new["a"][0] == new["b"][0] == new["c"][0] == 210
    # y values are far apart and untouched.
    assert [new[k][1] for k in ("a", "b", "c")] == [10, 100, 200]
    assert {(m[0], m[1]) for m in moves} == {("a", "x"), ("c", "x")}


def test_axes_snap_independently():
    positions = {"a": [100, 50], "b": [300, 53]}  # a row, not a column
    new, _ = align.snap_positions(_graph(), positions, tolerance=8)
    assert new["a"][1] == new["b"][1] == 52
    assert new["a"][0] == 100 and new["b"][0] == 300


def test_gap_beyond_tolerance_does_not_snap():
    positions = {"a": [100, 0], "b": [109, 50]}
    _, moves = align.snap_positions(_graph(), positions, tolerance=8)
    assert moves == []


def test_different_parents_never_cluster():
    # ga is parent-relative inside $g; numerically near a's x but a different
    # coordinate space entirely.
    positions = {"a": [210, 10], "g": [500, 10], "ga": [208, 40], "gb": [212, 90]}
    new, _ = align.snap_positions(_graph(), positions, tolerance=8)
    assert new["a"][0] == 210  # untouched: no top-level sibling nearby
    assert new["ga"][0] == new["gb"][0] == 210  # siblings inside $g do snap


def test_compound_entries_keep_their_size():
    positions = {"g": [206, 10, 320, 240], "a": [210, 400]}
    new, _ = align.snap_positions(_graph(), positions, tolerance=8)
    assert new["g"] == [208, 10, 320, 240]
    assert new["a"] == [208, 400]


def test_stale_ids_pass_through_untouched():
    positions = {"a": [100, 0], "ghost": [103, 0]}
    new, moves = align.snap_positions(_graph(), positions, tolerance=8)
    assert new["ghost"] == [103, 0]
    assert moves == []  # ghost never joins a's cluster


def test_snapped_result_is_stable_on_rerun():
    positions = {"a": [206, 10], "b": [210, 100], "c": [214, 200]}
    once, _ = align.snap_positions(_graph(), positions, tolerance=8)
    twice, moves = align.snap_positions(_graph(), once, tolerance=8)
    assert twice == once
    assert moves == []


# ---- CLI ---------------------------------------------------------------------


@pytest.fixture
def src(tmp_path):
    p = tmp_path / "d.yaml"
    p.write_text(YAML, encoding="utf-8")
    graph = parse_file(p)
    layout_store.merge_positions(
        p,
        graph,
        {"a": [206, 10], "b": [210, 100], "c": [214, 200], "g": [500, 10, 320, 240],
         "ga": [16, 40], "gb": [20, 120]},
    )
    return p


def test_cli_align_writes_and_preserves_comments(src, capsys):
    assert main(["align", str(src)]) == 0
    out = capsys.readouterr().out
    assert "aligned" in out and "a: x 206 -> 210" in out
    text = src.read_text(encoding="utf-8")
    assert "# top comment that must survive" in text
    assert "# inline comment" in text
    assert "a: [210, 10]" in text
    assert "g: [500, 10, 320, 240]" in text  # size kept
    # Aligning never invalidates the layout: still exact-restore.
    graph = parse_file(src)
    layout_store.annotate_graph(graph, src)
    assert graph["_layout"]["mode"] == "restore"


def test_cli_align_dry_run_touches_nothing(src, capsys):
    before = src.read_text(encoding="utf-8")
    assert main(["align", str(src), "--dry-run"]) == 0
    assert "dry run" in capsys.readouterr().out
    assert src.read_text(encoding="utf-8") == before


def test_cli_align_reports_already_aligned(src, capsys):
    assert main(["align", str(src)]) == 0
    capsys.readouterr()
    assert main(["align", str(src)]) == 0
    assert "already aligned" in capsys.readouterr().out


def test_cli_align_tolerance_flag(src, capsys):
    # Tight tolerance: 206/210/214 are no longer "almost aligned".
    assert main(["align", str(src), "--tolerance", "2"]) == 0
    assert "already aligned" in capsys.readouterr().out


def test_cli_align_without_saved_layout_fails(tmp_path, capsys):
    p = tmp_path / "d.yaml"
    p.write_text(YAML, encoding="utf-8")
    assert main(["align", str(p)]) == 1
    assert "no saved layout" in capsys.readouterr().err
