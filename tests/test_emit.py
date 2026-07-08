"""emit.py: single-file assembly, overrides, slim artifact."""

from __future__ import annotations

import json

import pytest

from io_flow import emit


def _graph(**extra):
    g = {
        "nodes": [
            {"id": "a", "type": "function", "parent": None, "label": "a", "data": {}},
        ],
        "edges": [],
    }
    g.update(extra)
    return g


def test_build_html_inlines_graph_and_all_scripts():
    html = emit.build_html(_graph(title="My <Diagram>"))
    # JSON island present and parseable (with the `<` escape undone by JSON).
    start = html.index('<script id="graph-data" type="application/json">')
    body = html[start:].split(">", 1)[1].split("</script")[0]
    assert json.loads(body)["nodes"][0]["id"] == "a"
    # Title is escaped.
    assert "<title>My &lt;Diagram&gt;</title>" in html
    # Every manifest script made it in (spot-check the bookends + new modules).
    for needle in ("panzoom", "IOF.templates", "IOF.collapse", "IOF.ui", "IOF.a11y"):
        assert needle in html
    # No CDN/network references (inline URLs inside vendored code are fine).
    assert "<script src=" not in html
    assert "<link" not in html
    assert "@import" not in html


def test_missing_engine_asset_raises(monkeypatch):
    monkeypatch.setattr(emit, "SCRIPT_MANIFEST", ["engine/does_not_exist.js"])
    with pytest.raises(FileNotFoundError):
        emit.build_html(_graph())


def test_elk_omitted_when_layout_restored():
    pinned = _graph(_layout={"mode": "restore", "positions": {"a": [0, 0]}, "notice": None})
    fresh = _graph(_layout={"mode": "elk", "positions": {}, "notice": None})
    slim = emit.build_html(pinned)
    full = emit.build_html(fresh)
    assert emit.elk_omitted(pinned) and not emit.elk_omitted(fresh)
    # elkjs is ~1.6 MB; the slim artifact must be dramatically smaller.
    assert len(slim) < len(full) / 2
    assert "ELK" in full


def test_css_and_templates_overrides(tmp_path):
    css = tmp_path / "skin.css"
    css.write_text(".node { background: hotpink; }", encoding="utf-8")
    tpl = tmp_path / "tpl.js"
    tpl.write_text("window.IOFlow = {}; /* custom templates */", encoding="utf-8")
    html = emit.build_html(_graph(), css=css, templates=tpl)
    assert "hotpink" in html
    assert "/* custom templates */" in html
    # The packaged templates were replaced, not appended.
    assert "USER-EDITABLE SURFACE" not in html
