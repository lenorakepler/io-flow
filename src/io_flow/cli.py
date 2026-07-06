"""io-flow command-line interface.

Subcommands:
  build         compile YAML -> single-file diagram.html
  edit          build, serve on localhost, open browser (primary editing loop)
  apply-layout  merge a layout.json into the source YAML (no-server fallback)
"""

from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

from . import emit
from .parser import parse_file


def _build_graph(input_path: Path):
    graph = parse_file(input_path)
    # Layout policy (topology hash) is applied here once layout_store exists.
    try:
        from . import layout_store

        layout_store.annotate_graph(graph, input_path)
    except Exception:
        # Layout persistence is optional for a plain build.
        pass
    return graph


def cmd_build(args: argparse.Namespace) -> int:
    input_path = Path(args.input)
    out = Path(args.output) if args.output else input_path.with_suffix(".html")
    graph = _build_graph(input_path)
    emit.write_html(graph, out)
    print(f"wrote {out} ({len(graph['nodes'])} nodes, {len(graph['edges'])} edges)")
    return 0


def cmd_edit(args: argparse.Namespace) -> int:
    from . import server

    input_path = Path(args.input)
    srv = server.LayoutServer(input_path, host="127.0.0.1", port=args.port)
    url = srv.url
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="io-flow", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    b = sub.add_parser("build", help="compile YAML to a single-file diagram.html")
    b.add_argument("input", help="input YAML file")
    b.add_argument("-o", "--output", help="output HTML path (default: <input>.html)")
    b.set_defaults(func=cmd_build)

    e = sub.add_parser("edit", help="build + serve + open browser (primary loop)")
    e.add_argument("input", help="input YAML file")
    e.add_argument("--port", type=int, default=8137, help="localhost port")
    e.add_argument("--no-browser", action="store_true", help="don't auto-open a browser")
    e.set_defaults(func=cmd_edit)

    a = sub.add_parser("apply-layout", help="merge a layout.json into the YAML")
    a.add_argument("input", help="input YAML file")
    a.add_argument("layout", help="layout JSON: {nodeId: [x, y]}")
    a.set_defaults(func=cmd_apply_layout)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
