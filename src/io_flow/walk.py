"""Walk a Python package into an io-flow YAML codebase map.

AST-walks every module under a package and emits an io-flow diagram whose nodes
carry the metadata a code reader wants in the sidebar:

    module   attributes   bases   args   returns   calls   modifies   source

Structure of the emitted YAML:
  * one ``group`` node per source file (``loc`` = its path)
  * ``class`` nodes (with ``attributes``/``bases``/``source``) whose methods are
    children
  * ``function`` nodes (with ``args``/``returns``/``source``) at file scope
  * every *resolved internal* call becomes an edge: same-file calls via the
    built-in ``calls:`` relation, cross-file calls via a registered ``xcall:``
    relation (so a skin can style them differently). Unresolved/external calls
    (``np.*``, ``self.x.append``, builtins) can't be edges but are listed under
    ``callees``.

io-flow reserves ``args``/``calls``/``returns`` as relation (edge) keys and
requires them dict-shaped, so the *display* metadata is emitted under safe keys
(``arg_names``/``return_exprs``/``callees``/...); a code-aware sidebar skin
labels them Args / Returns / Calls.

Driven by the ``io-flow walk`` subcommand (see cli.py). Depends only on the
stdlib and ruamel (already an io-flow dependency).
"""
from __future__ import annotations

import ast
import builtins
import textwrap
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.scalarstring import LiteralScalarString

_BUILTINS = set(dir(builtins))


# --------------------------------------------------------------------------- #
#  AST extraction (module / function / class / method -> metadata)
# --------------------------------------------------------------------------- #
def _call_base(call: ast.Call) -> str | None:
    """The bare name a call resolves to: foo() -> 'foo', np.array() -> 'array'."""
    f = call.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return None


def _dedupe(items):
    seen, out = set(), []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out


def _calls(node) -> list[str]:
    """Top-level call expressions in a body (not nested in another call's args),
    dropping builtins but keeping external-library calls."""
    out = []

    def visit(n):
        if isinstance(n, ast.Call):
            if _call_base(n) not in _BUILTINS:
                try:
                    out.append(ast.unparse(n))
                except Exception:
                    pass
            return  # don't descend into a call's own arguments
        for child in ast.iter_child_nodes(n):
            visit(child)

    for child in ast.iter_child_nodes(node):
        visit(child)
    return _dedupe(out)


def _flatten(target):
    if isinstance(target, (ast.Tuple, ast.List)):
        for elt in target.elts:
            yield from _flatten(elt)
    else:
        yield target


def _assign_targets(node):
    if isinstance(node, ast.Assign):
        for t in node.targets:
            yield from _flatten(t)
    elif isinstance(node, (ast.AugAssign, ast.AnnAssign)):
        yield from _flatten(node.target)


def _modifies(node) -> list[str]:
    """Attribute/subscript assignments in a body (self.x = ..., arr[i] = ...)."""
    out = []
    for child in ast.walk(node):
        if any(isinstance(t, (ast.Attribute, ast.Subscript)) for t in _assign_targets(child)):
            try:
                out.append(ast.unparse(child))
            except Exception:
                pass
    return _dedupe(out)


def _self_attrs(node) -> list[str]:
    out = []
    for child in ast.walk(node):
        for t in _assign_targets(child):
            if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "self":
                out.append(t.attr)
    return _dedupe(out)


def _args(fn) -> list[str]:
    names = [a.arg for a in fn.args.posonlyargs + fn.args.args]
    if fn.args.vararg:
        names.append("*" + fn.args.vararg.arg)
    names += [a.arg for a in fn.args.kwonlyargs]
    if fn.args.kwarg:
        names.append("**" + fn.args.kwarg.arg)
    return [a for a in names if a not in ("self", "cls")]


def _returns(fn) -> list[str]:
    out = []
    for n in ast.walk(fn):
        if isinstance(n, ast.Return) and n.value is not None:
            try:
                out.append(ast.unparse(n.value))
            except Exception:
                pass
    return _dedupe(out)


def _source(node, lines: list[str]) -> str:
    """Exact source of a def/class incl. decorators, dedented to column 0."""
    start = node.lineno
    if getattr(node, "decorator_list", None):
        start = min(start, min(d.lineno for d in node.decorator_list))
    seg = "\n".join(lines[start - 1 : node.end_lineno])
    return "\n".join(line.rstrip() for line in textwrap.dedent(seg).splitlines())


# --------------------------------------------------------------------------- #
#  Walk the package into a flat symbol list
# --------------------------------------------------------------------------- #
def walk(package_dir: Path, repo: Path) -> list[dict]:
    """One record per top-level function / class (+ its methods). ``loc``/``unit``
    are paths relative to ``repo`` (so ids read naturally, e.g. pkg/mod)."""
    syms: list[dict] = []
    for path in sorted(package_dir.rglob("*.py")):
        if "__pycache__" in path.parts or any(p.startswith(".") for p in path.parts):
            continue
        rel = path.relative_to(repo)
        unit = str(rel.with_suffix(""))                 # e.g. chromcov/io/track
        src = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        lines = src.splitlines()

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                syms.append({
                    "kind": "function", "name": node.name, "unit": unit, "loc": str(rel),
                    "args": _args(node), "returns": _returns(node),
                    "calls": _calls(node), "modifies": _modifies(node),
                    "source": _source(node, lines),
                })
            elif isinstance(node, ast.ClassDef):
                attrs = []
                for sub in node.body:
                    for t in _assign_targets(sub):
                        if isinstance(t, ast.Name):
                            attrs.append(t.id)
                methods = []
                for sub in node.body:
                    if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        attrs += _self_attrs(sub)
                        methods.append({
                            "kind": "method", "name": sub.name, "cls": node.name,
                            "unit": unit, "loc": str(rel),
                            "args": _args(sub), "returns": _returns(sub),
                            "calls": _calls(sub), "modifies": _modifies(sub),
                            "source": _source(sub, lines),
                        })
                syms.append({
                    "kind": "class", "name": node.name, "unit": unit, "loc": str(rel),
                    "bases": [ast.unparse(b) for b in node.bases],
                    "attributes": _dedupe(attrs), "methods": methods,
                    "source": _source(node, lines),
                })
    return syms


# --------------------------------------------------------------------------- #
#  Assign ids, resolve call edges, build the io-flow node tree
# --------------------------------------------------------------------------- #
def node_id(sym: dict) -> str:
    if sym["kind"] == "class":
        return sym["name"]
    if sym["kind"] == "method":
        return f"{sym['cls']}.{sym['name']}"
    return f"{Path(sym['unit']).name}.{sym['name']}"     # <stem>.<func>


def build_doc(syms: list[dict], title: str, no_edges: bool = False) -> tuple[dict, dict]:
    # id -> unit (file), and name -> [id] for call resolution
    unit_of: dict[str, str] = {}
    name_index: dict[str, list[str]] = {}
    methods_by_class: dict[str, dict[str, str]] = {}
    callables: list[dict] = []                            # {id, unit, calls, cls}

    def register(sym, cls):
        nid = node_id(sym)
        unit_of[nid] = sym["unit"]
        name_index.setdefault(sym["name"], []).append(nid)
        callables.append({"id": nid, "unit": sym["unit"],
                          "calls": sym.get("calls", []), "cls": cls})

    for sym in syms:
        if sym["kind"] == "function":
            register(sym, cls=None)
        elif sym["kind"] == "class":
            unit_of[sym["name"]] = sym["unit"]
            mmap = methods_by_class.setdefault(sym["name"], {})
            for m in sym["methods"]:
                mmap[m["name"]] = node_id(m)
                register(m, cls=sym["name"])

    # resolve each callable's calls -> {caller_id: {target_id: same_file?}}
    edges: dict[str, dict[str, bool]] = {}
    for c in callables:
        for call in c["calls"]:
            try:
                base = _call_base(ast.parse(call, mode="eval").body)
            except (SyntaxError, AttributeError):
                base = None
            if not base:
                continue
            target = None
            if c["cls"] and call.strip().startswith("self.") and c["cls"] in methods_by_class:
                target = methods_by_class[c["cls"]].get(base)
            if target is None:
                cands = name_index.get(base, [])
                if len(cands) == 1:
                    target = cands[0]
            if not target or target == c["id"]:
                continue
            edges.setdefault(c["id"], {})[target] = (unit_of.get(target) == c["unit"])

    def rel_blocks(nid: str) -> dict:
        """calls: (same-file) and xcall: (cross-file) $-ref dicts for a node."""
        out: dict[str, dict] = {}
        for tgt, same in sorted(edges.get(nid, {}).items()):
            out.setdefault("calls" if same else "xcall", {})[f"${tgt}"] = ""
        return out

    def leaf(sym: dict) -> dict:
        nid = node_id(sym)
        spec: dict = {"type": sym["kind"], "label": sym["name"],
                      "module": sym["unit"], "loc": sym["loc"]}
        if sym.get("args"):
            spec["arg_names"] = sym["args"]
        if sym.get("returns"):
            spec["return_exprs"] = sym["returns"]
        if sym.get("calls"):
            spec["callees"] = sym["calls"]
        if sym.get("modifies"):
            spec["modifies"] = sym["modifies"]
        if sym.get("bases"):
            spec["bases"] = sym["bases"]
        if sym.get("attributes"):
            spec["attributes"] = sym["attributes"]
        if not no_edges:
            spec.update(rel_blocks(nid))
        spec["source"] = LiteralScalarString(sym["source"])
        return spec

    # group nodes: one per file (unit), holding its classes + functions
    groups: dict[str, dict] = {}
    for sym in syms:
        unit = sym["unit"]
        g = groups.setdefault(unit, {"type": "group", "label": unit, "loc": f"{unit}.py"})
        spec = leaf(sym)
        if sym["kind"] == "class":
            for m in sym["methods"]:
                spec[f"${node_id(m)}"] = leaf(m)
        g[f"${node_id(sym)}"] = spec

    nodes = {f"${unit}": g for unit, g in sorted(groups.items())}

    doc = {"title": title}
    if not no_edges:
        # cross-file call (calls is built-in); no edges emitted -> no xcall usage
        doc["relations"] = {"xcall": {"direction": "out"}}
    if no_edges:
        # With no call edges the layered algorithm has nothing to flow, so every
        # (disconnected) file group stacks into one tall column. rectpacking
        # packs the groups into a grid honoring aspectRatio; members still lay
        # out inside each group and stacked classes stay stacked. Pure diagram
        # data -- the engine forwards `algorithm`/`elk` straight to ELK.
        diagram = {"algorithm": "rectpacking", "spacing": 40,
                   "elk": {"elk.aspectRatio": "1.6"}, "classLayout": None}
    else:
        diagram = {"direction": "RIGHT", "spacing": 40, "layerSpacing": 90,
                   "classLayout": None}
    doc.update({
        "defaults": {"group": "function", "class": "method", "_root": "node"},
        "diagram": diagram,
        "nodes": nodes,
    })
    stats = {"files": len(groups), "symbols": len(unit_of),
             "edges": 0 if no_edges else sum(len(v) for v in edges.values())}
    return doc, stats


def write_doc(doc: dict, out: Path) -> None:
    yaml = YAML()
    yaml.width = 4096
    yaml.default_flow_style = False
    with out.open("w", encoding="utf-8") as fh:
        yaml.dump(doc, fh)


def build_walk(repo: Path, package: str, title: str, out: Path,
               no_edges: bool = False) -> dict:
    """Walk ``repo/package`` and write the io-flow YAML to ``out``. Returns stats.

    ``no_edges`` emits nodes only (skips the call/xcall relation blocks), giving a
    pure hierarchy with all sidebar metadata intact but nothing connecting nodes."""
    syms = walk(repo / package, repo)
    doc, stats = build_doc(syms, title, no_edges=no_edges)
    write_doc(doc, out)
    return stats
