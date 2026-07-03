from __future__ import annotations

import builtins
import importlib
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest
from typer.testing import CliRunner

from belgie.cli.__main__ import CLI_REQUIRED_MESSAGE, app

runner = CliRunner()


def test_list_command_prints_configured_dependencies(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "demo"

[tool.belgie.dependencies]
std_path = "jsr:@std/path@^1"
""",
        encoding="utf-8",
    )

    result = runner.invoke(app, ["list", "-C", str(tmp_path)])

    assert result.exit_code == 0
    assert "std_path = jsr:@std/path@^1" in result.output


def test_list_command_reports_empty_dependency_table(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n', encoding="utf-8")

    result = runner.invoke(app, ["list", "-C", str(tmp_path)])

    assert result.exit_code == 0
    assert "No [tool.belgie.dependencies] entries found." in result.output


def test_main_reports_missing_cli_extra(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    real_import = builtins.__import__

    def fake_import(
        name: str,
        globals: Mapping[str, object] | None = None,  # noqa: A002
        locals: Mapping[str, object] | None = None,  # noqa: A002
        fromlist: Sequence[str] = (),
        level: int = 0,
    ) -> object:
        if name == "typer":
            msg = "No module named 'typer'"
            raise ImportError(msg)
        return real_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.delitem(sys.modules, "belgie.cli.__main__", raising=False)
    monkeypatch.delitem(sys.modules, "belgie.cli._app", raising=False)

    with pytest.raises(SystemExit) as exc_info:
        importlib.import_module("belgie.cli.__main__")

    assert exc_info.value.code == 1
    assert CLI_REQUIRED_MESSAGE in capsys.readouterr().err
