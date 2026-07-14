from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

import rtoml

from belgie._pyproject import PyprojectError, discover_pyproject_root, parse_belgie_tool_config, parse_tool_table

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path

LOCKFILE_NAME: Final[str] = "deno.lock"
PYPROJECT_NAME: Final[str] = "pyproject.toml"
TOOL_TABLE: Final[str] = "tool"
BELGIE_TABLE: Final[str] = "belgie"
DEPENDENCIES_TABLE: Final[str] = "dependencies"


class ProjectError(Exception):
    pass


@dataclass(slots=True, kw_only=True, frozen=True)
class BelgieProject:
    root: Path
    dependencies: dict[str, str]
    pyproject: dict[str, Any]
    source: Path

    @property
    def has_dependencies(self) -> bool:
        return bool(self.dependencies)

    @property
    def lockfile_path(self) -> Path:
        return self.root / LOCKFILE_NAME


def read_file_backup(path: Path) -> bytes | None:
    return path.read_bytes() if path.is_file() else None


def restore_file(path: Path, previous: bytes | None) -> None:
    if previous is None:
        path.unlink(missing_ok=True)
    else:
        path.write_bytes(previous)


@contextmanager
def preserve_file_on_error(path: Path) -> Iterator[None]:
    previous = read_file_backup(path)
    try:
        yield
    except BaseException:
        restore_file(path, previous)
        raise


def read_pyproject_document(root: Path) -> dict[str, Any]:
    pyproject_path = root / PYPROJECT_NAME
    if not pyproject_path.is_file():
        msg = f"No pyproject.toml found at {root}"
        raise ProjectError(msg)
    try:
        document = rtoml.load(pyproject_path)
    except (OSError, UnicodeDecodeError, rtoml.TomlParsingError) as exc:
        msg = f"Invalid pyproject.toml at {pyproject_path}: {exc}"
        raise ProjectError(msg) from exc
    if not isinstance(document, dict):
        msg = f"Invalid pyproject.toml at {pyproject_path}"
        raise ProjectError(msg)
    return document


def write_pyproject_document(root: Path, document: dict[str, Any]) -> None:
    path = root / PYPROJECT_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(rtoml.dumps(_reorder_for_rtoml(document), pretty=True), encoding="utf-8")


def _is_table_like(value: object) -> bool:
    if isinstance(value, dict):
        return True
    return isinstance(value, list) and bool(value) and all(isinstance(item, dict) for item in value)


def _reorder_for_rtoml(value: object) -> object:
    # rtoml emits list[dict] as [[array-of-tables]]; TOML requires those after
    # sibling key/values, so put nested tables / AoTs last within each table.
    if isinstance(value, dict):
        values: list[tuple[str, object]] = []
        tables: list[tuple[str, object]] = []
        for key, item in value.items():
            reordered = _reorder_for_rtoml(item)
            (tables if _is_table_like(item) else values).append((str(key), reordered))
        return dict([*values, *tables])
    if isinstance(value, list):
        return [_reorder_for_rtoml(item) for item in value]
    return value


def set_dependency_in_document(
    document: dict[str, Any],
    alias: str,
    value: str,
    *,
    validate: bool = False,
) -> None:
    if validate:
        if not alias.strip():
            msg = "Dependency alias must not be empty"
            raise ProjectError(msg)
        if not value.strip():
            msg = "Dependency specifier must not be empty"
            raise ProjectError(msg)

    dependencies = _ensure_dependencies_table(document)
    dependencies[alias] = value


def _ensure_dependencies_table(document: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(tool := document.setdefault(TOOL_TABLE, {}), dict):
        msg = "[tool] must be a table"
        raise ProjectError(msg)
    if not isinstance(belgie := tool.setdefault(BELGIE_TABLE, {}), dict):
        msg = "[tool.belgie] must be a table"
        raise ProjectError(msg)
    if not isinstance(dependencies := belgie.setdefault(DEPENDENCIES_TABLE, {}), dict):
        msg = "[tool.belgie.dependencies] must be a table"
        raise ProjectError(msg)
    return dependencies


def _parse_dependencies(document: dict[str, Any]) -> dict[str, str]:
    try:
        return parse_tool_table(document, BELGIE_TABLE, DEPENDENCIES_TABLE)
    except PyprojectError as exc:
        raise ProjectError(str(exc)) from exc


def load_project(root: Path) -> BelgieProject:
    return _load_project_from_document(root, read_pyproject_document(root))


def discover_project(*, project: Path | None = None, start: Path | None = None) -> BelgieProject:
    if project is not None:
        return load_project(project.resolve())

    try:
        root = discover_pyproject_root(start=start)
    except PyprojectError as exc:
        raise ProjectError(str(exc)) from exc
    return load_project(root)


def _parse_source(document: dict[str, Any]) -> Path:
    try:
        return parse_belgie_tool_config(document).source
    except PyprojectError as exc:
        raise ProjectError(str(exc)) from exc


def _load_project_from_document(root: Path, document: dict[str, Any]) -> BelgieProject:
    return BelgieProject(
        root=root.resolve(),
        dependencies=_parse_dependencies(document),
        pyproject=document,
        source=_parse_source(document),
    )
