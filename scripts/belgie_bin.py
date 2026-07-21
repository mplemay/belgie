from __future__ import annotations

import os
import subprocess
import sys
from typing import Final

from belgie import Environment
from belgie.cli._project import ProjectError, discover_project
from belgie.errors import BelgieRuntimeError

TOOLS_DIR_NAME: Final[str] = ".belgie-tools"
USAGE_EXIT_CODE: Final[int] = 2
MIN_ARGV_LEN: Final[int] = 2


def main(argv: list[str]) -> int:
    if len(argv) < MIN_ARGV_LEN:
        print(f"usage: {argv[0]} <binary> [args...]", file=sys.stderr)
        return USAGE_EXIT_CODE

    binary, *args = argv[1:]
    project = discover_project(project=None)
    tools_root = project.root / TOOLS_DIR_NAME
    tools_root.mkdir(parents=True, exist_ok=True)

    lockfile = project.lockfile_path
    if not lockfile.is_file():
        print(f"Missing Belgie lockfile at {lockfile}; run `belgie lock`", file=sys.stderr)
        return 1

    # Persist under .belgie-tools so the repo root has no node_modules — ephemeral
    # Environment tests symlink node_modules into the workspace cwd.
    with Environment(
        project.dependencies,
        path=tools_root,
        lockfile=lockfile,
    ) as environment:
        environment.install()

    # Run the native npm bin via subprocess. `belgie.Command` executes under Deno and
    # hits a tinypool worker-exit flake for oxfmt when formatting many files.
    bin_path = tools_root / "node_modules" / ".bin" / binary
    if not bin_path.is_file():
        print(f"Missing Belgie binary at {bin_path}", file=sys.stderr)
        return 1

    env = os.environ.copy()
    env["PATH"] = f"{bin_path.parent}{os.pathsep}{env.get('PATH', '')}"
    completed = subprocess.run(  # noqa: S603 — trusted Belgie-installed tooling binary
        [str(bin_path), *args],
        cwd=project.root,
        env=env,
        check=False,
    )
    return completed.returncode


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv))
    except (BelgieRuntimeError, ProjectError) as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1) from exc
