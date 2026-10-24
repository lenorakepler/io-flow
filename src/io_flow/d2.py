"""D2 export and layout: write a chart as D2, run one of D2's engines (tala, elk, dagre), read every box and edge path back from the SVG, and hand them to the layout store.

`io-flow d2 CHART.yaml` writes the D2 text. `io-flow layout CHART.yaml --engine tala` runs D2 and saves the result as the chart's layout block: parent-relative `[x, y, w, h]` for every node and, under `_routes`, each edge's SVG path with its label position, so the viewer restores the engine's routes instead of drawing its own curves. D2 names every shape and edge in its SVG by the base64 of its id, which is what makes the read-back possible.

What carries over to D2: nodes and labels; groups as containers; relation edges with labels; the type styles, approximated (a CSS background is a fill, a border colour a stroke, a dashed border a dashed stroke, a pill a rounded box); the diagram direction; the body text under each title, wrapped; the description as a tooltip. What does not: regions, sankey, stacked lists, saved positions, anchors.
"""
from __future__ import annotations

import base64
import html
import re
import shutil
import subprocess
import tempfile
import textwrap
from pathlib import Path
from typing import Any

# Edge styles per relation name; anything else is a plain arrow.
EDGE_CLASSES = {
    "pass": {"stroke": "#16a34a"},
    "warn": {"stroke": "#d97706"},
    "fail": {"stroke": "#dc2626"},
    "unknown": {"stroke": "#94a3b8", "stroke-dash": "4"},
    "back": {"stroke": "#6b7280", "stroke-dash": "6"},
    "yes": {"stroke": "#16a34a"},
    "no": {"stroke": "#6b7280"},
}

CSS_PROP = re.compile(r"([\w-]+)\s*:\s*([^;]+)")
PAD = 16  # margin the normalised layout keeps at the top-left, like ELK's


# D2's reserved keywords; a node whose id is one gets a trailing underscore as its D2 key (the read-back maps keys to ids, so nothing else changes).
RESERVED = {"label", "desc", "shape", "icon", "constraint", "tooltip", "link", "near", "width", "height", "direction", "top", "left", "grid-rows", "grid-columns", "grid-gap", "vertical-gap", "horizontal-gap", "class", "classes", "vars", "style", "source-arrowhead", "target-arrowhead", "layers", "scenarios", "steps", "text", "code", "md", "latex"}


def ident(s: str) -> str:
    """A D2 key: letters, digits and underscores; reserved words get a trailing underscore."""
    k = re.sub(r"[^A-Za-z0-9_]", "_", s)
    return k + "_" if k.lower() in RESERVED else k


def _css_props(css: str) -> dict[str, str]:
    if not css or "{" in css:
        return {}
    return {k.strip(): v.strip() for k, v in CSS_PROP.findall(css)}


def _resolve(types: dict, name: str) -> dict[str, str]:
    """The merged CSS properties of a type, following extends; a group-derived type is marked."""
    chain, cur = [], name
    while cur and cur in types and cur not in chain:
        chain.append(cur)
        cur = (types[cur] or {}).get("extends")
    props: dict[str, str] = {}
    for t in reversed(chain):
        props.update(_css_props((types[t] or {}).get("css") or ""))
    props["_group"] = "1" if "group" in chain or cur == "group" else ""
    return props


def _var(props: dict[str, str], name: str) -> str | None:
    v = props.get(f"--{name}")
    return v if v and v.startswith("#") else None


def _style(props: dict[str, str]) -> dict[str, str]:
    """D2 style keys from the approximated CSS."""
    st: dict[str, str] = {}
    if props.get("_group"):
        return {"fill": _var(props, "group-light") or "#f8fafc", "stroke": _var(props, "group") or "#94a3b8"}
    bg = props.get("background-color")
    if bg and bg.startswith("#"):
        st["fill"] = bg
    stroke = _var(props, "src")
    border = props.get("border") or props.get("border-left") or ""
    m = re.search(r"#[0-9a-fA-F]{3,6}", border)
    if props.get("border-color", "").startswith("#"):
        stroke = props["border-color"]
    elif m and not stroke:
        stroke = m.group(0)
    if stroke:
        st["stroke"] = stroke
        st["stroke-width"] = "2"
    if "dashed" in border or "dashed" in props.get("border-style", ""):
        st["stroke-dash"] = "4"
    if "999" in props.get("border-radius", ""):
        st["border-radius"] = "20"
    if props.get("font-weight") in ("600", "700", "bold"):
        st["bold"] = "true"
    return st


def _q(text: Any) -> str:
    return '"' + str(text).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def _wrap(text: Any, width: int) -> str:
    return "\n".join(textwrap.wrap(" ".join(str(text).split()), width)) if text else ""


def _style_body(st: dict[str, str]) -> str:
    return "; ".join(f"{k}: {_q(v) if str(v).startswith('#') else v}" for k, v in st.items())


def to_d2(graph: dict, body: bool = True, legend: bool = False, direction: str | None = None, font_size: int = 14) -> tuple[str, list[tuple[str, str]]]:
    """The D2 text for a parsed graph, and the (source, target) pair of every edge written, in order.

    D2 numbers the edges between one pair of shapes in declaration order, `(a -> b)[k]`, so the k-th pair in the returned list is the edge D2 calls `[k]`.
    """
    types = graph.get("types") or {}
    nodes = graph["nodes"]
    by_id = {n["id"]: n for n in nodes}
    children: dict[str | None, list] = {}
    for n in nodes:
        children.setdefault(n.get("parent"), []).append(n)
    # io-flow's stacked lists (diagram: classLayout) become one-column grids, so D2 keeps the rows in order under each other.
    cl = (graph.get("diagram") or {}).get("classLayout")
    stacked = set(cl.get("types", ["class"]) if isinstance(cl, dict) else ["class"]) if cl not in (None, False) else set()

    def full(nid: str) -> str:
        parts, cur = [], nid
        while cur is not None:
            parts.append(ident(cur))
            cur = by_id[cur].get("parent")
        return ".".join(reversed(parts))

    out: list[str] = []
    out.append(f"# {graph.get('title') or 'chart'}")
    out.append("# Written by io-flow (io_flow.d2). Edit the YAML and export again, or edit this file from here on.")
    out.append(f"direction: {(direction or str((graph.get('diagram') or {}).get('direction') or 'RIGHT')).lower()}")
    out.append("")

    used = {n.get("type") for n in nodes if n.get("type")}
    out.append("classes: {")
    # io-flow sets a 14px title and 12px body; D2's default is 16px. Boxes are measured at 14px so the
    # io-flow text, which wraps at the box width, fits the box D2 sized (`font_size` to taste).
    for t in sorted(used):
        st = _style(_resolve(types, t))
        st.setdefault("font-size", str(font_size))
        out.append(f"  {ident(t)}: {{ style: {{ {_style_body(st)} }} }}")
    out.append(f'  io_flow_leaf: {{ style: {{ font-size: {font_size} }} }}')
    if legend:
        out.append('  legend_box: { style: { fill: "#ffffff"; stroke: "#94a3b8"; stroke-dash: 2; font-size: 13 } }')
    for rel, st in EDGE_CLASSES.items():
        out.append(f"  edge_{rel}: {{ style: {{ {_style_body(st)} }} }}")
    out.append("}")
    out.append("")

    def emit(n: dict, depth: int) -> None:
        ind = "  " * depth
        label = n.get("label") or n["id"]
        data = n.get("data") or {}
        text = label
        kids = children.get(n["id"], [])
        if body and data.get("body") and not kids:
            text = label + "\n" + _wrap(data["body"], 46)
        attrs = []
        attrs.append(f"class: {ident(n['type']) if n.get('type') else 'io_flow_leaf'}")
        tip = data.get("description") or (data.get("body") if kids else None)
        if tip:
            attrs.append(f"tooltip: {_q(tip)}")
        head = f"{ind}{ident(n['id'])}: {_q(text)}"
        if kids:
            out.append(head + " {")
            for a in attrs:
                out.append(f"{ind}  {a}")
            if n.get("type") in stacked:
                out.append(f"{ind}  grid-columns: 1")
            for k in kids:
                emit(k, depth + 1)
            out.append(f"{ind}}}")
        elif attrs:
            out.append(head + " { " + "; ".join(attrs) + " }")
        else:
            out.append(head)

    for n in children.get(None, []):
        emit(n, 0)
    out.append("")

    written: list[tuple[str, str]] = []
    for e in graph["edges"]:
        if e["source"] not in by_id or e["target"] not in by_id:
            continue
        rel = e.get("type") or ""
        line = f"{full(e['source'])} -> {full(e['target'])}"
        if e.get("label"):
            line += f": {_q(e['label'])}"
        if rel in EDGE_CLASSES:
            line += f" {{ class: edge_{rel} }}"
        out.append(line)
        written.append((e["source"], e["target"]))
    out.append("")

    lg = graph.get("legend") or {}
    if legend and lg:
        out.append(f"legend: {_q(lg.get('title') or 'legend')} {{")
        out.append("  class: legend_box")
        out.append("  direction: down")
        for i, item in enumerate(lg.get("nodes") or []):
            if isinstance(item, str):
                t, cap = item, item
            elif isinstance(item, dict) and "type" in item:
                t, cap = item["type"], item.get("label") or item["type"]
            else:
                t, cap = next(iter(item.items()))
            if t in used or t in types:
                out.append(f"  l{i}: {_q(cap)} {{ class: {ident(t)} }}")
        out.append("}")
    return "\n".join(out) + "\n", written


# ---- Reading the SVG back --------------------------------------------------------

_GROUP = re.compile(r'<g class="([A-Za-z0-9+/=]+)(?: [^"]*)?">')
_RECT = re.compile(r'<g class="shape" ?>\s*<(?:rect|ellipse|path|polygon)[^>]*?\bx="([-\d.]+)"[^>]*?\by="([-\d.]+)"[^>]*?\bwidth="([-\d.]+)"[^>]*?\bheight="([-\d.]+)"')
_PATH = re.compile(r'<path d="([^"]+)"[^>]*class="connection[^"]*"')
_LABEL = re.compile(r'<text [^>]*\bx="([-\d.]+)"[^>]*\by="([-\d.]+)"[^>]*>')
_EDGE_ID = re.compile(r"^(?:(?P<pre>.+?)\.)?\((?P<a>.+?) -> (?P<b>.+?)\)\[(?P<k>\d+)\]$")
_NUM = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")


def _decode(b64: str) -> str | None:
    try:
        return html.unescape(base64.b64decode(b64).decode("utf-8"))
    except Exception:
        return None


def read_svg(svg: str) -> tuple[dict[str, tuple[float, float, float, float]], dict[tuple[str, str, int], tuple[str, tuple[float, float] | None]]]:
    """Boxes `{d2 path: (x, y, w, h)}` and edges `{(d2 src, d2 tgt, k): (path d, label xy)}`, in the SVG's absolute coordinates."""
    starts = [m.start() for m in _GROUP.finditer(svg)]
    boxes: dict[str, tuple[float, float, float, float]] = {}
    edges: dict[tuple[str, str, int], tuple[str, tuple[float, float] | None]] = {}
    for i, s0 in enumerate(starts):
        seg = svg[s0 : starts[i + 1] if i + 1 < len(starts) else len(svg)]
        m = _GROUP.match(seg)
        name = _decode(m.group(1)) if m else None
        if not name:
            continue
        em = _EDGE_ID.match(name)
        if em:
            pm = _PATH.search(seg)
            if not pm:
                continue
            pre = em.group("pre")
            a = f"{pre}.{em.group('a')}" if pre else em.group("a")
            b = f"{pre}.{em.group('b')}" if pre else em.group("b")
            lm = _LABEL.search(seg[pm.end() :])
            label = (float(lm.group(1)), float(lm.group(2))) if lm else None
            edges[(a, b, int(em.group("k")))] = (pm.group(1), label)
            continue
        rm = _RECT.search(seg)
        if rm:
            boxes[name] = tuple(float(v) for v in rm.groups())  # type: ignore[assignment]
    return boxes, edges


def shift_path(d: str, dx: float, dy: float) -> str:
    """An SVG path with every coordinate moved; absolute M, L, C, Q, S, T, H, V and A commands (what D2 writes)."""
    out: list[str] = []
    cmd = None
    nums: list[str] = []

    def flush() -> None:
        if cmd is None:
            return
        vals = [float(v) for v in nums]
        res: list[str] = []
        if cmd in "H":
            res = [f"{v + dx:g}" for v in vals]
        elif cmd in "V":
            res = [f"{v + dy:g}" for v in vals]
        elif cmd == "A":
            for j in range(0, len(vals) - 6, 7):
                rx, ry, rot, la, sw, x, y = vals[j : j + 7]
                res += [f"{rx:g}", f"{ry:g}", f"{rot:g}", f"{la:g}", f"{sw:g}", f"{x + dx:g}", f"{y + dy:g}"]
        else:
            for j in range(0, len(vals) - 1, 2):
                res += [f"{vals[j] + dx:g}", f"{vals[j + 1] + dy:g}"]
        out.append(cmd + (" " + " ".join(res) if res else ""))

    for tok in re.finditer(r"[MLCQSTHVAZmlcqsthvaz]|" + _NUM.pattern, d):
        t = tok.group(0)
        if t.isalpha():
            flush()
            cmd, nums = t.upper(), []
            if cmd == "Z":
                out.append("Z")
                cmd = None
        else:
            nums.append(t)
    flush()
    return " ".join(out)


def run_layout(graph: dict, engine: str = "tala", body: bool = True, d2_bin: str = "d2", keep_d2: Path | None = None, font_size: int = 14) -> tuple[dict[str, list[float]], dict[str, list]]:
    """Run D2 on the graph and return `(positions, routes)` ready for the layout store.

    positions: `{node id: [x, y, w, h]}`, parent-relative like the viewer's; routes: `{"src>tgt#k": [path d, label x, label y]}` in the same canvas coordinates as the root positions.
    """
    exe = shutil.which(d2_bin)
    if not exe:
        raise SystemExit(f"{d2_bin} not found on PATH; install D2 from https://d2lang.com (TALA ships with it since v0.9)")
    text, written = to_d2(graph, body=body, legend=False, font_size=font_size)
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "chart.d2"
        svg_path = Path(td) / "chart.svg"
        src.write_text(text, encoding="utf-8")
        if keep_d2:
            Path(keep_d2).write_text(text, encoding="utf-8")
        proc = subprocess.run([exe, "--layout", engine, str(src), str(svg_path)], capture_output=True, text=True)
        if proc.returncode != 0:
            raise SystemExit(f"d2 failed ({engine}):\n{proc.stderr.strip()}")
        svg = svg_path.read_text(encoding="utf-8")
    boxes, svg_edges = read_svg(svg)

    nodes = graph["nodes"]
    by_id = {n["id"]: n for n in nodes}
    # D2 path <-> io-flow id. Ids are globally unique in io-flow, so the last path segment identifies the node.
    by_ident = {ident(n["id"]): n["id"] for n in nodes}
    abs_box: dict[str, tuple[float, float, float, float]] = {}
    for path, box in boxes.items():
        nid = by_ident.get(path.rsplit(".", 1)[-1])
        if nid:
            abs_box[nid] = box
    if not abs_box:
        raise SystemExit("no shapes found in D2's SVG; nothing to lay out")
    dx = PAD - min(b[0] for b in abs_box.values())
    dy = PAD - min(b[1] for b in abs_box.values())

    positions: dict[str, list[float]] = {}
    for nid, (x, y, w, h) in abs_box.items():
        parent = by_id[nid].get("parent")
        if parent and parent in abs_box:
            px, py = abs_box[parent][0], abs_box[parent][1]
            positions[nid] = [round(x - px, 1), round(y - py, 1), round(w, 1), round(h, 1)]
        else:
            positions[nid] = [round(x + dx, 1), round(y + dy, 1), round(w, 1), round(h, 1)]

    # Edge k between a pair, in D2's numbering, is the k-th edge between that pair we wrote.
    routes: dict[str, list] = {}
    seen: dict[tuple[str, str], int] = {}
    for src_id, tgt_id in written:
        k = seen.get((src_id, tgt_id), 0)
        seen[(src_id, tgt_id)] = k + 1
        key = None
        for (a, b, kk), val in svg_edges.items():
            if kk == k and by_ident.get(a.rsplit(".", 1)[-1]) == src_id and by_ident.get(b.rsplit(".", 1)[-1]) == tgt_id:
                key = (a, b, kk)
                break
        if key is None:
            continue
        d, label = svg_edges[key]
        entry: list = [shift_path(d, dx, dy)]
        if label:
            entry += [round(label[0] + dx, 1), round(label[1] + dy, 1)]
        routes[f"{src_id}>{tgt_id}#{k}"] = entry
    return positions, routes
