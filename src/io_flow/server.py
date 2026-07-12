"""Localhost server for the primary ``io-flow edit`` loop.

Stdlib only. Serves the built HTML at ``/`` and accepts ``POST /save`` with
``{"positions": {id: [x, y]}, "new_edges"?: [{from, to, type?, label?}]}``.
The HTML is rebuilt from the source YAML on every GET, so editing the YAML
and refreshing the browser is a live loop; a parse failure serves the error
as plain text instead of killing the server. On save it appends any
browser-created connections to the YAML's ``edges:`` list (append-only, via
:mod:`edge_store`), merges positions (comments preserved via
:mod:`layout_store`), re-emits the HTML, and also refreshes the on-disk
``diagram.html`` so the leftover file is always current.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import html as _html

from . import edge_store, emit, layout_store
from .parser import parse_file


def _error_page(input_path: Path, exc: Exception) -> str:
    """Build-error page. Carries the same /version poller as live.js so the
    browser recovers by itself once the YAML parses again."""
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>io-flow build error</title></head>
<body style="font: 14px/1.5 ui-monospace, monospace; padding: 2em; color: #92400e; background: #fffbeb">
<h1 style="font-size: 16px">io-flow build error in {_html.escape(str(input_path))}</h1>
<pre style="white-space: pre-wrap">{_html.escape(str(exc))}</pre>
<p style="color: #6b7280">Watching for changes… this page reloads when the file is fixed.</p>
<script>
(function () {{
  var baseline = null;
  setInterval(function () {{
    fetch("/version", {{ cache: "no-store" }}).then(function (r) {{ return r.json(); }})
      .then(function (j) {{
        if (baseline === null) baseline = j.v;
        else if (j.v !== baseline) location.reload();
      }}).catch(function () {{}});
  }}, 1000);
}})();
</script>
</body></html>"""


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
        path = self.path.split("?")[0]
        if path in ("/", "/index.html", "/diagram.html"):
            try:
                app.rebuild()
            except Exception as exc:
                self._send(500, _error_page(app.input_path, exc).encode("utf-8"))
                return
            self._send(200, app.html.encode("utf-8"))
        elif path == "/version":
            body = json.dumps({"v": app.version()}).encode("utf-8")
            self._send(200, body, "application/json")
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
            new_edges = payload.get("new_edges") if isinstance(payload, dict) else None
            app.save(positions, new_edges)
            self._send(200, b'{"ok":true}', "application/json")
        except Exception as exc:  # pragma: no cover - defensive
            body = json.dumps({"ok": False, "error": str(exc)}).encode("utf-8")
            self._send(500, body, "application/json")

    def log_message(self, *args):  # silence default request logging
        pass


class LayoutServer:
    def __init__(
        self,
        input_path: str | Path,
        host: str = "127.0.0.1",
        port: int = 8137,
        css: str | Path | None = None,
        templates: str | Path | None = None,
    ):
        self.input_path = Path(input_path)
        self.host = host
        self.css = css
        self.templates = templates
        self.html = ""
        self.out_path = self.input_path.with_suffix(".html")
        self.rebuild()
        try:
            self.httpd = ThreadingHTTPServer((host, port), _Handler)
        except OSError:
            # Requested port taken (another `io-flow edit`?) -- fall back to an
            # ephemeral port; callers read the real one back from `self.port`.
            self.httpd = ThreadingHTTPServer((host, 0), _Handler)
        self.port = self.httpd.server_address[1]
        self.httpd.app = self  # type: ignore[attr-defined]

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}/"

    def version(self) -> int:
        """Change token for the live-reload poll: newest mtime of the source
        YAML and any skin overrides, so editing those reloads the browser too."""
        newest = 0
        for p in (self.input_path, self.css, self.templates):
            if p is None:
                continue
            try:
                newest = max(newest, Path(p).stat().st_mtime_ns)
            except OSError:
                continue
        return newest

    def rebuild(self) -> None:
        graph = parse_file(self.input_path)
        layout_store.annotate_graph(graph, self.input_path)
        self.html = emit.build_html(graph, css=self.css, templates=self.templates)
        self.out_path.write_text(self.html, encoding="utf-8")

    def save(self, positions: dict, new_edges: list | None = None) -> None:
        # Append edges first, then re-parse so the merged topology hash covers
        # them -- otherwise the next load would see a "changed" topology.
        if new_edges:
            edge_store.append_edges(self.input_path, parse_file(self.input_path), new_edges)
        graph = parse_file(self.input_path)
        layout_store.merge_positions(self.input_path, graph, positions)
        self.rebuild()

    def serve_forever(self) -> None:
        self._serving = True
        self.httpd.serve_forever()

    def shutdown(self) -> None:
        # socketserver's shutdown() blocks on an event that only a running
        # serve_forever() loop ever sets -- calling it on a server that never
        # served deadlocks. Only close the socket in that case.
        if getattr(self, "_serving", False):
            try:
                self.httpd.shutdown()
            except Exception:
                pass
        self.httpd.server_close()
