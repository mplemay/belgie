from __future__ import annotations

import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

import rtoml

if TYPE_CHECKING:
    from collections.abc import Iterator

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

    @property
    def has_dependencies(self) -> bool:
        return bool(self.dependencies)

    @property
    def lockfile_path(self) -> Path:
        return self.root / LOCKFILE_NAME


def temporary_file(parent: Path, prefix: str) -> Path:
    descriptor, temporary_name = tempfile.mkstemp(prefix=prefix, dir=parent)
    os.close(descriptor)
    temporary = Path(temporary_name)
    temporary.unlink()
    return temporary


@contextmanager
def temporary_lockfile(root: Path) -> Iterator[Path]:
    temporary = temporary_file(root, f".{LOCKFILE_NAME}.")
    try:
        yield temporary
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def preserve_lockfile(lockfile_path: Path) -> Iterator[None]:
    previous = read_lockfile_backup(lockfile_path)
    try:
        yield
    finally:
        restore_lockfile(lockfile_path, previous)


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
    text = rtoml.dumps(document, pretty=True)
    atomic_write_text(root / PYPROJECT_NAME, text)


def atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = temporary_file(path.parent, f".{path.name}.")
    try:
        temporary.write_bytes(data)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def atomic_commit_if_changed(path: Path, data: bytes) -> None:
    if path.is_file() and path.read_bytes() == data:
        return
    atomic_write_bytes(path, data)


def read_lockfile_backup(lockfile_path: Path) -> bytes | None:
    return lockfile_path.read_bytes() if lockfile_path.is_file() else None


def restore_lockfile(lockfile_path: Path, previous: bytes | None) -> None:
    if previous is None:
        lockfile_path.unlink(missing_ok=True)
    else:
        lockfile_path.write_bytes(previous)


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


def _read_dependencies_table(document: dict[str, Any]) -> dict[str, Any] | None:
    tool = document.get(TOOL_TABLE)
    if tool is None:
        return None
    if not isinstance(tool, dict):
        msg = "[tool] must be a table"
        raise ProjectError(msg)
    belgie = tool.get(BELGIE_TABLE)
    if belgie is None:
        return None
    if not isinstance(belgie, dict):
        msg = "[tool.belgie] must be a table"
        raise ProjectError(msg)
    dependencies = belgie.get(DEPENDENCIES_TABLE)
    if dependencies is None:
        return None
    if not isinstance(dependencies, dict):
        msg = "[tool.belgie.dependencies] must be a table"
        raise ProjectError(msg)
    return dependencies


def _parse_dependencies(document: dict[str, Any]) -> dict[str, str]:
    table = _read_dependencies_table(document)
    if table is None:
        return {}

    dependencies: dict[str, str] = {}
    for alias, value in table.items():
        if not isinstance(alias, str) or not alias.strip() or not isinstance(value, str) or not value.strip():
            msg = "[tool.belgie.dependencies] entries must map non-empty strings to non-empty strings"
            raise ProjectError(msg)
        dependencies[alias] = value
    return dependencies


def load_project(root: Path) -> BelgieProject:
    return _load_project_from_document(root, read_pyproject_document(root))


def discover_project(*, project: Path | None = None, start: Path | None = None) -> BelgieProject:
    if project is not None:
        return load_project(project.resolve())

    start_path = (start or Path.cwd()).resolve()
    if start_path.is_file():
        start_path = start_path.parent

    searched: list[str] = []
    for directory in (start_path, *start_path.parents):
        pyproject_path = directory / PYPROJECT_NAME
        searched.append(str(pyproject_path))
        if pyproject_path.is_file():
            return load_project(directory)

    msg = f"Could not find pyproject.toml. Searched: {', '.join(searched)}"
    raise ProjectError(msg)


def _load_project_from_document(root: Path, document: dict[str, Any]) -> BelgieProject:
    return BelgieProject(
        root=root.resolve(),
        dependencies=_parse_dependencies(document),
        pyproject=document,
    )
