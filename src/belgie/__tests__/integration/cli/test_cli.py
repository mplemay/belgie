from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from belgie.cli.__main__ import app
from belgie.cli._operations import install_project, lock_project, run_command, update_project
from belgie.cli._project import load_project

pytestmark = pytest.mark.integration

runner = CliRunner()


def test_pyproject_dependencies_lock_install_and_update(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "demo"

[tool.belgie.dependencies]
"is-number" = "npm:is-number@7.0.0"
""",
        encoding="utf-8",
    )

    lock_result = lock_project(load_project(tmp_path))
    install_result = install_project(load_project(tmp_path), frozen=True)
    update_result = update_project(load_project(tmp_path), ["is-number"], latest=False)

    assert lock_result.dependencies == 1
    assert install_result.dependencies == 1
    assert (tmp_path / "deno.lock").is_file()
    assert update_result.lockfile


def test_run_command_executes_dependency_binary(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "demo"

[tool.belgie.dependencies]
semver = "npm:semver@7.7.2"
""",
        encoding="utf-8",
    )

    lock_project(load_project(tmp_path))
    run_command(load_project(tmp_path), ["semver", "1.0.0"], frozen=True)


def test_run_cli_forwards_command_arguments(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "demo"

[tool.belgie.dependencies]
semver = "npm:semver@7.7.2"
""",
        encoding="utf-8",
    )

    lock_project(load_project(tmp_path))
    result = runner.invoke(app, ["run", "-C", str(tmp_path), "semver", "1.0.0"])

    assert result.exit_code == 0
