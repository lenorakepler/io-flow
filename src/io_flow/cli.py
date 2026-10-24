"""io-flow command-line interface.

Subcommands:
  build         compile YAML -> single-file diagram.html
  edit          build, serve on localhost, open browser (primary editing loop)
  check         parse only; report unresolved references (CI-friendly)
  apply-layout  merge a layout.json into the source YAML (no-server fallback)
  align         snap almost-aligned saved positions to exact columns/rows
  walk          walk a Python package into an io-flow YAML codebase map
  graphml       export to GraphML in yEd's format, to try yEd's layouts
  d2            export to D2 (https://d2lang.com)
  layout        lay the chart out with one of D2's engines (tala, elk, dagre) and save positions and routes into the YAML
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

from . import emit
from .parser import parse_file


def _build_graph(input_path: Path):
    from . import layout_store

    graph = parse_file(input_path)
    layout_store.annotate_graph(graph, graph.get("_layout_path") or input_path)
    return graph


def cmd_build(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    out = Path(args.output) if args.output else input_path.with_suffix(".html")
    graph = _build_graph(input_path)
    emit.write_html(
        graph, out, css=args.css, templates=args.templates, skin=args.skin
    )
    slim = " (elkjs omitted: all positions pinned)" if emit.elk_omitted(graph) else ""
    print(f"wrote {out} ({len(graph['nodes'])} nodes, {len(graph['edges'])} edges){slim}")
    return 0


def cmd_edit(args: argparse.Namespace) -> int:
    from . import server

    input_path = Path(args.input)
    srv = server.LayoutServer(
        input_path, host="127.0.0.1", port=args.port,
        css=args.css, templates=args.templates, skin=args.skin,
    )
    url = srv.url
    if srv.port != args.port:
        print(f"port {args.port} in use; using {srv.port} instead")
    print(f"serving {input_path} at {url}  (drag nodes, click Save, Ctrl-C to stop)")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped. diagram.html left in place.")
    finally:
        srv.shutdown()
    return 0


def cmd_check(args: argparse.Namespace) -> int:
    import warnings

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        graph = parse_file(Path(args.input))
    for w in caught:
        print(f"warning: {w.message}", file=sys.stderr)
    n_warn = len(caught)
    print(
        f"{args.input}: {len(graph['nodes'])} nodes, {len(graph['edges'])} edges, "
        f"{n_warn} warning{'s' if n_warn != 1 else ''}"
    )
    return 1 if (args.strict and caught) else 0


def cmd_apply_layout(args: argparse.Namespace) -> int:
    from . import layout_store

    input_path = Path(args.input)
    layout_json = Path(args.layout)
    import json

    positions = json.loads(layout_json.read_text(encoding="utf-8"))
    graph = parse_file(input_path)
    lp = Path(graph.get("_layout_path") or input_path)
    layout_store.merge_positions(lp, graph, positions)
    print(f"merged {len(positions)} positions into {lp}")
    return 0


def cmd_align(args: argparse.Namespace) -> int:
    from . import align, layout_store

    input_path = Path(args.input)
    graph = parse_file(input_path)
    lp = Path(graph.get("_layout_path") or input_path)
    saved = layout_store.read_layout(lp)
    if not saved or not saved.get("positions"):
        print(
            f"{lp}: no saved layout: block to align (drag + Save first)",
            file=sys.stderr,
        )
        return 1
    new_positions, moves = align.snap_positions(
        graph, saved["positions"], tolerance=args.tolerance
    )
    for nid, axis, old, new in moves:
        print(f"  {nid}: {axis} {old:g} -> {new:g}")
    if not moves:
        print(f"{lp}: already aligned (tolerance {args.tolerance:g}px)")
        return 0
    if args.dry_run:
        print(f"{lp}: {len(moves)} value(s) would move (dry run; file untouched)")
        return 0
    layout_store.merge_positions(lp, graph, new_positions)
    print(f"{input_path}: aligned {len(moves)} value(s) (tolerance {args.tolerance:g}px)")
    return 0


def cmd_walk(args: argparse.Namespace) -> int:
    from . import walk as walk_mod

    repo = Path(args.repo).resolve()
    package = args.package or repo.name
    package_dir = repo / package
    if not package_dir.is_dir():
        print(f"no package dir: {package_dir} (pass --package)", file=sys.stderr)
        return 1
    title = args.title or (package if repo.stem == package else f"{repo.stem} - {package}")
    out = Path(args.output) if args.output else Path.cwd() / f"{Path(package).name}.walked.yaml"
    stats = walk_mod.build_walk(repo, package, title, out, no_edges=args.no_edges)
    print(f"wrote {out} ({stats['files']} files, {stats['symbols']} symbols, "
          f"{stats['edges']} call edges)")
    return 0


def cmd_d2(args: argparse.Namespace) -> int:
    from . import d2

    graph = parse_file(Path(args.input))
    text, _ = d2.to_d2(graph, body=not args.no_body, legend=args.legend)
    out = Path(args.output) if args.output else Path(args.input).with_suffix(".d2")
    out.write_text(text, encoding="utf-8")
    print(f"wrote {out}")
    return 0


def cmd_layout(args: argparse.Namespace) -> int:
    from . import d2, layout_store

    path = Path(args.input)
    graph = parse_file(path)
    positions, routes = d2.run_layout(graph, engine=args.engine, body=not args.no_body, d2_bin=args.d2, keep_d2=Path(args.keep_d2) if args.keep_d2 else None)
    layout_store.merge_positions(graph.get("_layout_path") or path, graph, positions, None, routes)
    missing = [n["id"] for n in graph["nodes"] if n["id"] not in positions]
    print(f"{args.engine}: {len(positions)} nodes placed, {len(routes)} edges routed; layout saved into {path}" + (f"; not placed: {', '.join(missing)}" if missing else ""))
    if args.build:
        graph = _build_graph(path)
        out = Path(args.build)
        out.write_text(emit.build_html(graph), encoding="utf-8")
        print(f"wrote {out}")
    return 0


def cmd_graphml(args: argparse.Namespace) -> int:
    from . import graphml

    input_path = Path(args.input)
    out = Path(args.output) if args.output else input_path.with_suffix(".graphml")
    counts = graphml.write_graphml(parse_file(input_path), out)
    print(f"wrote {out} ({counts['nodes']} nodes, {counts['groups']} groups, "
          f"{counts['edges']} edges)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="io-flow", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    def add_skin_flags(sp):
        sp.add_argument("--css", help="project-local CSS replacing the packaged viewer.css")
        sp.add_argument(
            "--templates",
            help="project-local JS replacing the packaged templates.js, or a "
                 "directory of <type>.html Jinja node templates"
        )
        sp.add_argument(
            "--skin", action="append", metavar="NAME|FILE",
            help="skin layered on top: a bundled name (e.g. 'codemap') or a "
                 "local .css/.js/.sidebar.html file, or a literal CSS string "
                 "(anything containing '{') (repeatable; layered in order)"
        )

    b = sub.add_parser("build", help="compile YAML to a single-file diagram.html")
    b.add_argument("input", help="input YAML file")
    b.add_argument("-o", "--output", help="output HTML path (default: <input>.html)")
    add_skin_flags(b)
    b.set_defaults(func=cmd_build)

    e = sub.add_parser("edit", help="build + serve + open browser (primary loop)")
    e.add_argument("input", help="input YAML file")
    e.add_argument("--port", type=int, default=8137, help="localhost port")
    e.add_argument("--no-browser", action="store_true", help="don't auto-open a browser")
    add_skin_flags(e)
    e.set_defaults(func=cmd_edit)

    c = sub.add_parser("check", help="parse only; report unresolved references")
    c.add_argument("input", help="input YAML file")
    c.add_argument(
        "--strict", action="store_true", help="exit nonzero if any warnings are emitted"
    )
    c.set_defaults(func=cmd_check)

    a = sub.add_parser("apply-layout", help="merge a layout.json into the YAML")
    a.add_argument("input", help="input YAML file")
    a.add_argument("layout", help="layout JSON: {nodeId: [x, y]}")
    a.set_defaults(func=cmd_apply_layout)

    g = sub.add_parser(
        "align", help="snap almost-aligned saved positions to exact columns/rows"
    )
    g.add_argument("input", help="input YAML file (must have a saved layout: block)")
    g.add_argument(
        "--tolerance",
        type=float,
        default=8.0,
        help="cluster spread in px that counts as 'almost aligned' (default: 8)",
    )
    g.add_argument(
        "--dry-run", action="store_true", help="print what would move; don't write"
    )
    g.set_defaults(func=cmd_align)

    w = sub.add_parser("walk", help="walk a Python package into an io-flow YAML codebase map")
    w.add_argument("--repo", default=".", help="repo root to resolve paths against (default: CWD)")
    w.add_argument("--package", default=None, help="package dir under the repo (default: repo name)")
    w.add_argument(
        "--title", default=None,
        help="diagram title (default: '<repo> - <package>', or just one if they're equal)"
    )
    w.add_argument("-o", "--output", help="output YAML path (default: ./<package>.walked.yaml)")
    w.add_argument(
        "--no-edges", action="store_true",
        help="emit nodes only; skip call/xcall edges (pure hierarchy, metadata intact)"
    )
    w.set_defaults(func=cmd_walk)

    d = sub.add_parser("d2", help="export to D2 (https://d2lang.com)")
    d.add_argument("input")
    d.add_argument("-o", "--output")
    d.add_argument("--no-body", action="store_true", help="titles only; body text goes to the tooltip")
    d.add_argument("--legend", action="store_true", help="add a legend container with one sample per type")
    d.set_defaults(func=cmd_d2)

    lay = sub.add_parser("layout", help="lay out with a D2 engine and save positions and routes into the YAML")
    lay.add_argument("input")
    lay.add_argument("--engine", default="tala", choices=["tala", "elk", "dagre"], help="D2 layout engine (default tala)")
    lay.add_argument("--no-body", action="store_true", help="lay out with titles only, as if the body text were not on the canvas")
    lay.add_argument("--d2", default="d2", help="the d2 executable")
    lay.add_argument("--keep-d2", help="also write the D2 text here")
    lay.add_argument("--build", help="then build the HTML to this path")
    lay.set_defaults(func=cmd_layout)

    x = sub.add_parser(
        "graphml", help="export to GraphML in yEd's format, to try yEd's layouts"
    )
    x.add_argument("input", help="input YAML file")
    x.add_argument("-o", "--output", help="output GraphML path (default: <input>.graphml)")
    x.set_defaults(func=cmd_graphml)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
