"""jinja_templates.py: `templates/<type>.html` rendered at build time."""

from __future__ import annotations

import json

import pytest

from io_flow import emit
from io_flow.server import LayoutServer


def _graph(*types):
    return {
        "nodes": [
            {"id": t, "type": t, "parent": None, "label": t, "data": {"loc": f"{t}.py"}}
            for t in types
        ],
        "edges": [],
    }


def _embedded(html):
    """The graph JSON the artifact ships, parsed back out."""
    start = html.index('<script id="graph-data" type="application/json">')
    body = html[start:].split(">", 1)[1].split("</script")[0]
    return {n["id"]: n for n in json.loads(body)["nodes"]}


def test_type_template_renders_and_untemplated_type_falls_back(tmp_path):
    d = tmp_path / "templates"
    d.mkdir()
    (d / "queue.html").write_text(
        '<div class="node__title">{{ label }} ({{ data.loc }})</div>', encoding="utf-8"
    )
    nodes = _embedded(emit.build_html(_graph("queue", "function"), templates=d))
    assert nodes["queue"]["html"] == '<div class="node__title">queue (queue.py)</div>'
    # No queue.js template shadowing: the packaged templates.js still ships as
    # the fallback, and the untemplated type carries no prerendered html.
    assert "html" not in nodes["function"]


def test_inherited_template_takes_names_from_the_nodes_own_type(tmp_path):
    """The whole point of the bases: shared structure, per-type badges/classes."""
    d = tmp_path / "templates"
    d.mkdir()
    for t in ("queue", "job"):
        (d / f"{t}.html").write_text('{% extends "_simple.html" %}', encoding="utf-8")
    nodes = _embedded(emit.build_html(_graph("queue", "job"), templates=d))
    assert '<span class="node__badge">queue</span>' in nodes["queue"]["html"]
    assert '<span class="node__badge">job</span>' in nodes["job"]["html"]
    # A block override reaches into the shared base without restating it.
    (d / "job.html").write_text(
        '{% extends "_simple.html" %}{% block meta %}<div class="node__meta">x</div>'
        "{% endblock %}",
        encoding="utf-8",
    )
    nodes = _embedded(emit.build_html(_graph("job"), templates=d))
    assert '<div class="node__meta">x</div>' in nodes["job"]["html"]


def test_compound_base_keeps_the_load_bearing_mounts(tmp_path):
    d = tmp_path / "templates"
    d.mkdir()
    (d / "group.html").write_text('{% extends "_compound.html" %}', encoding="utf-8")
    nodes = _embedded(emit.build_html(_graph("group"), templates=d))
    html = nodes["group"]["html"]
    assert 'class="node__header"' in html and 'class="node__children"' in html


def test_sidebar_template_is_independent_of_the_body_template(tmp_path):
    d = tmp_path / "templates"
    d.mkdir()
    (d / "queue.sidebar.html").write_text("<dl><dt>at</dt><dd>{{ data.loc }}</dd></dl>",
                                          encoding="utf-8")
    nodes = _embedded(emit.build_html(_graph("queue", "function"), templates=d))
    # Sidebar without a body template: the body still falls back to templates.js.
    assert nodes["queue"]["sidebar"] == "<dl><dt>at</dt><dd>queue.py</dd></dl>"
    assert "html" not in nodes["queue"]
    assert "sidebar" not in nodes["function"]


def test_sidebar_base_dumps_data_and_takes_block_overrides(tmp_path):
    d = tmp_path / "templates"
    d.mkdir()
    (d / "queue.sidebar.html").write_text(
        '{% extends "_sidebar.html" %}{% block rows %}<dt>depth</dt><dd>12</dd>'
        "{{ super() }}{% endblock %}",
        encoding="utf-8",
    )
    sidebar = _embedded(emit.build_html(_graph("queue"), templates=d))["queue"]["sidebar"]
    assert "<dt>depth</dt><dd>12</dd>" in sidebar
    assert "<dt>loc</dt><dd>queue.py</dd>" in sidebar  # super() kept the generic rows


def test_values_are_autoescaped(tmp_path):
    d = tmp_path / "templates"
    d.mkdir()
    (d / "file.html").write_text("<div>{{ data.loc }}</div>", encoding="utf-8")
    g = _graph("file")
    g["nodes"][0]["data"]["loc"] = '<script>alert("x")</script>'
    nodes = _embedded(emit.build_html(g, templates=d))
    assert "<script>alert" not in nodes["file"]["html"]
    assert "&lt;script&gt;" in nodes["file"]["html"]


def test_missing_field_is_empty_not_an_error(tmp_path):
    d = tmp_path / "templates"
    d.mkdir()
    (d / "file.html").write_text(
        "<div>{% if data.nope.deeper %}never{% endif %}{{ data.nope }}</div>",
        encoding="utf-8",
    )
    nodes = _embedded(emit.build_html(_graph("file"), templates=d))
    assert nodes["file"]["html"] == "<div></div>"


def test_template_error_names_the_file_and_the_node(tmp_path):
    d = tmp_path / "templates"
    d.mkdir()
    (d / "file.html").write_text("{% if %}", encoding="utf-8")
    with pytest.raises(ValueError, match=r"file\.html.*node \$file"):
        emit.build_html(_graph("file"), templates=d)


def test_yaml_style_templates_dir_and_live_reload(tmp_path):
    """style: {templates: dir} drives the build, and editing a template bumps
    the live-reload version (a dir's own mtime would not)."""
    d = tmp_path / "templates"
    d.mkdir()
    tpl = d / "file.html"
    tpl.write_text('<div class="node__title">v1</div>', encoding="utf-8")
    src = tmp_path / "d.yaml"
    src.write_text(
        "style: {templates: templates}\nnodes: {$cfg: {type: file}}\n", encoding="utf-8"
    )
    srv = LayoutServer(src, port=0)
    try:
        assert "v1" in srv.html
        v1 = srv.version()
        tpl.write_text('<div class="node__title">v2</div>', encoding="utf-8")
        assert srv.version() > v1
        srv.rebuild()
        assert "v2" in srv.html
    finally:
        srv.httpd.server_close()
