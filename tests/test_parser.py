"""M1 acceptance tests: parser produces the exact expected graph model."""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from io_flow.parser import (
    DuplicateNodeError,
    UnresolvedReferenceWarning,
    parse,
    parse_file,
)

EXAMPLE = Path(__file__).resolve().parents[1] / "example_input.yaml"


def _edge_set(graph):
    return {(e["source"], e["target"]) for e in graph["edges"]}


def _node(graph, node_id):
    for n in graph["nodes"]:
        if n["id"] == node_id:
            return n
    raise AssertionError(f"node {node_id!r} not found")


def test_example_edges_exact():
    """The four edges documented in example_input.yaml, and nothing else."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # any phantom/unresolved ref would fail
        graph = parse_file(EXAMPLE)

    expected = {
        ("limitparam", "Config.attributes"),
        ("configfile", "Config.from_yaml"),
        ("Config", "do_run"),
        ("skippreflight", "do_run"),
    }
    assert _edge_set(graph) == expected


def test_no_phantom_edges_from_free_text():
    """value:/cli:/description: content must never produce edges."""
    graph = parse(
        {
            "nodes": {
                "input": {
                    # value happens to equal another node's id -> must NOT match
                    "alpha": {"value": "beta", "type": "file"},
                    "beta": {"cli": "--beta", "type": "option"},
                    # description/cli that look like ids -> must NOT match
                    "gamma": {"cli": "beta", "description": "alpha", "type": "file"},
                }
            }
        }
    )
    assert _edge_set(graph) == set()


def test_node_hierarchy_and_types():
    graph = parse_file(EXAMPLE)

    assert _node(graph, "file1")["type"] == "file"
    assert _node(graph, "full")["type"] == "option"
    assert _node(graph, "limitparam")["type"] == "parameter"

    cls = _node(graph, "Config")
    assert cls["type"] == "class"
    assert cls["parent"] is None
    assert cls["data"].get("loc") == "src/config.py"

    attrs = _node(graph, "Config.attributes")
    assert attrs["type"] == "attributes"
    assert attrs["parent"] == "Config"

    method = _node(graph, "Config.from_yaml")
    assert method["type"] == "method"
    assert method["parent"] == "Config"

    fn = _node(graph, "do_run")
    assert fn["type"] == "function"
    assert fn["parent"] is None


def test_forward_reference_resolves():
    """A reference to a node defined later in the document still resolves."""
    graph = parse(
        {
            "nodes": {
                "functions": {
                    "runner": {"args": {"cfg": "late_input"}},
                },
                "input": {
                    "late_input": {"type": "file"},
                },
            }
        }
    )
    assert ("late_input", "runner") in _edge_set(graph)


def test_duplicate_id_is_hard_error():
    with pytest.raises(DuplicateNodeError):
        parse(
            {
                "nodes": {
                    "input": {"Config": {"type": "file"}},
                    "classes": {"Config": {"loc": "x.py"}},
                }
            }
        )


def test_unresolved_reference_warns_with_candidates():
    with pytest.warns(UnresolvedReferenceWarning, match="configfil"):
        graph = parse(
            {
                "nodes": {
                    "input": {"configfile": {"type": "file"}},
                    "functions": {
                        # typo: 'configfil' should suggest 'configfile'
                        "loader": {"args": {"path": "configfil"}},
                    },
                }
            }
        )
    # no edge is created for the unresolved reference
    assert _edge_set(graph) == set()


def test_numeric_and_bool_arg_values_are_not_references():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        graph = parse(
            {
                "nodes": {
                    "functions": {
                        "f": {"args": {"threshold": 60, "flag": False}},
                    }
                }
            }
        )
    assert _edge_set(graph) == set()
