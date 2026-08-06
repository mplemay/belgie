from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Final

import rtoml
import tomlkit
from tomlkit.exceptions import TOMLKitError
from tomlkit.items import InlineTable, String, StringType, Table

from belgie._pyproject import (
    BelgieToolConfig,
    PyprojectError,
    TypeScriptConfig,
    discover_pyproject_root,
    parse_belgie_tool_config,
    parse_tool_table,
)

if TYPE_CHECKING:
    from collections.abc import Iterator, Mapping
    from pathlib import Path

    from tomlkit.toml_document import TOMLDocument

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
    module: bool
    minimum_dependency_age: str | None
    pyproject: dict[str, Any]
    source: Path
    typescript: TypeScriptConfig

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


def update_belgie_dependencies(root: Path, updates: Mapping[str, str]) -> None:
    path = root / PYPROJECT_NAME
    if not path.is_file():
        msg = f"No pyproject.toml found at {root}"
        raise ProjectError(msg)
    try:
        document = tomlkit.parse(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, TOMLKitError) as exc:
        msg = f"Invalid pyproject.toml at {path}: {exc}"
        raise ProjectError(msg) from exc

    dependencies = _ensure_tomlkit_dependencies_table(document)
    preferred_literal = _preferred_literal(dependencies)
    for alias, value in updates.items():
        _validate_dependency_entry(alias, value)
        _set_dep_string(dependencies, alias, value, preferred_literal=preferred_literal)

    path.write_text(tomlkit.dumps(document), encoding="utf-8")


def _validate_dependency_entry(alias: str, value: str) -> None:
    if not alias.strip():
        msg = "Dependency alias must not be empty"
        raise ProjectError(msg)
    if not value.strip():
        msg = "Dependency specifier must not be empty"
        raise ProjectError(msg)


def _is_literal_string(value: object) -> bool:
    return isinstance(value, String) and value.type in (StringType.SLL, StringType.MLL)


def _preferred_literal(dependencies: Table | InlineTable) -> bool:
    for value in dependencies.values():
        if isinstance(value, String):
            return _is_literal_string(value)
    return False


def _set_dep_string(
    dependencies: Table | InlineTable,
    alias: str,
    value: str,
    *,
    preferred_literal: bool,
) -> None:
    if alias in dependencies and isinstance(current := dependencies[alias], String):
        dependencies[alias] = tomlkit.string(value, literal=_is_literal_string(current))
        return
    dependencies[alias] = tomlkit.string(value, literal=preferred_literal)


def _tomlkit_child_table(
    parent: TOMLDocument | Table | InlineTable,
    key: str,
    *,
    label: str,
    super_table: bool = False,
) -> Table | InlineTable:
    value = parent.get(key)
    if value is None:
        table = tomlkit.table(is_super_table=super_table)
        parent[key] = table
        return table
    if not isinstance(value, (Table, InlineTable)):
        msg = f"{label} must be a table"
        raise ProjectError(msg)
    return value


def _ensure_tomlkit_dependencies_table(document: TOMLDocument) -> Table | InlineTable:
    tool = _tomlkit_child_table(document, TOOL_TABLE, label="[tool]", super_table=True)
    belgie = _tomlkit_child_table(tool, BELGIE_TABLE, label="[tool.belgie]", super_table=True)
    return _tomlkit_child_table(belgie, DEPENDENCIES_TABLE, label="[tool.belgie.dependencies]")


def set_dependency_in_document(document: dict[str, Any], alias: str, value: str) -> None:
    _validate_dependency_entry(alias, value)
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


def _parse_tool_config(document: dict[str, Any]) -> BelgieToolConfig:
    try:
        return parse_belgie_tool_config(document)
    except PyprojectError as exc:
        raise ProjectError(str(exc)) from exc


def _load_project_from_document(root: Path, document: dict[str, Any]) -> BelgieProject:
    config = _parse_tool_config(document)
    return BelgieProject(
        root=root.resolve(),
        dependencies=_parse_dependencies(document),
        module=config.module,
        minimum_dependency_age=config.minimum_dependency_age,
        pyproject=document,
        source=config.source,
        typescript=config.typescript,
    )
