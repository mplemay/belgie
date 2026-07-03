from __future__ import annotations

import sys
from importlib import import_module
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from collections.abc import Sequence

CLI_REQUIRED_MESSAGE: Final[str] = 'belgie CLI dependencies are required. Install them with: uv add "belgie[cli]"'


def main(argv: Sequence[str] | None = None) -> None:
    try:
        app_module = import_module("belgie.cli._app")
    except ModuleNotFoundError as import_error:
        if import_error.name in {"rtoml", "typer"}:
            print(CLI_REQUIRED_MESSAGE, file=sys.stderr)  # noqa: T201
            raise SystemExit(1) from import_error
        raise

    app_module.run(argv)


if __name__ == "__main__":
    main()
