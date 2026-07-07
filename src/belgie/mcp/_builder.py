from functools import cache
from importlib.resources import as_file, files
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from belgie import Environment, Runtime, Script
from belgie._pyproject import (
    PyprojectError,
    parse_tool_table,
    read_pyproject_toml,
    resolve_file_dependency_paths,
)

MCP_PACKAGE_DIR: Final[Path] = Path(__file__).resolve().parent
MCP_BUILD_DEPENDENCIES_TABLE: Final[tuple[str, ...]] = ("belgie", "mcp", "build-dependencies")
MCP_PYPROJECT_PATH: Final[Path] = MCP_PACKAGE_DIR / "pyproject.toml"

WIDGET_PATH_OUTSIDE_ROOT_ERROR: Final[str] = "Widget path must stay inside the BelgieExtension root"
MISSING_MCP_BUILD_DEPENDENCIES_ERROR: Final[str] = "[tool.belgie.mcp.build-dependencies] must define at least one entry"


class WidgetRenderManifest(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    package_name: str = Field(validation_alias="packageName")
    package_version: str = Field(validation_alias="packageVersion")


class WidgetBuildResult(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    html: str
    manifest: WidgetRenderManifest


def build_widget(*, root: Path, path: Path) -> WidgetBuildResult:
    root_path = root.resolve(strict=True)
    widget_path = (root_path / path).resolve(strict=True)
    try:
        relative_widget_path = widget_path.relative_to(root_path)
    except ValueError as error:
        raise ValueError(WIDGET_PATH_OUTSIDE_ROOT_ERROR) from error

    with (
        as_file(files("belgie.mcp._widget_package")) as widget_package_path,
        # Keep Vite's dependency root adjacent to the widget source tree for cross-root imports.
        TemporaryDirectory(prefix="belgie-mcp-", dir=root_path.parent) as temp_dir,
    ):
        project_path = Path(temp_dir)
        build_script = Script.from_file(widget_package_path / "run-build.ts")
        dependencies = _load_build_dependencies()
        with Environment(dependencies, path=project_path) as env:
            env.install()
            with Runtime(env=env) as runtime:
                return WidgetBuildResult.model_validate(
                    runtime(build_script)(str(project_path), str(root_path), relative_widget_path.as_posix()),
                )


def _load_build_dependencies() -> dict[str, str]:
    return _load_build_dependencies_for(MCP_PYPROJECT_PATH)


@cache
def _load_build_dependencies_for(pyproject_path: Path) -> dict[str, str]:
    document = read_pyproject_toml(pyproject_path)
    dependencies = parse_tool_table(document, *MCP_BUILD_DEPENDENCIES_TABLE)
    if not dependencies:
        raise PyprojectError(MISSING_MCP_BUILD_DEPENDENCIES_ERROR)
    return resolve_file_dependency_paths(dependencies, MCP_PACKAGE_DIR)
