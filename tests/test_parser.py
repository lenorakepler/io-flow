"""Parser acceptance tests: the $-grammar produces the exact expected graph model."""

from __future__ import annotations

import warnings
from pathlib import Path

import pytest

from io_flow.parser import (
    UnmarkedReferenceWarning,
    UnusedDefaultWarning,
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
        ("limitparam", "attributes"),
        ("configfile", "from_yaml"),
        ("Config", "do_run"),
        ("skippreflight", "do_run"),
        # `calls:` edges point from the caller to the callee.
        ("do_run", "from_yaml"),
        ("do_run", "preflight"),
        # `returns:` edges point from the function to the returned-to node.
        ("do_run", "report"),
        # explicit top-level `edges:` entry (from -> to as written).
        ("preflight", "report"),
        # a call between two functions nested in a group (names stay flat).
        ("summarize", "plot"),
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

    attrs = _node(graph, "attributes")
    assert attrs["type"] == "attributes"
    assert attrs["parent"] == "Config"

    method = _node(graph, "from_yaml")
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


def test_dots_in_names_are_legal_and_meaningless():
    """Dots carry no structure -- they're a natural way to hand-uniquify
    common names ($Config.run vs $Runner.run)."""
    graph = parse(
        {
            "nodes": {
                "$Config": {"type": "class", "$Config.run": {"label": "run"}},
                "$Runner": {"type": "class", "$Runner.run": {"label": "run"}},
                "$f": {"calls": {"$Config.run": ""}},
            }
        }
    )
    assert _node(graph, "Config.run")["parent"] == "Config"
    assert _node(graph, "Runner.run")["parent"] == "Runner"
    assert ("f", "Config.run") in _edge_set(graph)


def test_duplicate_names_across_parents_are_an_error():
    """Names are one global namespace; nesting does not scope them."""
    from io_flow.parser import DuplicateNodeError

    with pytest.raises(DuplicateNodeError, match="run"):
        parse(
            {
                "nodes": {
                    "$Config": {"type": "class", "$run": {}},
                    "$Runner": {"type": "class", "$run": {}},
                }
            }
        )


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
    assert ("go", "helper", "step") in _labeled_edges(graph)


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
    assert ("go", "out", "result") in _labeled_edges(graph)


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


def test_numeric_annotation_is_a_weight_string_is_a_label():
    """The unmarked side of a key-side ref annotates by type."""
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        graph = parse(
            {
                "nodes": {
                    "$a": {"calls": {"$b": 42, "$c": "named"}},
                    "$b": {},
                    "$c": {},
                }
            }
        )
    edges = {(e["source"], e["target"]): e for e in graph["edges"]}
    assert edges[("a", "b")]["weight"] == 42
    assert "label" not in edges[("a", "b")]
    assert edges[("a", "c")]["label"] == "named"
    assert "weight" not in edges[("a", "c")]


def test_bool_annotation_is_neither_label_nor_weight():
    graph = parse({"nodes": {"$a": {"calls": {"$b": True}}, "$b": {}}})
    (edge,) = graph["edges"]
    assert "weight" not in edge and "label" not in edge


def test_explicit_edge_weight_passes_through():
    graph = parse(
        {
            "nodes": {"$a": {}, "$b": {}},
            "edges": [{"from": "$a", "to": "$b", "type": "passes", "weight": 3.5}],
        }
    )
    (edge,) = graph["edges"]
    assert edge["weight"] == 3.5


def test_explicit_edge_non_numeric_weight_is_error():
    with pytest.raises(ValueError, match="weight"):
        parse(
            {
                "nodes": {"$a": {}, "$b": {}},
                "edges": [{"from": "$a", "to": "$b", "weight": "heavy"}],
            }
        )


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
                            {"from": "$a", "to": "$b", "type": "passes", "label": "baton"},
                        ],
                    }
                }
            }
        )
    assert ("a", "b", "passes") in _labeled_edges_typed(graph)
    assert ("a", "b", "baton") in _labeled_edges(graph)
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
    # id stays the unique name; label carries the display name.
    assert _node(graph, "run_v2")["label"] == "run"
    # unlabeled node falls back to its name.
    assert _node(graph, "helper")["label"] == "helper"
    # nested label override.
    assert _node(graph, "go_fast")["label"] == "go"


def test_label_defaults_to_name():
    graph = parse({"nodes": {"$Runner": {"type": "class", "$go": {}}}})
    assert _node(graph, "go")["label"] == "go"


def test_any_node_with_children_is_a_compound_parent():
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        graph = parse(
            {
                "nodes": {
                    "$step1": {
                        "type": "group",
                        "loc": "s.py",
                        "$a": {"calls": {"$b": ""}},
                        "$b": {},
                    }
                }
            }
        )
    grp = _node(graph, "step1")
    assert grp["type"] == "group"
    assert grp["parent"] is None
    assert grp["data"].get("loc") == "s.py"  # unmarked keys become node data
    # members are parented to the group; names stay flat.
    assert _node(graph, "a")["parent"] == "step1"
    assert _node(graph, "b")["parent"] == "step1"
    # edges between members resolve by name.
    assert ("a", "b") in _edge_set(graph)


def test_nesting_is_recursive_and_ids_stay_flat():
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
    assert _node(graph, "top")["parent"] == "outer"
    assert _node(graph, "inner")["parent"] == "outer"
    assert _node(graph, "deep")["parent"] == "inner"
    assert _node(graph, "C")["parent"] == "inner"
    assert _node(graph, "m")["parent"] == "C"


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


def test_class_layout_config_passes_through():
    # A bare `classLayout:` (YAML null) must survive as a *present* key: the
    # viewer detects the mode with a presence check, not truthiness.
    graph = parse({"nodes": {"$a": {}}, "diagram": {"classLayout": None}})
    assert "classLayout" in graph["diagram"]
    assert graph["diagram"]["classLayout"] is None

    graph = parse(
        {"nodes": {"$a": {}}, "diagram": {"classLayout": {"types": ["class", "group"]}}}
    )
    assert graph["diagram"]["classLayout"]["types"] == ["class", "group"]


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


def test_explicit_edge_anchor_passes_through():
    graph = parse(
        {
            "nodes": {"$a": {}, "$b": {}},
            "edges": [{"from": "$a", "to": "$b", "anchor": {"from": "bottom", "to": "top"}}],
        }
    )
    assert graph["edges"][0]["anchor"] == {"from": "bottom", "to": "top"}


def test_relation_anchor_stamps_derived_and_explicit_edges():
    graph = parse(
        {
            "relations": {
                "inherits": {"direction": "out", "anchor": {"from": "top", "to": "bottom"}}
            },
            "nodes": {
                "$base": {},
                "$derived": {"inherits": {"$base": ""}},
                "$other": {},
            },
            # A typed explicit edge inherits the relation's default anchor...
            "edges": [
                {"from": "$other", "to": "$base", "type": "inherits"},
                # ...unless it declares its own.
                {"from": "$other", "to": "$derived", "type": "inherits", "anchor": {"to": "left"}},
            ],
        }
    )
    anchors = {(e["source"], e["target"]): e.get("anchor") for e in graph["edges"]}
    assert anchors[("derived", "base")] == {"from": "top", "to": "bottom"}
    assert anchors[("other", "base")] == {"from": "top", "to": "bottom"}
    assert anchors[("other", "derived")] == {"to": "left"}


def test_anchor_validation_is_loud():
    with pytest.raises(ValueError, match="anchor"):
        parse(
            {
                "nodes": {"$a": {}, "$b": {}},
                "edges": [{"from": "$a", "to": "$b", "anchor": {"from": "middle"}}],
            }
        )
    with pytest.raises(ValueError, match="anchor"):
        parse({"relations": {"x": {"anchor": {"sideways": "left"}}}, "nodes": {}})
    with pytest.raises(ValueError, match="anchor"):
        parse({"relations": {"x": {"anchor": {}}}, "nodes": {}})


def test_default_type_falls_back_to_node():
    graph = parse({"nodes": {"$plain": {}}})
    assert _node(graph, "plain")["type"] == "node"


def test_untyped_nodes_fall_back_to_what_they_structurally_are():
    """Children -> `group`, none -> `node`; a `defaults:` entry still wins."""
    graph = parse(
        {
            "nodes": {
                "$holder": {"$leaf": {}},
                "$listing": {"steps": ["one"]},
                "$alone": {},
            }
        }
    )
    assert _node(graph, "holder")["type"] == "group"
    assert _node(graph, "listing")["type"] == "group"
    assert _node(graph, "alone")["type"] == "node"
    assert _node(graph, "leaf")["type"] == "node"
    typed = parse({"defaults": {"_root": "platform"}, "nodes": {"$h": {"$k": {}}}})
    assert _node(typed, "h")["type"] == "platform"


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
    assert _node(graph, "m")["type"] == "method"
    assert _node(graph, "f")["type"] == "function"


def test_defaults_chain_through_defaulted_parents():
    """A child's default keys off the parent's *resolved* type."""
    graph = parse(
        {
            "defaults": {"_root": "group", "group": "group"},
            "nodes": {"$outer": {"$inner": {"$leaf": {}}}},
        }
    )
    assert _node(graph, "outer")["type"] == "group"
    assert _node(graph, "inner")["type"] == "group"
    assert _node(graph, "leaf")["type"] == "group"


def test_childtype_types_a_type_s_untyped_children():
    """The `defaults:` mapping, said in the declaration that owns it."""
    graph = parse(
        {
            "types": {
                "dir": {"extends": "group", "childtype": "dir"},
                "vault": {"extends": "dir"},  # inherited like any other field
            },
            "nodes": {
                "$projects": {"type": "dir", "$prj1": {}, "$prj2": {"type": "file"}},
                "$v": {"type": "vault", "$inner": {}},
            },
        }
    )
    assert _node(graph, "prj1")["type"] == "dir"
    assert _node(graph, "prj2")["type"] == "file"  # explicit type still wins
    assert _node(graph, "inner")["type"] == "dir"


def test_defaults_beats_childtype():
    """`defaults:` is this diagram overriding a shared declaration."""
    graph = parse(
        {
            "types": {"dir": {"childtype": "dir"}},
            "defaults": {"dir": "file"},
            "nodes": {"$d": {"type": "dir", "$kid": {}}},
        }
    )
    assert _node(graph, "kid")["type"] == "file"


def test_defaults_key_that_names_a_node_warns():
    """`projects: dir` reads right and does nothing; keys are parent types."""
    doc = {
        "defaults": {"projects": "dir"},
        "nodes": {"$projects": {"type": "dir", "$prj1": {}}},
    }
    with pytest.warns(UnusedDefaultWarning, match=r"\$projects is a node name"):
        graph = parse(doc)
    assert _node(graph, "prj1")["type"] == "node"  # unchanged: the key never applied
    # The type-keyed version is silent, and works.
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        fixed = parse({**doc, "defaults": {"dir": "dir"}})
    assert _node(fixed, "prj1")["type"] == "dir"


def test_explicit_type_beats_defaults():
    graph = parse(
        {
            "defaults": {"group": "function"},
            "nodes": {"$g": {"type": "group", "$c": {"type": "class"}}},
        }
    )
    assert _node(graph, "c")["type"] == "class"


def test_steps_number_children_by_position():
    """`steps:` trades per-node ids for order: id is parent + index."""
    graph = parse(
        {
            "nodes": {
                "$stages": {
                    "type": "steps",
                    "steps": [
                        "Project Setup",                      # bare string: the label
                        {"label": "Ingestion", "$sub": {}},   # a step is a node spec
                        {"label": "Eval", "type": "urgent", "number": 99},
                    ],
                },
                "$runner": {"calls": {"$stages1": ""}},       # addressable by position
            }
        }
    )
    ids = [n["id"] for n in graph["nodes"]]
    assert ids[:4] == ["stages", "stages0", "stages1", "sub"]  # declaration order kept
    assert _node(graph, "stages0")["label"] == "Project Setup"
    assert [_node(graph, f"stages{i}")["data"]["number"] for i in range(3)] == [0, 1, 99]
    assert _node(graph, "sub")["parent"] == "stages1"
    # Untyped steps land on `step`; the item's own type still wins.
    assert _node(graph, "stages0")["type"] == "step"
    assert _node(graph, "stages2")["type"] == "urgent"
    assert ("runner", "stages1") in _edge_set(graph)
    # The list itself is wiring, not sidebar data.
    assert "steps" not in _node(graph, "stages")["data"]


def test_defaults_beat_the_step_fallback():
    graph = parse(
        {
            "defaults": {"steps": "stage"},
            "nodes": {"$s": {"type": "steps", "steps": ["one"]}},
        }
    )
    assert _node(graph, "s0")["type"] == "stage"


def test_steps_must_be_a_list():
    with pytest.raises(ValueError, match="steps: must be a list"):
        parse({"nodes": {"$s": {"steps": {"label": "one"}}}})


def test_autoedges_chains_the_steps_in_order():
    graph = parse(
        {
            "nodes": {
                "$s": {"autoedges": True, "steps": ["one", "two", "three"]},
                "$t": {"autoedges": "then", "steps": ["a", "b"]},
            }
        }
    )
    assert _labeled_edges_typed(graph) == {
        ("s0", "s1", "next"),
        ("s1", "s2", "next"),
        ("t0", "t1", "then"),  # a string names the edge type
    }
    assert "autoedges" not in _node(graph, "s")["data"]


def test_autoedges_without_steps_is_an_error():
    with pytest.raises(ValueError, match="autoedges: only means something"):
        parse({"nodes": {"$s": {"autoedges": True}}})


def test_legend_accepts_every_spelling():
    graph = parse(
        {
            "legend": {
                "title": "what things are",
                "nodes": [
                    "file",                                    # bare name
                    {"dir": "a directory"},                    # one-key caption
                    {"type": "option", "label": "a flag", "cli": "--v"},  # full spec
                ],
                "edges": {"calls": "who calls whom"},          # mapping form
            },
            "nodes": {"$a": {}},
        }
    )
    assert graph["legend"]["title"] == "what things are"
    assert [(e["type"], e["label"]) for e in graph["legend"]["nodes"]] == [
        ("file", "file"),          # caption defaults to the type name
        ("dir", "a directory"),
        ("option", "a flag"),
    ]
    assert graph["legend"]["nodes"][2]["cli"] == "--v"  # data reaches the sample
    assert graph["legend"]["edges"] == [{"type": "calls", "label": "who calls whom"}]


def test_legend_rejects_typos_and_entries_without_a_type():
    with pytest.raises(ValueError, match="unknown key"):
        parse({"legend": {"noeds": ["file"]}, "nodes": {"$a": {}}})
    with pytest.raises(ValueError, match="each entry needs a type"):
        parse({"legend": {"nodes": [{"label": "no type here"}]}, "nodes": {"$a": {}}})
    with pytest.raises(ValueError, match="must be a list or a mapping"):
        parse({"legend": {"nodes": "file"}, "nodes": {"$a": {}}})


def test_style_block_parsed_and_validated():
    graph = parse({"style": {"skin": "codemap"}, "nodes": {"$a": {}}})
    assert graph["style"] == {"skin": ["codemap"]}
    # Unknown keys are a loud error (typo protection).
    with pytest.raises(ValueError, match="unknown key.*colour"):
        parse({"style": {"colour": "x.css"}, "nodes": {"$a": {}}})
    # No style block -> no style key at all.
    assert "style" not in parse({"nodes": {"$a": {}}})


def test_style_css_path_resolves_relative_to_yaml(tmp_path):
    (tmp_path / "theme.css").write_text(".node {}", encoding="utf-8")
    (tmp_path / "diag.yaml").write_text(
        "style: {css: theme.css}\nnodes: {$a: {}}\n", encoding="utf-8"
    )
    graph = parse_file(tmp_path / "diag.yaml")
    # skin stays a bare name; css becomes an absolute path next to the YAML.
    assert graph["style"]["css"] == str(tmp_path / "theme.css")


def test_style_skin_list_parsed_and_validated():
    g = parse({"style": {"skin": ["codemap", "over.css"]}, "nodes": {"$a": {}}})
    assert g["style"]["skin"] == ["codemap", "over.css"]
    # A non-string entry is a loud error.
    with pytest.raises(ValueError, match="skin"):
        parse({"style": {"skin": [1, 2]}, "nodes": {"$a": {}}})


def test_style_skin_files_resolve_relative_to_yaml_but_names_dont(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "x.css").write_text(".n {}", encoding="utf-8")
    (tmp_path / "d.yaml").write_text(
        "style: {skin: [codemap, sub/x.css, extra.js]}\nnodes: {$a: {}}\n",
        encoding="utf-8",
    )
    g = parse_file(tmp_path / "d.yaml")
    assert g["style"]["skin"] == [
        "codemap",
        str(tmp_path / "sub" / "x.css"),
        str(tmp_path / "extra.js"),
    ]


def test_descriptors_synthesize_a_first_child_from_a_field():
    """A registered `descriptors:` field becomes a synthetic child box."""
    graph = parse(
        {
            "descriptors": {"description": "desc"},
            "nodes": {
                "$a": {
                    "type": "group",
                    "description": "hello",
                    "$real": {"type": "file"},
                },
            },
        }
    )
    child = _node(graph, "a.description")
    assert child["type"] == "desc"
    assert child["parent"] == "a"
    assert child["data"]["text"] == "hello"
    # Emitted before the real child, so it lays out first.
    ids = [n["id"] for n in graph["nodes"]]
    assert ids.index("a.description") < ids.index("real")
    # The field still rides along on the parent (sidebar keeps it).
    assert _node(graph, "a")["data"]["description"] == "hello"


def test_descriptors_only_fire_when_registered_and_present():
    # No descriptors block: description stays plain data, no synthetic child.
    g = parse({"nodes": {"$a": {"description": "x"}}})
    assert not any(n["id"] == "a.description" for n in g["nodes"])
    # Registered but field absent on a node: nothing synthesized.
    g = parse({"descriptors": {"description": "desc"}, "nodes": {"$a": {}}})
    assert not any(n["id"] == "a.description" for n in g["nodes"])


def test_descriptors_must_be_a_mapping():
    with pytest.raises(ValueError, match="descriptors: must be a mapping"):
        parse({"descriptors": ["description"], "nodes": {"$a": {}}})


def test_descriptors_id_collision_is_a_loud_error():
    from io_flow.parser import DuplicateNodeError

    with pytest.raises(DuplicateNodeError):
        parse(
            {
                "descriptors": {"description": "desc"},
                "nodes": {
                    "$a": {"description": "x", "$a.description": {"type": "file"}},
                },
            }
        )


def test_types_from_external_file(tmp_path):
    (tmp_path / "types.yaml").write_text(
        "box: {title: '[[ {{ label }} ]]', badge: b}\n", encoding="utf-8"
    )
    (tmp_path / "d.yaml").write_text(
        "types: types.yaml\nnodes: {$a: {type: box}}\n", encoding="utf-8"
    )
    g = parse_file(tmp_path / "d.yaml")
    assert g["types"]["box"]["badge"] == "b"
    assert _node(g, "a")["type"] == "box"


def test_types_from_list_of_files_and_inline_last_wins(tmp_path):
    (tmp_path / "base.yaml").write_text("box: {badge: base}\n", encoding="utf-8")
    (tmp_path / "d.yaml").write_text(
        "types:\n  - base.yaml\n  - {box: {badge: override}}\n"
        "nodes: {$a: {type: box}}\n",
        encoding="utf-8",
    )
    g = parse_file(tmp_path / "d.yaml")
    assert g["types"]["box"]["badge"] == "override"


def test_types_inline_mapping_still_works(tmp_path):
    (tmp_path / "d.yaml").write_text(
        "types: {box: {badge: inline}}\nnodes: {$a: {type: box}}\n", encoding="utf-8"
    )
    g = parse_file(tmp_path / "d.yaml")
    assert g["types"]["box"]["badge"] == "inline"


def test_types_missing_file_is_an_error(tmp_path):
    (tmp_path / "d.yaml").write_text("types: nope.yaml\nnodes: {$a: {}}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="file not found"):
        parse_file(tmp_path / "d.yaml")


def test_src_embeds_file_contents(tmp_path):
    (tmp_path / "hello.py").write_text("print('hi')\n", encoding="utf-8")
    (tmp_path / "d.yaml").write_text(
        "nodes: {$a: {type: file, src: hello.py}}\n", encoding="utf-8"
    )
    g = parse_file(tmp_path / "d.yaml")
    fc = g["fileContents"]["a"]
    assert fc["name"] == "hello.py"
    assert fc["lang"] == "python"
    assert fc["text"] == "print('hi')\n"
    assert fc["truncated"] is False


def test_src_missing_file_errors(tmp_path):
    (tmp_path / "d.yaml").write_text("nodes: {$a: {src: nope.py}}\n", encoding="utf-8")
    with pytest.raises(ValueError, match="src: file not found"):
        parse_file(tmp_path / "d.yaml")


def test_src_without_base_dir_is_plain_data():
    # parse() called directly (no file context) leaves src as data, no embedding.
    g = parse({"nodes": {"$a": {"src": "x.py"}}})
    assert "fileContents" not in g
    assert _node(g, "a")["data"]["src"] == "x.py"


def test_node_group_field_flows_to_its_edges():
    # A node's `group:` is inherited by its in-block edges (explicit + relation).
    g = parse({
        "relations": {"reads": {"direction": "in"}},
        "nodes": {
            "$a": {"group": "g1", "edges": [{"to": "$b", "type": "x"}], "reads": {"$c": ""}},
            "$b": {}, "$c": {},
        },
    })
    x = [e for e in g["edges"] if e.get("type") == "x"][0]
    r = [e for e in g["edges"] if e.get("type") == "reads"][0]
    assert x["group"] == "g1"
    assert r["group"] == "g1"  # relation-block edge inherits it too


def test_node_without_group_gives_ungrouped_edges():
    g = parse({"nodes": {"$a": {"edges": [{"to": "$b", "type": "x"}]}, "$b": {}}})
    e = [e for e in g["edges"] if e.get("type") == "x"][0]
    assert "group" not in e


def test_explicit_group_overrides_owner():
    g = parse({"nodes": {"$a": {"edges": [{"to": "$b", "type": "x", "group": "G"}]}, "$b": {}}})
    e = [e for e in g["edges"] if e.get("type") == "x"][0]
    assert e["group"] == "G"


def test_top_level_edge_has_no_group():
    g = parse({"nodes": {"$a": {}, "$b": {}}, "edges": [{"from": "$a", "to": "$b"}]})
    assert "group" not in g["edges"][0]


def test_legend_groups_parsed():
    g = parse({
        "nodes": {"$a": {}},
        "legend": {"groups": [{"group": "stage0", "label": "Stage 0"}, "stage1"]},
    })
    groups = g["legend"]["groups"]
    assert groups[0] == {"group": "stage0", "label": "Stage 0"}
    assert groups[1] == {"group": "stage1", "label": "stage1"}


def test_relation_block_group_overrides_node_group():
    g = parse({
        "relations": {"reads": {"direction": "in"}, "creates": {"direction": "out"},
                      "drives": {"direction": "out"}},
        "nodes": {
            "$s": {
                "group": "nodeg",
                "drives": {"$st": ""},                 # ungrouped-in-block? gets node group
                "creates": {"group": "g6", "$e": ""},  # block group wins
            },
            "$st": {}, "$e": {},
        },
    })
    drives = [e for e in g["edges"] if e["type"] == "drives"][0]
    creates = [e for e in g["edges"] if e["type"] == "creates"][0]
    assert drives["group"] == "nodeg"   # inherits node group (no block group)
    assert creates["group"] == "g6"     # block group overrides node group
