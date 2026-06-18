from __future__ import annotations

import sys
from typing import Final

from belgie._core import BelgieRuntimeError, _run_task_module

MIN_RUNTIME_ARGS: Final[int] = 4


def main() -> int:
    if len(sys.argv) < MIN_RUNTIME_ARGS:
        sys.stderr.write(
            "Internal Belgie task runtime requires PROJECT COMMAND MODULE [ARGS...]\n",
        )
        return 2

    project_dir, command_name, module_path, *argv = sys.argv[1:]
    try:
        return _run_task_module(project_dir, command_name, module_path, argv)
    except BelgieRuntimeError as error:
        sys.stderr.write(f"{error}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
