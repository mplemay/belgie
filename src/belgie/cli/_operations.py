from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import TYPE_CHECKING

from belgie import Environment
from belgie.cli._project import (
    BelgieProject,
    ProjectError,
    _load_project_from_document,
    set_dependency_in_document,
    set_dependency_value_in_document,
    temporary_lockfile,
    write_pyproject_document,
)

if TYPE_CHECKING:
    from collections.abc import Sequence

    from belgie import EnvironmentInstallResult, EnvironmentUpdateResult


def create_environment(project: BelgieProject, *, frozen: bool) -> Environment:
    if not project.has_dependencies:
        msg = f"No [tool.belgie.dependencies] entries found in {project.root / 'pyproject.toml'}"
        raise ProjectError(msg)

    lockfile = project.lockfile_path
    if frozen and not lockfile.is_file():
        msg = f"Missing Belgie lockfile at {lockfile}; run `belgie lock`"
        raise ProjectError(msg)

    return Environment(
        project.dependencies,
        path=project.root,
        lockfile=lockfile if frozen else None,
    )


def lock_project(project: BelgieProject) -> EnvironmentInstallResult:
    with (
        temporary_lockfile(project.root) as temporary,
        create_environment(project, frozen=False) as environment,
    ):
        result = environment.lock(lockfile=temporary)
        commit_lockfile(temporary, project.lockfile_path)
        return result


def install_project(project: BelgieProject, *, frozen: bool) -> EnvironmentInstallResult:
    with create_environment(project, frozen=frozen) as environment:
        return environment.install()


def add_dependency(project: BelgieProject, *, alias: str, specifier: str) -> EnvironmentInstallResult:
    document = deepcopy(project.pyproject)
    set_dependency_in_document(document, alias, specifier)
    updated_project = _load_project_from_document(project.root, document)

    with (
        temporary_lockfile(project.root) as temporary,
        create_environment(updated_project, frozen=False) as environment,
    ):
        result = environment.lock(lockfile=temporary)
        write_pyproject_document(project.root, document)
        commit_lockfile(temporary, project.lockfile_path)
        return result


def update_project(
    project: BelgieProject,
    packages: Sequence[str] | None,
    *,
    latest: bool,
) -> EnvironmentUpdateResult:
    document = deepcopy(project.pyproject)
    with (
        temporary_lockfile(project.root) as temporary,
        create_environment(project, frozen=False) as environment,
    ):
        result = environment.update(packages, latest=latest, lockfile_only=True)
        temporary.write_bytes(Path(result.lockfile).read_bytes())

        for change in result.changes:
            if (current := project.dependencies.get(change.name)) is None:
                msg = f"Belgie updated unknown dependency alias '{change.name}'"
                raise ProjectError(msg)
            set_dependency_value_in_document(
                document,
                change.name,
                updated_dependency_value(change.name, current, change.updated),
            )

        write_pyproject_document(project.root, document)
        commit_lockfile(temporary, project.lockfile_path)
        return result


def commit_lockfile(temporary: Path, lockfile_path: Path) -> None:
    temporary.replace(lockfile_path)


def updated_dependency_value(alias: str, current: str, updated: str) -> str:
    if current.startswith(("npm:", "jsr:")):
        return updated

    prefix = f"npm:{alias}@"
    if not updated.startswith(prefix):
        msg = f"Updated dependency '{alias}' no longer resolves to its npm package: {updated}"
        raise ProjectError(msg)
    return updated.removeprefix(prefix)
