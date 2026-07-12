"""io-flow command-line interface.

Subcommands:
  build         compile YAML -> single-file diagram.html
  edit          build, serve on localhost, open browser (primary editing loop)
  check         parse only; report unresolved references (CI-friendly)
  apply-layout  merge a layout.json into the source YAML (no-server fallback)
  align         snap almost-aligned saved positions to exact columns/rows
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
    layout_store.annotate_graph(graph, input_path)
    return graph


def cmd_build(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    out = Path(args.output) if args.output else input_path.with_suffix(".html")
    graph = _build_graph(input_path)
    emit.write_html(graph, out, css=args.css, templates=args.templates)
    slim = " (elkjs omitted: all positions pinned)" if emit.elk_omitted(graph) else ""
    print(f"wrote {out} ({len(graph['nodes'])} nodes, {len(graph['edges'])} edges){slim}")
    return 0


def cmd_edit(args: argparse.Namespace) -> int:
    from . import server

    input_path = Path(args.input)
    srv = server.LayoutServer(
        input_path, host="127.0.0.1", port=args.port, css=args.css, templates=args.templates
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
    layout_store.merge_positions(input_path, graph, positions)
    print(f"merged {len(positions)} positions into {input_path}")
    return 0


def cmd_align(args: argparse.Namespace) -> int:
    from . import align, layout_store

    input_path = Path(args.input)
    graph = parse_file(input_path)
    saved = layout_store.read_layout(input_path)
    if not saved or not saved.get("positions"):
        print(
            f"{input_path}: no saved layout: block to align (drag + Save first)",
            file=sys.stderr,
        )
        return 1
    new_positions, moves = align.snap_positions(
        graph, saved["positions"], tolerance=args.tolerance
    )
    for nid, axis, old, new in moves:
        print(f"  {nid}: {axis} {old:g} -> {new:g}")
    if not moves:
        print(f"{input_path}: already aligned (tolerance {args.tolerance:g}px)")
        return 0
    if args.dry_run:
        print(f"{input_path}: {len(moves)} value(s) would move (dry run; file untouched)")
        return 0
    layout_store.merge_positions(input_path, graph, new_positions)
    print(f"{input_path}: aligned {len(moves)} value(s) (tolerance {args.tolerance:g}px)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="io-flow", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    def add_skin_flags(sp):
        sp.add_argument("--css", help="project-local CSS replacing the packaged viewer.css")
        sp.add_argument(
            "--templates", help="project-local JS replacing the packaged templates.js"
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

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
