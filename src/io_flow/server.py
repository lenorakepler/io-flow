"""Localhost server for the primary ``io-flow edit`` loop.

Stdlib only. Serves the built HTML at ``/`` and accepts ``POST /save`` with
``{"positions": {id: [x, y]}}``. On save it merges positions into the source
YAML (comments preserved via :mod:`layout_store`), re-emits the HTML, and also
refreshes the on-disk ``diagram.html`` so the leftover file is always current.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import emit, layout_store
from .parser import parse_file


class _Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _send(self, code: int, body: bytes = b"", ctype: str = "text/html; charset=utf-8"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        if body:
            self.wfile.write(body)

    def do_GET(self):  # noqa: N802 (stdlib naming)
        app: "LayoutServer" = self.server.app  # type: ignore[attr-defined]
        if self.path.split("?")[0] in ("/", "/index.html", "/diagram.html"):
            self._send(200, app.html.encode("utf-8"))
        else:
            self._send(404, b"not found", "text/plain")

    def do_OPTIONS(self):  # noqa: N802
        # Capability ping from save.js.
        if self.path == "/save":
            self._send(204)
        else:
            self._send(404, b"", "text/plain")

    def do_POST(self):  # noqa: N802
        if self.path != "/save":
            self._send(404, b"not found", "text/plain")
            return
        app: "LayoutServer" = self.server.app  # type: ignore[attr-defined]
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b"{}"
        try:
            payload = json.loads(raw or b"{}")
            positions = payload.get("positions", payload)
            app.save(positions)
            self._send(200, b'{"ok":true}', "application/json")
        except Exception as exc:  # pragma: no cover - defensive
            body = json.dumps({"ok": False, "error": str(exc)}).encode("utf-8")
            self._send(500, body, "application/json")

    def log_message(self, *args):  # silence default request logging
        pass


class LayoutServer:
    def __init__(self, input_path: str | Path, host: str = "127.0.0.1", port: int = 8137):
        self.input_path = Path(input_path)
        self.host = host
        self.port = port
        self.html = ""
        self.out_path = self.input_path.with_suffix(".html")
        self._build()
        self.httpd = ThreadingHTTPServer((host, port), _Handler)
        self.httpd.app = self  # type: ignore[attr-defined]

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    def _build(self) -> None:
        graph = parse_file(self.input_path)
        layout_store.annotate_graph(graph, self.input_path)
        self.html = emit.build_html(graph)
        self.out_path.write_text(self.html, encoding="utf-8")

    def save(self, positions: dict) -> None:
        graph = parse_file(self.input_path)
        layout_store.merge_positions(self.input_path, graph, positions)
        self._build()

    def serve_forever(self) -> None:
        self.httpd.serve_forever()

    def shutdown(self) -> None:
        try:
            self.httpd.shutdown()
        except Exception:
            pass
        self.httpd.server_close()
