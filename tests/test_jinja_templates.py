"""jinja_templates.py: `templates/<type>.html` rendered at build time."""

from __future__ import annotations

import json

import pytest

from io_flow import emit
from io_flow.parser import parse_file
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


def test_packaged_declarations_render_the_builtin_types():
    """The ten built-in types are types.yaml entries now, not JS functions."""
    g = _graph("file", "parameter", "function", "class")
    g["nodes"][0]["data"] = {"cli": "--config", "value": "config.yaml"}
    g["nodes"][1]["data"] = {"value": 60}
    nodes = _embedded(emit.build_html(g))
    assert '<span class="node__badge">file</span>' in nodes["file"]["html"]
    assert "<code>--config</code>" in nodes["file"]["html"]
    assert '<span class="node__badge">param</span>' in nodes["parameter"]["html"]
    assert "= 60" in nodes["parameter"]["html"]
    # Callables mark themselves with () and carry no badge.
    assert "function()" in nodes["function"]["html"]
    assert "node__badge" not in nodes["function"]["html"]
    # Compound types keep both load-bearing mounts.
    assert 'class="node__header"' in nodes["class"]["html"]
    assert 'class="node__children"' in nodes["class"]["html"]


def test_blank_meta_lines_are_dropped():
    """`show cli only if there is one` is a one-liner, not a conditional."""
    g = _graph("option")
    g["nodes"][0]["data"] = {}
    assert "node__meta" not in _embedded(emit.build_html(g))["option"]["html"]


def test_project_types_yaml_declares_and_overrides(tmp_path):
    d = tmp_path / "templates"
    d.mkdir()
    (d / "types.yaml").write_text(
        "queue: {badge: queue, meta: ['{{ data.depth }} waiting']}\n"
        "method: {title: '{{ label }} [m]'}\n",  # replaces the packaged entry
        encoding="utf-8",
    )
    g = _graph("queue", "method")
    g["nodes"][0]["data"] = {"depth": 12}
    nodes = _embedded(emit.build_html(g, templates=d))
    assert '<span class="node__badge">queue</span>' in nodes["queue"]["html"]
    assert '<div class="node__meta">12 waiting</div>' in nodes["queue"]["html"]
    assert "method [m]" in nodes["method"]["html"]
    assert "method()" not in nodes["method"]["html"]


def test_diagram_types_block_extends_types_per_document(tmp_path):
    """A diagram can describe a type it alone uses, with no file anywhere."""
    src = tmp_path / "d.yaml"
    src.write_text(
        "types:\n"
        "  queue: {badge: queue, meta: ['{{ data.depth }} waiting']}\n"
        "  gate: {template: '<div class=\"node__title\">|{{ label }}|</div>'}\n"
        "nodes:\n"
        "  $inbox: {type: queue, depth: 12}\n"
        "  $g: {type: gate}\n",
        encoding="utf-8",
    )
    nodes = _embedded(emit.build_html(parse_file(src)))
    assert '<div class="node__meta">12 waiting</div>' in nodes["inbox"]["html"]
    assert nodes["g"]["html"] == '<div class="node__title">|g|</div>'


def test_declared_sidebar_string_beats_the_skins_default(tmp_path):
    skin = tmp_path / "plain.sidebar.html"
    skin.write_text("GENERIC", encoding="utf-8")
    src = tmp_path / "d.yaml"
    src.write_text(
        "types: {queue: {sidebar: '<dl><dt>depth</dt><dd>{{ data.depth }}</dd></dl>'}}\n"
        "nodes: {$inbox: {type: queue, depth: 12}, $other: {type: gate}}\n",
        encoding="utf-8",
    )
    nodes = _embedded(emit.build_html(parse_file(src), skin=str(skin)))
    assert nodes["inbox"]["sidebar"] == "<dl><dt>depth</dt><dd>12</dd></dl>"
    assert nodes["other"]["sidebar"] == "GENERIC"


def test_blocks_replace_a_base_block_from_yaml(tmp_path):
    """`blocks:` reaches the slots the title/badge/meta sugar doesn't cover, so
    a one-line type never needs a one-line file."""
    src = tmp_path / "d.yaml"
    src.write_text(
        "types:\n"
        "  queue:\n"
        "    badge: queue\n"
        "    blocks: {meta: '<div class=\"node__meta\">{{ data.depth }}!</div>'}\n"
        "  panel:\n"
        "    extends: _group\n"
        "    blocks: {children: '<div class=\"node__children\" data-panel></div>'}\n"
        "nodes:\n"
        "  $inbox: {type: queue, depth: 12}\n"
        "  $p: {type: panel}\n",
        encoding="utf-8",
    )
    nodes = _embedded(emit.build_html(parse_file(src)))
    # The block replaced meta; the badge sugar still came through.
    assert '<div class="node__meta">12!</div>' in nodes["inbox"]["html"]
    assert '<span class="node__badge">queue</span>' in nodes["inbox"]["html"]
    # And a block the sugar has no field for at all.
    assert 'data-panel' in nodes["p"]["html"]


def test_blocks_can_append_with_super(tmp_path):
    src = tmp_path / "d.yaml"
    src.write_text(
        "types:\n"
        "  queue:\n"
        "    meta: ['{{ data.depth }} waiting']\n"
        "    blocks: {meta: '{{ super() }}<div class=\"node__meta\">and more</div>'}\n"
        "nodes: {$inbox: {type: queue, depth: 12}}\n",
        encoding="utf-8",
    )
    html = _embedded(emit.build_html(parse_file(src)))["inbox"]["html"]
    assert html.index("12 waiting") < html.index("and more")


def test_bad_block_name_is_a_loud_error(tmp_path):
    src = tmp_path / "d.yaml"
    src.write_text(
        "types: {queue: {blocks: {'meta %}{{ 1/0 }}{%': 'x'}}}\n"
        "nodes: {$inbox: {type: queue}}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="not a block name"):
        emit.build_html(parse_file(src))


def test_type_template_wins_and_undeclared_types_get_a_base(tmp_path):
    d = tmp_path / "templates"
    d.mkdir()
    (d / "queue.html").write_text(
        '<div class="node__title">{{ label }} ({{ data.loc }})</div>', encoding="utf-8"
    )
    nodes = _embedded(emit.build_html(_graph("queue", "widget"), templates=d))
    assert nodes["queue"]["html"] == '<div class="node__title">queue (queue.py)</div>'
    # `widget` is neither declared nor templated: it still renders, via _node.
    assert nodes["widget"]["html"] == (
        '<div class="node__header"><div class="node__title">widget</div></div>'
    )


def test_undeclared_type_gets_compound_when_it_has_children():
    """Compound-ness is a state, not a type: the base follows the children."""
    g = _graph("widget")
    g["nodes"].append(
        {"id": "kid", "type": "widget", "parent": "widget", "label": "kid", "data": {}}
    )
    nodes = _embedded(emit.build_html(g))
    parent, child = nodes["widget"]["html"], nodes["kid"]["html"]
    assert 'class="node__header"' in parent and 'class="node__children"' in parent
    assert "node__children" not in child


def test_inherited_template_takes_names_from_the_nodes_own_type(tmp_path):
    """The whole point of the bases: shared structure, per-type badges/classes."""
    d = tmp_path / "templates"
    d.mkdir()
    for t in ("queue", "job"):
        (d / f"{t}.html").write_text(
            '{% extends "_node.html" %}'
            '{% block badge %} <span class="node__badge">{{ type }}</span>{% endblock %}',
            encoding="utf-8",
        )
    nodes = _embedded(emit.build_html(_graph("queue", "job"), templates=d))
    assert '<span class="node__badge">queue</span>' in nodes["queue"]["html"]
    assert '<span class="node__badge">job</span>' in nodes["job"]["html"]
    # A block override reaches into the shared base without restating it.
    (d / "job.html").write_text(
        '{% extends "_node.html" %}{% block meta %}<div class="node__meta">x</div>'
        "{% endblock %}",
        encoding="utf-8",
    )
    nodes = _embedded(emit.build_html(_graph("job"), templates=d))
    assert '<div class="node__meta">x</div>' in nodes["job"]["html"]


def test_file_template_inherits_its_declarations_slots(tmp_path):
    """A file extending a base still gets the declaration's title/badge/meta as
    block defaults, so it can override just the block it cares about."""
    d = tmp_path / "templates"
    d.mkdir()
    (d / "types.yaml").write_text(
        "queue: {badge: queue, title: '{{ label }}!', meta: ['{{ data.depth }} waiting']}\n",
        encoding="utf-8",
    )
    (d / "queue.html.j2").write_text(
        '{% extends "_node.html" %}'
        '{% block meta %}<div class="node__meta">deep</div>{% endblock %}',
        encoding="utf-8",
    )
    g = _graph("queue")
    g["nodes"][0]["data"] = {"depth": 12}
    html = _embedded(emit.build_html(g, templates=d))["queue"]["html"]
    assert "queue!" in html  # title from the declaration
    assert '<span class="node__badge">queue</span>' in html  # badge too
    assert '<div class="node__meta">deep</div>' in html  # meta from the file
    assert "12 waiting" not in html  # which replaced the declared line


def test_compound_base_keeps_the_load_bearing_mounts(tmp_path):
    d = tmp_path / "templates"
    d.mkdir()
    (d / "group.html").write_text('{% extends "_group.html" %}', encoding="utf-8")
    nodes = _embedded(emit.build_html(_graph("group"), templates=d))
    html = nodes["group"]["html"]
    assert 'class="node__header"' in html and 'class="node__children"' in html


def test_sidebar_template_is_independent_of_the_body_template(tmp_path):
    d = tmp_path / "templates"
    d.mkdir()
    (d / "queue.sidebar.html").write_text("<dl><dt>at</dt><dd>{{ data.loc }}</dd></dl>",
                                          encoding="utf-8")
    nodes = _embedded(emit.build_html(_graph("queue", "function"), templates=d))
    # Sidebar without a body template: the body still comes from the base.
    assert nodes["queue"]["sidebar"] == "<dl><dt>at</dt><dd>queue.py</dd></dl>"
    assert nodes["queue"]["html"] == (
        '<div class="node__header"><div class="node__title">queue</div></div>'
    )
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


def test_html_j2_suffix_works_everywhere(tmp_path):
    """`.html.j2` is the spelling editors highlight as Jinja; it must be
    interchangeable with `.html` for node, sidebar and skin templates -- and
    `{% extends "_node.html" %}` must still find the packaged base."""
    d = tmp_path / "templates"
    d.mkdir()
    (d / "queue.html.j2").write_text(
        '{% extends "_node.html" %}'
        '{% block badge %} <span class="node__badge">{{ type }}</span>{% endblock %}',
        encoding="utf-8",
    )
    (d / "queue.sidebar.html.j2").write_text("SIDEBAR", encoding="utf-8")
    skin = tmp_path / "plain.sidebar.html.j2"
    skin.write_text("GENERIC", encoding="utf-8")
    nodes = _embedded(
        emit.build_html(_graph("queue", "function"), templates=d, skin=str(skin))
    )
    assert '<span class="node__badge">queue</span>' in nodes["queue"]["html"]
    assert nodes["queue"]["sidebar"] == "SIDEBAR"
    assert nodes["function"]["sidebar"] == "GENERIC"


def test_skin_sidebar_template_covers_every_type(tmp_path):
    """A skin's <name>.sidebar.html is the default sidebar -- no templates dir
    needed, and it applies to types that named no sidebar template."""
    skin = tmp_path / "plain.sidebar.html"
    skin.write_text("<dl><dt>where</dt><dd>{{ data.loc }}</dd></dl>", encoding="utf-8")
    nodes = _embedded(emit.build_html(_graph("queue", "function"), skin=str(skin)))
    assert nodes["queue"]["sidebar"] == "<dl><dt>where</dt><dd>queue.py</dd></dl>"
    assert nodes["function"]["sidebar"].endswith("<dd>function.py</dd></dl>")


def test_type_sidebar_template_beats_the_skins_default(tmp_path):
    skin = tmp_path / "plain.sidebar.html"
    skin.write_text("GENERIC", encoding="utf-8")
    d = tmp_path / "templates"
    d.mkdir()
    (d / "queue.sidebar.html").write_text("SPECIFIC", encoding="utf-8")
    nodes = _embedded(
        emit.build_html(_graph("queue", "function"), templates=d, skin=str(skin))
    )
    assert nodes["queue"]["sidebar"] == "SPECIFIC"
    assert nodes["function"]["sidebar"] == "GENERIC"


def test_bundled_codemap_skin_renders_its_sidebar(tmp_path):
    g = _graph("function")
    g["nodes"][0]["data"] = {
        "module": "pkg/mod", "arg_names": ["a", "b"], "source": "def f(a, b):\n    return a",
        "calls": {"$other": ""},  # edge wiring: never a sidebar row
    }
    sidebar = _embedded(emit.build_html(g, skin="codemap"))["function"]["sidebar"]
    assert "<dt>module</dt>" in sidebar and "<dd>pkg/mod</dd>" in sidebar
    assert '<div class="sb-list-h">args</div>' in sidebar  # relabeled from arg_names
    assert "<li>a</li>" in sidebar
    assert '<pre class="sb-code">' in sidebar and "def f(a, b):" in sidebar
    assert "xcall" not in sidebar and "<dt>calls</dt>" not in sidebar


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
