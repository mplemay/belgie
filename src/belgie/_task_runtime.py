from __future__ import annotations

from argparse import ArgumentParser, Namespace
from pathlib import Path
from sys import stderr
from typing import TYPE_CHECKING

from belgie._core import BelgieError, _run_task_npm_bin

if TYPE_CHECKING:
    from collections.abc import Sequence


def main(args: Sequence[str] | None = None) -> int:
    parser = ArgumentParser(prog="python -m belgie._task_runtime")
    subparsers = parser.add_subparsers(dest="runtime_command", required=True)
    npm_bin = subparsers.add_parser("npm-bin")
    npm_bin.add_argument("--project-cwd", required=True)
    npm_bin.add_argument("--cwd", required=True)
    npm_bin.add_argument("--command-name", required=True)
    npm_bin.add_argument("script_path")
    npm_bin.add_argument("argv", nargs="*")
    namespace = parser.parse_args(args)
    return run_npm_bin(namespace)


def run_npm_bin(namespace: Namespace) -> int:
    try:
        return _run_task_npm_bin(
            Path(namespace.project_cwd),
            Path(namespace.cwd),
            namespace.command_name,
            Path(namespace.script_path),
            list(namespace.argv),
        )
    except BelgieError as error:
        stderr.write(f"{error}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
