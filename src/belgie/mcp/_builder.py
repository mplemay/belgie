from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Final
from urllib.parse import urlparse

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
MISSING_PROJECT_DEPENDENCIES_ERROR: Final[str] = "No [tool.belgie.dependencies] entries found in {pyproject}"
MISSING_LOCKFILE_ERROR: Final[str] = "Missing Belgie lockfile at {lockfile}; run `belgie install`"
MISSING_MCP_PACKAGE_ERROR: Final[str] = (
    "Missing {package} in [tool.belgie.dependencies]; declare an npm or file: dependency"
)
INVALID_BASE_URL_ERROR: Final[str] = "base_url must be an absolute http(s) URL, got {base_url!r}"
MANIFEST_SCRIPT: Final[str] = (
    'import { loadWidgetManifest } from "@belgie/mcp/manifest";\n'
    "export default (projectRoot: string, baseUrl: string) => "
    "loadWidgetManifest(projectRoot, baseUrl);\n"
)


class WidgetEntry(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    name: str
    html: str


class WidgetManifest(BaseModel):
    model_config = ConfigDict(frozen=True, populate_by_name=True)

    base_url: str = Field(validation_alias="baseUrl")
    widgets: dict[str, WidgetEntry]


def load_widget_manifest(
    *,
    base_url: str,
    project_path: Path | None = None,
    environment: BelgieEnvironment | None = None,
) -> WidgetManifest:
    normalized_base_url = _normalize_base_url(base_url)
    resolved_project_path = _resolve_project_path(project_path)
    _require_mcp_package(resolved_project_path)
    with (
        _use_environment(environment, project_path=resolved_project_path) as env,
        Runtime(env=env) as runtime,
    ):
        return WidgetManifest.model_validate(
            runtime(Script(MANIFEST_SCRIPT))(
                str(resolved_project_path),
                normalized_base_url,
            ),
        )


def _normalize_base_url(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        msg = INVALID_BASE_URL_ERROR.format(base_url=base_url)
        raise ValueError(msg)
    return base_url.rstrip("/")


def _resolve_project_path(path: Path | None) -> Path:
    return (Path.cwd() if path is None else Path(path)).resolve()


def _require_mcp_package(project_path: Path) -> None:
    dependencies = _load_project_dependencies(project_path)
    if MCP_PACKAGE_NAME not in dependencies:
        msg = MISSING_MCP_PACKAGE_ERROR.format(package=MCP_PACKAGE_NAME)
        raise PyprojectError(msg)


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
