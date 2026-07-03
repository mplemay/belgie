from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from belgie.cli import __main__ as cli_main
from belgie.cli._app import app

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
    def fake_import_module(
        name: str,
    ) -> object:
        if name == "belgie.cli._app":
            msg = "No module named 'typer'"
            raise ModuleNotFoundError(msg, name="typer")
        return None

    monkeypatch.setattr(cli_main, "import_module", fake_import_module)

    with pytest.raises(SystemExit) as exc_info:
        cli_main.main(["--help"])

    assert exc_info.value.code == 1
    assert 'uv add "belgie[cli]"' in capsys.readouterr().err
