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
    for needle in ("panzoom", "IOF.renderNode", "IOF.collapse", "IOF.ui", "IOF.a11y"):
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


def test_yaml_style_block_drives_build(tmp_path):
    css = tmp_path / "theme.css"
    css.write_text("/* MARK */ .node { color: teal; }", encoding="utf-8")
    html = emit.build_html(_graph(style={"css": str(css)}))
    assert "/* MARK */" in html
    # The style block itself must not leak into the embedded viewer JSON.
    start = html.index('<script id="graph-data" type="application/json">')
    body = html[start:].split(">", 1)[1].split("</script")[0]
    assert "style" not in json.loads(body)


def test_local_skin_files_append_and_keep_base(tmp_path):
    one = tmp_path / "a.css"
    one.write_text("/* EXTRA-A */", encoding="utf-8")
    two = tmp_path / "b.css"
    two.write_text("/* EXTRA-B */", encoding="utf-8")
    js = tmp_path / "s.js"
    js.write_text("/* EXTRA-JS */", encoding="utf-8")
    html = emit.build_html(_graph(), skin=[str(one), str(two), str(js)])
    # Base viewer.css is NOT replaced (unlike css=), and every entry is present.
    assert "--header-h" in html  # a distinctive base viewer.css token survived
    assert "/* EXTRA-JS */" in html
    # Appended in order, after the base css.
    assert html.index("/* EXTRA-A */") < html.index("/* EXTRA-B */")
    # Skin JS lands after templates.js, before the engine bootstrap.
    assert html.index("/* EXTRA-JS */") < html.index("engine/viewer.js")


def test_bundled_skin_name_and_local_file_layer_together(tmp_path):
    over = tmp_path / "ov.css"
    over.write_text("/* YAML-EXTRA */", encoding="utf-8")
    html = emit.build_html(_graph(style={"skin": ["codemap", str(over)]}))
    assert "/* YAML-EXTRA */" in html
    # Bundled codemap css came first, the local override after it.
    assert html.index("io-flow bundled skin: code-map") < html.index("/* YAML-EXTRA */")


def test_unknown_skin_name_errors(tmp_path):
    with pytest.raises(FileNotFoundError, match="unknown skin 'nope'"):
        emit.build_html(_graph(), skin="nope")
    # A suffixed entry is a path, so a missing one reports as a missing file.
    with pytest.raises(FileNotFoundError, match="skin file not found"):
        emit.build_html(_graph(), skin=str(tmp_path / "gone.css"))


def test_cli_arg_overrides_yaml_style(tmp_path):
    yaml_css = tmp_path / "yaml.css"
    yaml_css.write_text("/* FROM-YAML */", encoding="utf-8")
    flag_css = tmp_path / "flag.css"
    flag_css.write_text("/* FROM-FLAG */", encoding="utf-8")
    html = emit.build_html(_graph(style={"css": str(yaml_css)}), css=flag_css)
    assert "/* FROM-FLAG */" in html
    assert "/* FROM-YAML */" not in html
