"""cli.py: check subcommand exit codes and build output."""

from __future__ import annotations

from io_flow.cli import main

CLEAN = """\
nodes:
  input:
    cfg: {type: file}
  functions:
    run:
      args: {c: cfg}
"""

BROKEN_REF = """\
nodes:
  input:
    cfg: {type: file}
  functions:
    run:
      args: {c: cgf}
"""


def test_check_clean_exits_zero(tmp_path, capsys):
    src = tmp_path / "d.yaml"
    src.write_text(CLEAN, encoding="utf-8")
    assert main(["check", str(src)]) == 0
    out = capsys.readouterr().out
    assert "2 nodes" in out and "0 warnings" in out


def test_check_strict_fails_on_unresolved_ref(tmp_path, capsys):
    src = tmp_path / "d.yaml"
    src.write_text(BROKEN_REF, encoding="utf-8")
    assert main(["check", str(src), "--strict"]) == 1
    err = capsys.readouterr().err
    assert "cgf" in err and "Did you mean" in err


def test_check_non_strict_warns_but_passes(tmp_path):
    src = tmp_path / "d.yaml"
    src.write_text(BROKEN_REF, encoding="utf-8")
    assert main(["check", str(src)]) == 0


def test_build_writes_html(tmp_path, capsys):
    src = tmp_path / "d.yaml"
    src.write_text(CLEAN, encoding="utf-8")
    out = tmp_path / "out.html"
    assert main(["build", str(src), "-o", str(out)]) == 0
    assert out.exists()
    assert "wrote" in capsys.readouterr().out
