from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

import pytest
from typer.testing import CliRunner

from belgie.cli.__main__ import app
from belgie.cli._operations import install_project, lock_project, run_command, update_project
from belgie.cli._project import load_project

pytestmark = pytest.mark.integration

runner = CliRunner()
MCP_PACKAGE_PATH: Final[Path] = Path(__file__).resolve().parents[5] / "packages" / "mcp"


def test_pyproject_dependencies_lock_install_and_update(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        """
[project]
name = "demo"

[tool.belgie]
minimum-dependency-age = "P7D"

[tool.belgie.dependencies]
"is-number" = "npm:is-number@7.0.0"
""",
        encoding="utf-8",
    )

    lock_result = lock_project(load_project(tmp_path))
    install_result = install_project(load_project(tmp_path), frozen=True)
    update_result = update_project(load_project(tmp_path), ["is-number"], latest=False, minimum_dependency_age="0")

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


def test_typescript_generates_without_widget_or_tool_execution(tmp_path: Path) -> None:
    module_name = f"generated_{tmp_path.name.replace('-', '_')}"
    source = tmp_path / "src"
    source.mkdir()
    (tmp_path / "pyproject.toml").write_text(
        f"""
[project]
name = "generated-demo"

[tool.belgie]
source = "src"

[tool.belgie.typescript]
target = "{module_name}:server"
output = "generated/tools.ts"

[tool.belgie.dependencies]
"@belgie/mcp" = "file:{MCP_PACKAGE_PATH.resolve().as_posix()}"
"@modelcontextprotocol/ext-apps" = "npm:@modelcontextprotocol/ext-apps@latest"
react = "npm:react@^19"
"react-dom" = "npm:react-dom@^19"
vite = "npm:vite@8.1.3"
""".lstrip(),
        encoding="utf-8",
    )
    (source / f"{module_name}.py").write_text(
        """
from pathlib import Path

from mcp.server import MCPServer

from belgie.mcp import BelgieExtension


CALLED = False
extension = BelgieExtension(project=Path.cwd())


@extension.tool(widget=Path("missing/widget.tsx"), name="typed")
def typed(value: str, count: int = 1) -> str:
    global CALLED
    CALLED = True
    return value * count


server = MCPServer(name="generated-demo", extensions=[extension])
""".lstrip(),
        encoding="utf-8",
    )

    project = load_project(tmp_path)
    lock_project(project)
    first = runner.invoke(app, ["typescript", "-C", str(tmp_path)])
    second = runner.invoke(app, ["types", "-C", str(tmp_path), "--check"])

    assert first.exit_code == 0, first.output
    assert second.exit_code == 0, second.output
    generated = tmp_path / "generated" / "tools.ts"
    assert '"typed"' in generated.read_text(encoding="utf-8")
    assert not sys.modules[module_name].CALLED
    assert not (tmp_path / "missing").exists()
    sys.modules.pop(module_name, None)
