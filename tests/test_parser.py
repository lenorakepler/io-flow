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


def _labeled_edges(graph):
    return {(e["source"], e["target"], e.get("label")) for e in graph["edges"]}


def _labeled_edges_typed(graph):
    return {(e["source"], e["target"], e.get("type")) for e in graph["edges"]}


def _node(graph, node_id):
    for n in graph["nodes"]:
        if n["id"] == node_id:
            return n
    raise AssertionError(f"node {node_id!r} not found")


def test_example_edges_exact():
    """The edges documented in example_input.yaml, and nothing else."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # any phantom/unresolved ref would fail
        graph = parse_file(EXAMPLE)

    expected = {
        ("limitparam", "Config.attributes"),
        ("configfile", "Config.from_yaml"),
        ("Config", "do_run"),
        ("skippreflight", "do_run"),
        # `calls:` edges point from the caller to the callee.
        ("do_run", "Config.from_yaml"),
        ("do_run", "preflight"),
        # `returns:` edges point from the function to the returned-to node.
        ("do_run", "report"),
        # explicit top-level `edges:` entry (from -> to as written).
        ("preflight", "report"),
        # a call between two functions nested in a group.
        ("summarize", "plot"),
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


def test_calls_creates_caller_to_callee_edge_with_label():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        graph = parse(
            {
                "nodes": {
                    "functions": {
                        "a": {"calls": {"b": "does the thing", "c": ""}},
                        "b": {},
                        "c": {},
                    }
                }
            }
        )
    # Edge direction is caller -> callee; label carried only when non-empty.
    assert ("a", "b", "does the thing") in _labeled_edges(graph)
    assert ("a", "c", None) in _labeled_edges(graph)


def test_method_calls_are_resolved():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        graph = parse(
            {
                "nodes": {
                    "classes": {
                        "Runner": {"methods": {"go": {"calls": {"helper": "step"}}}},
                    },
                    "functions": {"helper": {}},
                }
            }
        )
    assert ("Runner.go", "helper", "step") in _labeled_edges(graph)


def test_returns_creates_source_to_target_edge_with_label():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        graph = parse(
            {
                "nodes": {
                    "classes": {
                        "Runner": {"methods": {"go": {"returns": {"out": "result"}}}},
                    },
                    "functions": {
                        "a": {"returns": {"b": "the value", "c": ""}},
                        "b": {},
                        "c": {},
                    },
                    "input": {"out": {"type": "file"}},
                }
            }
        )
    # Same source -> target direction and label handling as `calls:`.
    assert ("a", "b", "the value") in _labeled_edges(graph)
    assert ("a", "c", None) in _labeled_edges(graph)
    assert ("Runner.go", "out", "result") in _labeled_edges(graph)


def test_unresolved_return_target_warns_and_makes_no_edge():
    with pytest.warns(UnresolvedReferenceWarning, match="report"):
        graph = parse(
            {
                "nodes": {
                    "functions": {
                        "a": {"returns": {"reprt": ""}},
                        "report": {},
                    }
                }
            }
        )
    assert ("a", "reprt") not in _edge_set(graph)
    assert ("a", "report") not in _edge_set(graph)


def test_unresolved_call_target_warns_and_makes_no_edge():
    with pytest.warns(UnresolvedReferenceWarning, match="helpr"):
        graph = parse(
            {
                "nodes": {
                    "functions": {
                        "a": {"calls": {"helpr": ""}},
                        "helper": {},
                    }
                }
            }
        )
    assert ("a", "helpr") not in _edge_set(graph)
    assert ("a", "helper") not in _edge_set(graph)


def test_derived_edges_carry_their_type():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        graph = parse(
            {
                "nodes": {
                    "input": {"cfg": {"type": "file"}},
                    "functions": {
                        "a": {
                            "args": {"c": "cfg"},
                            "calls": {"b": ""},
                            "returns": {"b": ""},
                        },
                        "b": {},
                    },
                }
            }
        )
    by_pair = {(e["source"], e["target"]): e.get("type") for e in graph["edges"]}
    assert by_pair[("cfg", "a")] == "args"
    # a -> b appears from both calls and returns; both types must be present.
    types = {e.get("type") for e in graph["edges"] if (e["source"], e["target"]) == ("a", "b")}
    assert types == {"calls", "returns"}


def test_explicit_edges_block():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        graph = parse(
            {
                "nodes": {"functions": {"a": {}, "b": {}}},
                "edges": [
                    {"from": "a", "to": "b", "type": "calls", "label": "go"},
                    {"from": "b", "to": "a"},  # type/label optional
                ],
            }
        )
    edges = {(e["source"], e["target"]): e for e in graph["edges"]}
    assert edges[("a", "b")]["type"] == "calls"
    assert edges[("a", "b")]["label"] == "go"
    assert "type" not in edges[("b", "a")]
    assert "label" not in edges[("b", "a")]


def test_explicit_edge_missing_endpoint_is_error():
    with pytest.raises(ValueError):
        parse({"nodes": {"functions": {"a": {}}}, "edges": [{"from": "a"}]})


def test_explicit_edge_unknown_node_warns():
    with pytest.warns(UnresolvedReferenceWarning, match="ghost"):
        graph = parse(
            {
                "nodes": {"functions": {"a": {}}},
                "edges": [{"from": "a", "to": "ghost"}],
            }
        )
    assert _edge_set(graph) == set()


def test_node_label_overrides_display_name_but_not_id():
    graph = parse(
        {
            "nodes": {
                "functions": {
                    "run_v2": {"label": "run"},
                    "helper": {},
                },
                "classes": {
                    "Runner": {"methods": {"go_fast": {"label": "go"}}},
                },
            }
        }
    )
    # id stays the unique key; label carries the display name.
    assert _node(graph, "run_v2")["label"] == "run"
    # unlabeled function falls back to its id.
    assert _node(graph, "helper")["label"] == "helper"
    # method label overrides its default short-name.
    assert _node(graph, "Runner.go_fast")["label"] == "go"


def test_method_label_defaults_to_short_name():
    graph = parse(
        {"nodes": {"classes": {"Runner": {"methods": {"go": {}}}}}}
    )
    assert _node(graph, "Runner.go")["label"] == "go"


def test_group_is_compound_parent_of_its_members():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        graph = parse(
            {
                "nodes": {
                    "groups": {
                        "step1": {
                            "loc": "s.py",
                            "functions": {"a": {"calls": {"b": ""}}, "b": {}},
                        }
                    }
                }
            }
        )
    grp = _node(graph, "step1")
    assert grp["type"] == "group"
    assert grp["parent"] is None
    assert grp["data"].get("loc") == "s.py"  # non-member keys become group data
    # members are parented to the group; their ids stay bare (unqualified).
    assert _node(graph, "a")["parent"] == "step1"
    assert _node(graph, "b")["parent"] == "step1"
    # edges between members still resolve.
    assert ("a", "b") in _edge_set(graph)


def test_groups_nest_recursively_with_classes_and_functions():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        graph = parse(
            {
                "nodes": {
                    "groups": {
                        "outer": {
                            "functions": {"top": {}},
                            "groups": {
                                "inner": {
                                    "functions": {"deep": {}},
                                    "classes": {"C": {"methods": {"m": {}}}},
                                }
                            },
                        }
                    }
                }
            }
        )
    assert _node(graph, "outer")["parent"] is None
    assert _node(graph, "top")["parent"] == "outer"
    assert _node(graph, "inner")["parent"] == "outer"
    assert _node(graph, "deep")["parent"] == "inner"
    assert _node(graph, "C")["parent"] == "inner"
    assert _node(graph, "C.m")["parent"] == "C"


def test_group_can_act_as_a_function():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        graph = parse(
            {
                "nodes": {
                    "input": {"cfg": {"type": "file"}},
                    "groups": {
                        "workflow": {
                            "args": {"c": "cfg"},
                            "calls": {"other": "run"},
                            "functions": {"inner": {}},
                        }
                    },
                    "functions": {"other": {}},
                }
            }
        )
    # group participates in edges like a function.
    assert ("cfg", "workflow", "args") in _labeled_edges_typed(graph)
    assert ("workflow", "other", "calls") in _labeled_edges_typed(graph)


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


def test_duplicate_edges_are_deduped_but_types_kept():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        graph = parse(
            {
                "nodes": {"functions": {"a": {"calls": {"b": ""}}, "b": {}}},
                # Explicit edge repeating the derived calls edge exactly.
                "edges": [{"from": "a", "to": "b", "type": "calls"}],
            }
        )
    calls_edges = [e for e in graph["edges"] if e.get("type") == "calls"]
    assert len(calls_edges) == 1


def test_diagram_config_passes_through():
    graph = parse(
        {
            "nodes": {"functions": {"a": {}}},
            "diagram": {"direction": "DOWN", "spacing": 60, "elk": {"elk.aspectRatio": "2"}},
        }
    )
    assert graph["diagram"]["direction"] == "DOWN"
    assert graph["diagram"]["elk"]["elk.aspectRatio"] == "2"


def test_relations_registers_new_edge_kinds():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        graph = parse(
            {
                "relations": {
                    "emits": {"direction": "out"},
                    "reads": {"direction": "in", "ref": "value"},
                },
                "nodes": {
                    "input": {"log": {"type": "file"}, "cfg": {"type": "file"}},
                    "functions": {
                        "a": {"emits": {"log": "event"}, "reads": {"conf": "cfg"}},
                    },
                },
            }
        )
    assert ("a", "log", "emits") in _labeled_edges_typed(graph)
    assert ("cfg", "a", "reads") in _labeled_edges_typed(graph)
    # label carried from the key-ref form.
    assert ("a", "log", "event") in _labeled_edges(graph)


def test_relations_unresolved_ref_still_warns():
    with pytest.warns(UnresolvedReferenceWarning, match="lgo"):
        parse(
            {
                "relations": {"emits": {"direction": "out"}},
                "nodes": {
                    "input": {"log": {"type": "file"}},
                    "functions": {"a": {"emits": {"lgo": ""}}},
                },
            }
        )


def test_relations_bad_direction_is_error():
    with pytest.raises(ValueError, match="direction"):
        parse({"relations": {"x": {"direction": "sideways"}}, "nodes": {}})
