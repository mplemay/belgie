from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Final

TOOL_TABLE: Final[str] = "tool"
BELGIE_TABLE: Final[str] = "belgie"
PYPROJECT_NAME: Final[str] = "pyproject.toml"
DEFAULT_SOURCE: Final[Path] = Path()
DEFAULT_MODULE: Final[bool] = False
SOURCE_TABLE_PATH: Final[str] = "[tool.belgie].source"
MODULE_TABLE_PATH: Final[str] = "[tool.belgie].module"
ABSOLUTE_SOURCE_PATH_ERROR: Final[str] = f"{SOURCE_TABLE_PATH} must be a relative path"
PARENT_SOURCE_PATH_ERROR: Final[str] = f"{SOURCE_TABLE_PATH} cannot contain '..'"
EMPTY_SOURCE_PATH_ERROR: Final[str] = f"{SOURCE_TABLE_PATH} must be a non-empty string"
INVALID_SOURCE_PATH_ERROR: Final[str] = f"{SOURCE_TABLE_PATH} must be a string"
INVALID_MODULE_ERROR: Final[str] = f"{MODULE_TABLE_PATH} must be a boolean"


class PyprojectError(Exception):
    pass


@dataclass(slots=True, kw_only=True, frozen=True)
class BelgieToolConfig:
    source: Path = DEFAULT_SOURCE
    module: bool = DEFAULT_MODULE


def is_absolute_config_path(source: str) -> bool:
    return PurePosixPath(source).is_absolute() or PureWindowsPath(source).is_absolute()


def discover_pyproject_root(*, start: Path | None = None) -> Path:
    start_path = (start or Path.cwd()).resolve()
    if start_path.is_file():
        start_path = start_path.parent

    searched: list[str] = []
    for directory in (start_path, *start_path.parents):
        pyproject_path = directory / PYPROJECT_NAME
        searched.append(str(pyproject_path))
        if pyproject_path.is_file():
            return directory.resolve()

    msg = f"Could not find pyproject.toml. Searched: {', '.join(searched)}"
    raise PyprojectError(msg)


def parse_belgie_tool_config(document: dict[str, Any]) -> BelgieToolConfig:
    tool = document.get(TOOL_TABLE)
    if tool is None:
        return BelgieToolConfig()
    if not isinstance(tool, dict):
        msg = "[tool] must be a table"
        raise PyprojectError(msg)

    belgie = tool.get(BELGIE_TABLE)
    if belgie is None:
        return BelgieToolConfig()
    if not isinstance(belgie, dict):
        msg = "[tool.belgie] must be a table"
        raise PyprojectError(msg)

    source = belgie.get("source")
    if source is None:
        source_path = DEFAULT_SOURCE
    else:
        if not isinstance(source, str) or not source.strip():
            raise PyprojectError(EMPTY_SOURCE_PATH_ERROR if isinstance(source, str) else INVALID_SOURCE_PATH_ERROR)
        source_path = Path(source)
        if is_absolute_config_path(source):
            raise PyprojectError(ABSOLUTE_SOURCE_PATH_ERROR)
        if any(part == ".." for part in source_path.parts):
            raise PyprojectError(PARENT_SOURCE_PATH_ERROR)

    module = belgie.get("module", DEFAULT_MODULE)
    if not isinstance(module, bool):
        raise PyprojectError(INVALID_MODULE_ERROR)
    return BelgieToolConfig(source=source_path, module=module)


def load_belgie_tool_config(project_root: Path) -> BelgieToolConfig:
    document = read_pyproject_toml(project_root / PYPROJECT_NAME)
    return parse_belgie_tool_config(document)


def read_pyproject_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        msg = f"No pyproject.toml found at {path.parent}"
        raise PyprojectError(msg)
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        msg = f"Invalid pyproject.toml at {path}: {exc}"
        raise PyprojectError(msg) from exc
    if not isinstance(document, dict):
        msg = f"Invalid pyproject.toml at {path}"
        raise PyprojectError(msg)
    return document


def parse_tool_table(document: dict[str, Any], *segments: str) -> dict[str, str]:
    table_path = ".".join((TOOL_TABLE, *segments))
    current: object = document
    for segment in (TOOL_TABLE, *segments):
        if not isinstance(current, dict):
            msg = f"[{table_path}] must be a table"
            raise PyprojectError(msg)
        next_value = current.get(segment)
        if next_value is None:
            return {}
        current = next_value

    if not isinstance(current, dict):
        msg = f"[{table_path}] must be a table"
        raise PyprojectError(msg)

    dependencies: dict[str, str] = {}
    for alias, value in current.items():
        if not isinstance(alias, str) or not alias.strip() or not isinstance(value, str) or not value.strip():
            msg = f"[{table_path}] entries must map non-empty strings to non-empty strings"
            raise PyprojectError(msg)
        dependencies[alias] = value
    return dependencies


def resolve_file_dependency_paths(dependencies: dict[str, str], base: Path) -> dict[str, str]:
    resolved: dict[str, str] = {}
    for alias, specifier in dependencies.items():
        if specifier.startswith("file:"):
            path = specifier.removeprefix("file:")
            if not path:
                msg = f"Belgie dependency '{alias}' must provide a non-empty file: path"
                raise PyprojectError(msg)
            absolute = (base / path).resolve()
            resolved[alias] = f"file:{absolute.as_posix()}"
        else:
            resolved[alias] = specifier
    return resolved
