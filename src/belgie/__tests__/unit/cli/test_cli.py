from __future__ import annotations

import builtins
import importlib
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

import pytest
from typer.testing import CliRunner

from belgie.cli.__main__ import CLI_REQUIRED_MESSAGE, app, main
from belgie.cli._generate import GenerateResult
from belgie.cli._project import ProjectError

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


def test_run_command_requires_a_command(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "demo"

[tool.belgie.dependencies]
semver = "npm:semver@7.7.2"
""",
        encoding="utf-8",
    )
    (tmp_path / "deno.lock").write_text("{}", encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        main(["run", "-C", str(tmp_path)])

    assert exc_info.value.code == 1
    assert "Missing command" in capsys.readouterr().err


def test_generate_command_forwards_target_output_project_and_frozen(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n', encoding="utf-8")
    generated_path = tmp_path / "generated" / "tools.ts"
    calls: list[tuple[str, Path, bool]] = []

    def generate_tool_types(project, *, target: str, output: Path, frozen: bool) -> GenerateResult:
        assert project.root == tmp_path
        calls.append((target, output, frozen))
        return GenerateResult(path=generated_path, tools=2, changed=True)

    monkeypatch.setattr("belgie.cli.__main__.generate_tool_types", generate_tool_types)

    result = runner.invoke(
        app,
        [
            "generate",
            "demo:server",
            "--output",
            "generated/tools.ts",
            "--no-frozen",
            "-C",
            str(tmp_path),
        ],
    )

    assert result.exit_code == 0
    assert calls == [("demo:server", Path("generated/tools.ts"), False)]
    assert f"Generated 2 tool types: {generated_path}" in result.output


def test_run_command_requires_dependencies(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "demo"\n', encoding="utf-8")
    (tmp_path / "deno.lock").write_text("{}", encoding="utf-8")

    with pytest.raises(SystemExit) as exc_info:
        main(["run", "-C", str(tmp_path), "semver", "1.0.0"])

    assert exc_info.value.code == 1
    assert "No [tool.belgie.dependencies] entries found" in capsys.readouterr().err


def test_run_command_requires_lockfile_when_frozen(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "demo"

[tool.belgie.dependencies]
semver = "npm:semver@7.7.2"
""",
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as exc_info:
        main(["run", "-C", str(tmp_path), "semver", "1.0.0"])

    assert exc_info.value.code == 1
    assert isinstance(exc_info.value.__cause__, ProjectError)
    assert "Missing Belgie lockfile" in capsys.readouterr().err


def test_main_handles_project_error(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    missing_project = tmp_path / "missing"

    with pytest.raises(SystemExit) as exc_info:
        main(["list", "-C", str(missing_project)])

    assert exc_info.value.code == 1
    assert f"No pyproject.toml found at {missing_project}" in capsys.readouterr().err


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
