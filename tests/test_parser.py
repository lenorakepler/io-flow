"""Parser acceptance tests: the $-grammar produces the exact expected graph model."""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from io_flow.parser import (
    UnmarkedReferenceWarning,
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
        # a call between two functions nested in a group (path-qualified ids).
        ("postprocess.summarize", "postprocess.plot"),
    }
    assert _edge_set(graph) == expected


def test_unmarked_strings_never_produce_edges():
    """Unmarked strings are literals: free text can never spawn a phantom edge."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        graph = parse(
            {
                "nodes": {
                    # value/cli/description that look like ids -> must NOT match.
                    "$alpha": {"value": "beta", "type": "file"},
                    "$beta": {"cli": "--beta", "type": "option"},
                    "$gamma": {"cli": "beta", "description": "alpha", "type": "file"},
                }
            }
        )
    assert _edge_set(graph) == set()


def test_unmarked_string_in_relation_block_makes_no_edge():
    """Inside a relation block an unmarked match still makes no edge (it warns)."""
    with pytest.warns(UnmarkedReferenceWarning):
        graph = parse(
            {
                "nodes": {
                    "$beta": {"type": "file"},
                    "$f": {"args": {"x": "beta"}},
                }
            }
        )
    assert _edge_set(graph) == set()


def test_unmarked_literal_matching_a_node_id_warns():
    """A forgotten $ silently drops an edge -- the parser makes that loud."""
    with pytest.warns(UnmarkedReferenceWarning, match="beta"):
        parse(
            {
                "nodes": {
                    "$beta": {"type": "file"},
                    "$f": {"args": {"x": "beta"}},
                }
            }
        )


def test_node_hierarchy_types_and_data():
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
    assert method["type"] == "method"  # via defaults: {class: method}
    assert method["parent"] == "Config"

    fn = _node(graph, "do_run")
    assert fn["type"] == "function"
    assert fn["parent"] is None


def test_forward_reference_resolves():
    """A reference to a node defined later in the document still resolves."""
    graph = parse(
        {
            "nodes": {
                "$runner": {"args": {"cfg": "$late_input"}},
                "$late_input": {"type": "file"},
            }
        }
    )
    assert ("late_input", "runner") in _edge_set(graph)


def test_unmarked_top_level_key_is_error():
    """Under nodes: there is no owner node, so unmarked keys are errors."""
    with pytest.raises(ValueError, match="loose_data"):
        parse({"nodes": {"loose_data": {"type": "file"}}})


def test_dot_in_node_name_is_error():
    """Dots separate path segments in ids, so declared names can't contain them."""
    with pytest.raises(ValueError, match=r"\."):
        parse({"nodes": {"$a.b": {}}})


def test_unresolved_reference_warns_with_candidates():
    with pytest.warns(UnresolvedReferenceWarning, match="configfil"):
        graph = parse(
            {
                "nodes": {
                    "$configfile": {"type": "file"},
                    # typo: '$configfil' should suggest '$configfile'
                    "$loader": {"args": {"path": "$configfil"}},
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
                    "$a": {"calls": {"$b": "does the thing", "$c": ""}},
                    "$b": {},
                    "$c": {},
                }
            }
        )
    # Edge direction is caller -> callee; label carried only when non-empty.
    assert ("a", "b", "does the thing") in _labeled_edges(graph)
    assert ("a", "c", None) in _labeled_edges(graph)


def test_relation_reference_works_on_either_side():
    """Whichever side wears the $ is the reference -- no key/value axis."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        graph = parse(
            {
                "nodes": {
                    "$cfg": {"type": "file"},
                    # value-side ref: unmarked key is the arg name.
                    "$f": {"args": {"path": "$cfg"}},
                    # key-side ref (same relation): unmarked value is a label.
                    "$g": {"args": {"$cfg": "raw"}},
                }
            }
        )
    assert ("cfg", "f", None) in _labeled_edges(graph)
    assert ("cfg", "g", "raw") in _labeled_edges(graph)


def test_both_sides_marked_is_error():
    with pytest.raises(ValueError, match="both"):
        parse({"nodes": {"$a": {"calls": {"$b": "$c"}}, "$b": {}, "$c": {}}})


def test_method_calls_are_resolved():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        graph = parse(
            {
                "nodes": {
                    "$Runner": {
                        "type": "class",
                        "$go": {"calls": {"$helper": "step"}},
                    },
                    "$helper": {},
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
                    "$Runner": {
                        "type": "class",
                        "$go": {"returns": {"$out": "result"}},
                    },
                    "$a": {"returns": {"$b": "the value", "$c": ""}},
                    "$b": {},
                    "$c": {},
                    "$out": {"type": "file"},
                }
            }
        )
    # Same source -> target direction and label handling as `calls:`.
    assert ("a", "b", "the value") in _labeled_edges(graph)
    assert ("a", "c", None) in _labeled_edges(graph)
    assert ("Runner.go", "out", "result") in _labeled_edges(graph)


def test_unresolved_reference_makes_no_edge():
    with pytest.warns(UnresolvedReferenceWarning, match="reprt"):
        graph = parse(
            {
                "nodes": {
                    "$a": {"returns": {"$reprt": ""}},
                    "$report": {},
                }
            }
        )
    assert ("a", "reprt") not in _edge_set(graph)
    assert ("a", "report") not in _edge_set(graph)


def test_derived_edges_carry_their_type():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        graph = parse(
            {
                "nodes": {
                    "$cfg": {"type": "file"},
                    "$a": {
                        "args": {"c": "$cfg"},
                        "calls": {"$b": ""},
                        "returns": {"$b": ""},
                    },
                    "$b": {},
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
                "nodes": {"$a": {}, "$b": {}},
                "edges": [
                    {"from": "$a", "to": "$b", "type": "calls", "label": "go"},
                    {"from": "$b", "to": "$a"},  # type/label optional
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
        parse({"nodes": {"$a": {}}, "edges": [{"from": "$a"}]})


def test_explicit_edge_unmarked_ref_is_error():
    with pytest.raises(ValueError, match=r"\$-marked"):
        parse({"nodes": {"$a": {}, "$b": {}}, "edges": [{"from": "a", "to": "$b"}]})


def test_node_level_edges_block():
    """An edges: list inside a node behaves exactly like the top-level one."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        graph = parse(
            {
                "nodes": {
                    "$g": {
                        "type": "group",
                        "$a": {},
                        "$b": {},
                        "edges": [
                            {"from": "$g.a", "to": "$g.b", "type": "passes", "label": "baton"},
                        ],
                    }
                }
            }
        )
    assert ("g.a", "g.b", "passes") in _labeled_edges_typed(graph)
    assert ("g.a", "g.b", "baton") in _labeled_edges(graph)
    # `edges` is reserved: it is consumed, not sidebar data.
    assert "edges" not in _node(graph, "g")["data"]


def test_node_level_edge_defaults_omitted_endpoint_to_owner():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        graph = parse(
            {
                "nodes": {
                    "$x": {},
                    "$g": {
                        "type": "group",
                        "edges": [
                            {"to": "$x", "type": "emits"},   # from: defaults to $g
                            {"from": "$x", "type": "feeds"},  # to: defaults to $g
                        ],
                    },
                }
            }
        )
    assert ("g", "x", "emits") in _labeled_edges_typed(graph)
    assert ("x", "g", "feeds") in _labeled_edges_typed(graph)


def test_node_level_edge_with_both_endpoints_omitted_is_error():
    with pytest.raises(ValueError, match="at least one"):
        parse({"nodes": {"$g": {"edges": [{"type": "loop"}]}}})


def test_node_level_edge_unmarked_ref_is_error():
    with pytest.raises(ValueError, match=r"\$-marked"):
        parse({"nodes": {"$x": {}, "$g": {"edges": [{"to": "x"}]}}})


def test_node_level_edges_must_be_a_list():
    with pytest.raises(ValueError, match="list"):
        parse({"nodes": {"$g": {"edges": {"to": "$g"}}}})


def test_top_level_edge_still_requires_both_endpoints():
    with pytest.raises(ValueError, match="both"):
        parse({"nodes": {"$a": {}}, "edges": [{"to": "$a"}]})


def test_node_level_and_top_level_edges_dedupe_together():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        graph = parse(
            {
                "nodes": {
                    "$a": {"edges": [{"to": "$b", "type": "passes"}]},
                    "$b": {},
                },
                "edges": [{"from": "$a", "to": "$b", "type": "passes"}],
            }
        )
    passes = [e for e in graph["edges"] if e.get("type") == "passes"]
    assert len(passes) == 1


def test_explicit_edge_unknown_node_warns():
    with pytest.warns(UnresolvedReferenceWarning, match="ghost"):
        graph = parse(
            {
                "nodes": {"$a": {}},
                "edges": [{"from": "$a", "to": "$ghost"}],
            }
        )
    assert _edge_set(graph) == set()


def test_node_label_overrides_display_name_but_not_id():
    graph = parse(
        {
            "nodes": {
                "$run_v2": {"label": "run"},
                "$helper": {},
                "$Runner": {"type": "class", "$go_fast": {"label": "go"}},
            }
        }
    )
    # id stays the unique path; label carries the display name.
    assert _node(graph, "run_v2")["label"] == "run"
    # unlabeled node falls back to its short name.
    assert _node(graph, "helper")["label"] == "helper"
    # nested label override.
    assert _node(graph, "Runner.go_fast")["label"] == "go"


def test_label_defaults_to_short_name():
    graph = parse({"nodes": {"$Runner": {"type": "class", "$go": {}}}})
    assert _node(graph, "Runner.go")["label"] == "go"


def test_any_node_with_children_is_a_compound_parent():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        graph = parse(
            {
                "nodes": {
                    "$step1": {
                        "type": "group",
                        "loc": "s.py",
                        "$a": {"calls": {"$step1.b": ""}},
                        "$b": {},
                    }
                }
            }
        )
    grp = _node(graph, "step1")
    assert grp["type"] == "group"
    assert grp["parent"] is None
    assert grp["data"].get("loc") == "s.py"  # unmarked keys become node data
    # members are parented to the group; ids are path-qualified.
    assert _node(graph, "step1.a")["parent"] == "step1"
    assert _node(graph, "step1.b")["parent"] == "step1"
    # edges between members resolve via full paths.
    assert ("step1.a", "step1.b") in _edge_set(graph)


def test_nesting_is_recursive_and_ids_are_paths():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        graph = parse(
            {
                "nodes": {
                    "$outer": {
                        "type": "group",
                        "$top": {},
                        "$inner": {
                            "type": "group",
                            "$deep": {},
                            "$C": {"type": "class", "$m": {}},
                        },
                    }
                }
            }
        )
    assert _node(graph, "outer")["parent"] is None
    assert _node(graph, "outer.top")["parent"] == "outer"
    assert _node(graph, "outer.inner")["parent"] == "outer"
    assert _node(graph, "outer.inner.deep")["parent"] == "outer.inner"
    assert _node(graph, "outer.inner.C")["parent"] == "outer.inner"
    assert _node(graph, "outer.inner.C.m")["parent"] == "outer.inner.C"


def test_compound_can_act_as_a_function():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        graph = parse(
            {
                "nodes": {
                    "$cfg": {"type": "file"},
                    "$workflow": {
                        "type": "group",
                        "args": {"c": "$cfg"},
                        "calls": {"$other": "run"},
                        "$inner": {},
                    },
                    "$other": {},
                }
            }
        )
    # a compound participates in edges like any node.
    assert ("cfg", "workflow", "args") in _labeled_edges_typed(graph)
    assert ("workflow", "other", "calls") in _labeled_edges_typed(graph)


def test_numeric_and_bool_values_are_literals():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        graph = parse(
            {
                "nodes": {
                    "$f": {"args": {"threshold": 60, "flag": False}},
                }
            }
        )
    assert _edge_set(graph) == set()


def test_duplicate_edges_are_deduped_but_types_kept():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        graph = parse(
            {
                "nodes": {"$a": {"calls": {"$b": ""}}, "$b": {}},
                # Explicit edge repeating the derived calls edge exactly.
                "edges": [{"from": "$a", "to": "$b", "type": "calls"}],
            }
        )
    calls_edges = [e for e in graph["edges"] if e.get("type") == "calls"]
    assert len(calls_edges) == 1


def test_diagram_config_passes_through():
    graph = parse(
        {
            "nodes": {"$a": {}},
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
                    "reads": {"direction": "in"},
                },
                "nodes": {
                    "$log": {"type": "file"},
                    "$cfg": {"type": "file"},
                    "$a": {"emits": {"$log": "event"}, "reads": {"conf": "$cfg"}},
                },
            }
        )
    assert ("a", "log", "emits") in _labeled_edges_typed(graph)
    assert ("cfg", "a", "reads") in _labeled_edges_typed(graph)
    # label carried from the key-side-ref form.
    assert ("a", "log", "event") in _labeled_edges(graph)


def test_relations_unresolved_ref_still_warns():
    with pytest.warns(UnresolvedReferenceWarning, match="lgo"):
        parse(
            {
                "relations": {"emits": {"direction": "out"}},
                "nodes": {
                    "$log": {"type": "file"},
                    "$a": {"emits": {"$lgo": ""}},
                },
            }
        )


def test_relations_bad_direction_is_error():
    with pytest.raises(ValueError, match="direction"):
        parse({"relations": {"x": {"direction": "sideways"}}, "nodes": {}})


def test_relations_ref_axis_is_obsolete():
    """The old ref: key|value axis is gone -- references self-mark with $."""
    with pytest.raises(ValueError, match="ref"):
        parse({"relations": {"reads": {"direction": "in", "ref": "value"}}, "nodes": {}})


def test_default_type_falls_back_to_node():
    graph = parse({"nodes": {"$plain": {}}})
    assert _node(graph, "plain")["type"] == "node"


def test_defaults_block_types_children_by_parent_type():
    graph = parse(
        {
            "defaults": {"class": "method", "group": "function", "_root": "input"},
            "nodes": {
                "$untyped_root": {},
                "$C": {"type": "class", "$m": {}},
                "$g": {"type": "group", "$f": {}},
            },
        }
    )
    assert _node(graph, "untyped_root")["type"] == "input"
    assert _node(graph, "C.m")["type"] == "method"
    assert _node(graph, "g.f")["type"] == "function"


def test_defaults_chain_through_defaulted_parents():
    """A child's default keys off the parent's *resolved* type."""
    graph = parse(
        {
            "defaults": {"_root": "group", "group": "group"},
            "nodes": {"$outer": {"$inner": {"$leaf": {}}}},
        }
    )
    assert _node(graph, "outer")["type"] == "group"
    assert _node(graph, "outer.inner")["type"] == "group"
    assert _node(graph, "outer.inner.leaf")["type"] == "group"


def test_explicit_type_beats_defaults():
    graph = parse(
        {
            "defaults": {"group": "function"},
            "nodes": {"$g": {"type": "group", "$c": {"type": "class"}}},
        }
    )
    assert _node(graph, "g.c")["type"] == "class"
