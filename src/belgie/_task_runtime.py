from __future__ import annotations

import sys
from typing import Final

from belgie._core import _run_task_module
from belgie.errors import BelgieRuntimeError

MIN_RUNTIME_ARGS: Final[int] = 6


def main() -> int:
    if len(sys.argv) < MIN_RUNTIME_ARGS:
        sys.stderr.write(
            "Internal Belgie task runtime requires PROJECT CONFIG LOCKFILE COMMAND MODULE [ARGS...]\n",
        )
        return 2

    project_dir, config_file, lockfile, command_name, module_path, *argv = sys.argv[1:]
    try:
        return _run_task_module(
            project_dir,
            config_file,
            lockfile,
            command_name,
            module_path,
            argv,
        )
    except BelgieRuntimeError as error:
        sys.stderr.write(f"{error}\n")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
