from __future__ import annotations

import sys
from pathlib import Path
from typing import Final

from belgie._core import BelgieError, _run_node_child

USAGE_EXIT_CODE: Final[int] = 2
OPTIONS_WITH_VALUES: Final[frozenset[str]] = frozenset(
    {
        "--cert",
        "--config",
        "--env-file",
        "--import-map",
        "--location",
        "--log-level",
        "--seed",
        "--v8-flags",
    },
)


def parse_run_args(args: list[str]) -> tuple[Path, list[str]]:
    if not args or args[0] != "run":
        msg = "Belgie child runtime expected Deno-compatible `run` arguments"
        raise ValueError(msg)

    index = 1
    while index < len(args):
        argument = args[index]
        if argument == "--":
            index += 1
            break
        if not argument.startswith("-"):
            break
        option = argument.split("=", maxsplit=1)[0]
        index += 1
        if option in OPTIONS_WITH_VALUES and "=" not in argument:
            index += 1

    if index >= len(args):
        msg = "Belgie child runtime did not receive a module path"
        raise ValueError(msg)
    return Path(args[index]), args[index + 1 :]


def main() -> None:
    try:
        module, argv = parse_run_args(sys.argv[1:])
    except ValueError as error:
        print(error, file=sys.stderr)  # noqa: T201
        raise SystemExit(USAGE_EXIT_CODE) from error
    try:
        exit_code = _run_node_child(module, argv)
    except BelgieError as error:
        print(error, file=sys.stderr)  # noqa: T201
        raise SystemExit(1) from error
    raise SystemExit(exit_code)


if __name__ == "__main__":
    main()
