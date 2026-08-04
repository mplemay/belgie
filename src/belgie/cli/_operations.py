from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

from belgie import Command, Environment, EnvironmentOptions, Runtime
from belgie.cli._project import (
    PYPROJECT_NAME,
    BelgieProject,
    ProjectError,
    _load_project_from_document,
    preserve_file_on_error,
    set_dependency_in_document,
    update_belgie_dependencies,
)
from belgie.cli._specifiers import manifest_dependency_value

if TYPE_CHECKING:
    from collections.abc import Sequence
    from pathlib import Path

    from belgie import EnvironmentInstallResult, EnvironmentUpdateResult


def create_environment(
    project: BelgieProject,
    *,
    frozen: bool,
    minimum_dependency_age: str | None = None,
) -> Environment:
    if not project.has_dependencies:
        msg = f"No [tool.belgie.dependencies] entries found in {project.root / 'pyproject.toml'}"
        raise ProjectError(msg)

    lockfile = project.lockfile_path
    if frozen and not lockfile.is_file():
        msg = f"Missing Belgie lockfile at {lockfile}; run `belgie lock`"
        raise ProjectError(msg)

    configured_age = project.minimum_dependency_age if minimum_dependency_age is None else minimum_dependency_age
    options = None
    if configured_age is not None:
        try:
            options = EnvironmentOptions(minimum_dependency_age=configured_age)
        except ValueError as exc:
            raise ProjectError(str(exc)) from exc
    return Environment(
        project.dependencies,
        path=project.root,
        lockfile=lockfile if frozen else None,
        options=options,
    )


def lock_project(
    project: BelgieProject,
    *,
    minimum_dependency_age: str | None = None,
) -> EnvironmentInstallResult:
    lockfile_path = project.lockfile_path
    with (
        preserve_file_on_error(lockfile_path),
        create_environment(
            project,
            frozen=False,
            minimum_dependency_age=minimum_dependency_age,
        ) as environment,
    ):
        return environment.lock(lockfile=lockfile_path)


def install_project(
    project: BelgieProject,
    *,
    frozen: bool,
    minimum_dependency_age: str | None = None,
) -> EnvironmentInstallResult:
    with create_environment(
        project,
        frozen=frozen,
        minimum_dependency_age=minimum_dependency_age,
    ) as environment:
        return environment.install()


def run_command(  # noqa: PLR0913
    project: BelgieProject,
    command: Sequence[str],
    *,
    cwd: Path | None = None,
    frozen: bool,
    module: bool | None = None,
    minimum_dependency_age: str | None = None,
) -> None:
    if not command:
        msg = "Missing command"
        raise ProjectError(msg)

    name, *args = command
    with create_environment(
        project,
        frozen=frozen,
        minimum_dependency_age=minimum_dependency_age,
    ) as environment:
        environment.install()
        with Runtime(env=environment) as runtime:
            runtime(
                Command(
                    name,
                    cwd=str(cwd or project.root),
                    module=project.module if module is None else module,
                ),
            )(*args)


def add_dependency(
    project: BelgieProject,
    *,
    alias: str,
    specifier: str,
    minimum_dependency_age: str | None = None,
) -> EnvironmentInstallResult:
    document = deepcopy(project.pyproject)
    set_dependency_in_document(document, alias, specifier)
    updated_project = _load_project_from_document(project.root, document)

    lockfile_path = project.lockfile_path
    pyproject_path = project.root / PYPROJECT_NAME
    with (
        preserve_file_on_error(lockfile_path),
        preserve_file_on_error(pyproject_path),
        create_environment(
            updated_project,
            frozen=False,
            minimum_dependency_age=minimum_dependency_age,
        ) as environment,
    ):
        result = environment.lock(lockfile=lockfile_path)
        update_belgie_dependencies(project.root, {alias: specifier})
    return result


def update_project(
    project: BelgieProject,
    packages: Sequence[str] | None,
    *,
    latest: bool,
    minimum_dependency_age: str | None = None,
) -> EnvironmentUpdateResult:
    lockfile_path = project.lockfile_path
    pyproject_path = project.root / PYPROJECT_NAME
    with (
        preserve_file_on_error(lockfile_path),
        preserve_file_on_error(pyproject_path),
        create_environment(
            project,
            frozen=False,
            minimum_dependency_age=minimum_dependency_age,
        ) as environment,
    ):
        result = environment.update(packages, latest=latest, lockfile_only=True)
        updates: dict[str, str] = {}
        for change in result.changes:
            if (current := project.dependencies.get(change.name)) is None:
                msg = f"Belgie updated unknown dependency alias '{change.name}'"
                raise ProjectError(msg)
            updates[change.name] = manifest_dependency_value(
                change.name,
                change.updated,
                current=current,
            )
        if updates:
            update_belgie_dependencies(project.root, updates)
    return result
