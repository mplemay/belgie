from __future__ import annotations

import tomllib
from typing import TYPE_CHECKING, Any, Final

if TYPE_CHECKING:
    from pathlib import Path

TOOL_TABLE: Final[str] = "tool"
PYPROJECT_NAME: Final[str] = "pyproject.toml"


class PyprojectError(Exception):
    pass


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
