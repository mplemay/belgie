from __future__ import annotations

import importlib.metadata
from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer

from belgie.cli._operations import add_dependency, install_project, lock_project, update_project
from belgie.cli._project import ProjectError, discover_project
from belgie.errors import BelgieRuntimeError

if TYPE_CHECKING:
    from collections.abc import Sequence

ProjectDir = Annotated[
    Path | None,
    typer.Option(
        "-C",
        "--project",
        help="Project root containing pyproject.toml",
    ),
]

app = typer.Typer(
    no_args_is_help=True,
    add_completion=False,
    name="belgie",
    help="Belgie project dependency tooling",
)


def _version_callback(value: bool) -> None:  # noqa: FBT001
    if value:
        typer.echo(f"belgie {importlib.metadata.version('belgie')}")
        raise typer.Exit


@app.callback()
def root(
    *,
    version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the belgie version and exit.",
        ),
    ] = False,
) -> None:
    pass


@app.command()
def add(
    alias: Annotated[str, typer.Argument(help="JavaScript import alias")],
    specifier: Annotated[str, typer.Argument(help="npm version requirement or full npm:/jsr: specifier")],
    project: ProjectDir = None,
) -> None:
    discovered = discover_project(project=project)
    result = add_dependency(discovered, alias=alias, specifier=specifier)
    typer.echo(f"Added {alias}. Locked {result.dependencies} dependencies. Lockfile: {discovered.lockfile_path}")


@app.command()
def lock(project: ProjectDir = None) -> None:
    discovered = discover_project(project=project)
    result = lock_project(discovered)
    typer.echo(f"Locked {result.dependencies} dependencies. Lockfile: {discovered.lockfile_path}")


@app.command()
def install(
    project: ProjectDir = None,
    frozen: Annotated[bool, typer.Option("--frozen", help="Require and install from the existing deno.lock")] = False,  # noqa: FBT002
) -> None:
    discovered = discover_project(project=project)
    result = install_project(discovered, frozen=frozen)
    typer.echo(f"Installed {result.dependencies} dependencies. Lockfile: {result.lockfile}")


@app.command()
def update(
    packages: Annotated[list[str] | None, typer.Argument(help="Optional dependency aliases to update")] = None,
    project: ProjectDir = None,
    latest: Annotated[bool, typer.Option("--latest", help="Update to the latest versions")] = False,  # noqa: FBT002
) -> None:
    discovered = discover_project(project=project)
    result = update_project(discovered, packages or None, latest=latest)
    for change in result.changes:
        typer.echo(f"{change.name}: {change.previous} -> {change.updated}")
    typer.echo(f"Lockfile: {discovered.lockfile_path}")


@app.command("list")
def list_dependencies(project: ProjectDir = None) -> None:
    discovered = discover_project(project=project)
    if not discovered.dependencies:
        typer.echo("No [tool.belgie.dependencies] entries found.")
        return
    for alias, specifier in discovered.dependencies.items():
        typer.echo(f"{alias} = {specifier}")


def run(argv: Sequence[str] | None = None) -> None:
    try:
        app(
            list(argv) if argv is not None else None,
            prog_name="belgie",
        )
    except (BelgieRuntimeError, ProjectError) as exc:
        typer.echo(str(exc), err=True)
        raise SystemExit(1) from exc
