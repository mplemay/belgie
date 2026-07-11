from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from belgie import Environment, Runtime, Script
from belgie._core import AsyncEnvironment, SyncEnvironment
from belgie._pyproject import (
    PyprojectError,
    parse_tool_table,
    read_pyproject_toml,
    resolve_file_dependency_paths,
)

type BelgieEnvironment = Environment | SyncEnvironment | AsyncEnvironment

LOCKFILE_NAME: Final[str] = "deno.lock"
DEPENDENCIES_TABLE: Final[tuple[str, ...]] = ("belgie", "dependencies")
MCP_PACKAGE_NAME: Final[str] = "@belgie/mcp"
WIDGET_PATH_OUTSIDE_ROOT_ERROR: Final[str] = "Widget path must stay inside the BelgieExtension root"
MISSING_PROJECT_DEPENDENCIES_ERROR: Final[str] = "No [tool.belgie.dependencies] entries found in {pyproject}"
MISSING_LOCKFILE_ERROR: Final[str] = "Missing Belgie lockfile at {lockfile}; run `belgie install`"
MISSING_MCP_PACKAGE_ERROR: Final[str] = (
    "Missing {package} file: dependency in [tool.belgie.dependencies]; "
    "declare it as a local path to the @belgie/mcp package"
)
INVALID_MCP_PACKAGE_ERROR: Final[str] = (
    "{package} must be a file: dependency pointing at the local @belgie/mcp package, got {specifier!r}"
)


class WidgetRenderManifest(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    package_name: str = Field(validation_alias="packageName")
    package_version: str = Field(validation_alias="packageVersion")


class WidgetBuildResult(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    html: str
    manifest: WidgetRenderManifest


def build_widget(
    *,
    root: Path,
    path: Path,
    environment: BelgieEnvironment | None = None,
    project_path: Path | None = None,
) -> WidgetBuildResult:
    root_path = root.resolve(strict=True)
    widget_path = (root_path / path).resolve(strict=True)
    try:
        relative_widget_path = widget_path.relative_to(root_path)
    except ValueError as error:
        raise ValueError(WIDGET_PATH_OUTSIDE_ROOT_ERROR) from error

    resolved_project_path = _resolve_project_path(project_path)
    mcp_package_path = _resolve_mcp_package_path(resolved_project_path)
    with (
        _use_environment(environment, project_path=resolved_project_path) as env,
        Runtime(env=env) as runtime,
    ):
        build_script = Script.from_file(mcp_package_path / "run-build.ts")
        return WidgetBuildResult.model_validate(
            runtime(build_script)(
                str(resolved_project_path),
                str(root_path),
                relative_widget_path.as_posix(),
            ),
        )


def _resolve_project_path(path: Path | None) -> Path:
    return (Path.cwd() if path is None else Path(path)).resolve()


def _resolve_mcp_package_path(project_path: Path) -> Path:
    dependencies = _load_project_dependencies(project_path)
    specifier = dependencies.get(MCP_PACKAGE_NAME)
    if specifier is None:
        msg = MISSING_MCP_PACKAGE_ERROR.format(package=MCP_PACKAGE_NAME)
        raise PyprojectError(msg)
    if not specifier.startswith("file:"):
        msg = INVALID_MCP_PACKAGE_ERROR.format(package=MCP_PACKAGE_NAME, specifier=specifier)
        raise PyprojectError(msg)
    path = Path(specifier.removeprefix("file:"))
    if not path.is_dir():
        msg = INVALID_MCP_PACKAGE_ERROR.format(package=MCP_PACKAGE_NAME, specifier=specifier)
        raise PyprojectError(msg)
    return path


def _load_project_dependencies(project_path: Path) -> dict[str, str]:
    pyproject_path = project_path / "pyproject.toml"
    document = read_pyproject_toml(pyproject_path)
    dependencies = parse_tool_table(document, *DEPENDENCIES_TABLE)
    if not dependencies:
        msg = MISSING_PROJECT_DEPENDENCIES_ERROR.format(pyproject=pyproject_path)
        raise PyprojectError(msg)
    return resolve_file_dependency_paths(dependencies, project_path)


def _require_installed(project_path: Path) -> None:
    lockfile = project_path / LOCKFILE_NAME
    if not lockfile.is_file():
        msg = MISSING_LOCKFILE_ERROR.format(lockfile=lockfile)
        raise PyprojectError(msg)


@contextmanager
def _use_environment(
    environment: BelgieEnvironment | None,
    *,
    project_path: Path,
) -> Iterator[SyncEnvironment | AsyncEnvironment]:
    if environment is None:
        dependencies = _load_project_dependencies(project_path)
        _require_installed(project_path)
        with Environment(
            dependencies,
            path=project_path,
            lockfile=project_path / LOCKFILE_NAME,
        ) as env:
            yield env
    elif isinstance(environment, Environment):
        with environment as env:
            yield env
    else:
        yield environment
