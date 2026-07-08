"""server.py: live rebuild on GET, save merge, port fallback."""

from __future__ import annotations

import json
import threading
import urllib.error
import urllib.request

import pytest

from io_flow.server import LayoutServer

YAML = """\
# top comment that must survive
nodes:
  input:
    cfg:
      type: file   # inline comment
  functions:
    run:
      args:
        c: cfg
"""


@pytest.fixture()
def served(tmp_path):
    src = tmp_path / "d.yaml"
    src.write_text(YAML, encoding="utf-8")
    srv = LayoutServer(src, port=0)  # ephemeral port
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield src, srv
    finally:
        srv.shutdown()


def _get(srv, path="/"):
    with urllib.request.urlopen(srv.url.rstrip("/") + path) as r:
        return r.status, r.read().decode("utf-8")


def test_get_serves_built_html(served):
    _src, srv = served
    status, body = _get(srv)
    assert status == 200
    assert '"id": "run"' in body or '"id":"run"' in body


def test_get_rebuilds_after_yaml_edit(served):
    src, srv = served
    src.write_text(YAML + "    newfn: {}\n", encoding="utf-8")
    _status, body = _get(srv)
    assert "newfn" in body


def test_get_reports_parse_error_without_dying(served):
    src, srv = served
    src.write_text("nodes: [broken", encoding="utf-8")
    try:
        _get(srv)
        raise AssertionError("expected HTTP 500")
    except urllib.error.HTTPError as e:
        assert e.code == 500
        assert "build error" in e.read().decode("utf-8")
    # Server survives and recovers once the YAML is fixed.
    src.write_text(YAML, encoding="utf-8")
    status, _ = _get(srv)
    assert status == 200


def test_save_merges_positions_and_preserves_comments(served):
    src, srv = served
    payload = json.dumps({"positions": {"cfg": [10, 20], "run": [200, 20]}}).encode()
    req = urllib.request.Request(
        srv.url.rstrip("/") + "/save",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        assert json.loads(r.read())["ok"] is True
    text = src.read_text(encoding="utf-8")
    assert "# top comment that must survive" in text
    assert "# inline comment" in text
    assert "cfg: [10, 20]" in text
    assert "_topology:" in text


def test_version_changes_when_yaml_touched(served):
    src, srv = served
    _status, body = _get(srv, "/version")
    v1 = json.loads(body)["v"]
    src.write_text(YAML + "    another: {}\n", encoding="utf-8")
    _status, body = _get(srv, "/version")
    v2 = json.loads(body)["v"]
    assert v2 > v1


def test_error_page_carries_recovery_poller(served):
    src, srv = served
    src.write_text("nodes: [broken", encoding="utf-8")
    try:
        _get(srv)
        raise AssertionError("expected HTTP 500")
    except urllib.error.HTTPError as e:
        page = e.read().decode("utf-8")
    assert "/version" in page  # auto-recovers once the YAML is fixed


def test_port_conflict_falls_back_to_ephemeral(served, tmp_path):
    _src, srv = served
    src2 = tmp_path / "d2.yaml"
    src2.write_text(YAML, encoding="utf-8")
    srv2 = LayoutServer(src2, port=srv.port)  # deliberately collide
    try:
        assert srv2.port != srv.port
    finally:
        srv2.shutdown()
