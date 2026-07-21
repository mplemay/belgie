from __future__ import annotations

import importlib.metadata
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Annotated, Final

if TYPE_CHECKING:
    from collections.abc import Sequence

CLI_REQUIRED_MESSAGE: Final[str] = 'belgie CLI dependencies are required. Install them with: uv add "belgie[cli]"'

try:
    import typer
except ImportError as exc:
    print(CLI_REQUIRED_MESSAGE, file=sys.stderr)  # noqa: T201
    raise SystemExit(1) from exc

try:
    import rtoml  # noqa: F401
except ImportError as exc:
    print(CLI_REQUIRED_MESSAGE, file=sys.stderr)  # noqa: T201
    raise SystemExit(1) from exc

from belgie.cli._operations import (  # noqa: E402
    add_dependency,
    install_project,
    lock_project,
    run_command,
    update_project,
)
from belgie.cli._project import ProjectError, discover_project  # noqa: E402
from belgie.errors import BelgieRuntimeError  # noqa: E402

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


@app.command(
    context_settings={"allow_extra_args": True, "ignore_unknown_options": True},
)
def run(
    ctx: typer.Context,
    project: ProjectDir = None,
    cwd: Annotated[
        Path | None,
        typer.Option("--cwd", help="Working directory for the command"),
    ] = None,
    module: Annotated[
        bool | None,
        typer.Option(
            "--module/--no-module",
            help="Override [tool.belgie].module for this command",
        ),
    ] = None,
    frozen: Annotated[bool, typer.Option("--frozen/--no-frozen", help="Require and use the existing deno.lock")] = True,  # noqa: FBT002
) -> None:
    discovered = discover_project(project=project)
    run_command(discovered, ctx.args, cwd=cwd, frozen=frozen, module=module)


def main(argv: Sequence[str] | None = None) -> None:
    try:
        app(
            list(argv) if argv is not None else None,
            prog_name="belgie",
        )
    except (BelgieRuntimeError, ProjectError) as exc:
        typer.echo(str(exc), err=True)
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
