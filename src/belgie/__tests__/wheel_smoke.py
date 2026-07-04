from __future__ import annotations

import asyncio
from contextlib import chdir
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final

from belgie import Command, Environment, Runtime, Script
from belgie.__tests__.helpers.local_package import write_local_package_with_bin

ANSWER: Final[int] = 42
REACT_VERSION: Final[str] = "19.2.6"
COMMAND_OUTPUT: Final[str] = "ok\n"


def dependencies() -> dict[str, str]:
    return {
        "local-pkg": "file:./local-pkg",
        "react": REACT_VERSION,
        "semver": "7.7.2",
    }


def run_smoke(root: Path, *, async_mode: bool) -> None:
    write_local_package_with_bin(root, bin_name="local-pkg")
    lockfile = root / "deno.lock"
    script_source = "export default async () => 42" if async_mode else "export default () => 42"
    react_source = (
        'import React from "react"; export default async () => React.version;'
        if async_mode
        else 'import React from "react"; export default () => React.version;'
    )
    local_source = (
        'import { answer } from "local-pkg"; export default async () => answer;'
        if async_mode
        else 'import { answer } from "local-pkg"; export default () => answer;'
    )
    label = "async" if async_mode else "sync"

    with chdir(root):
        if async_mode:
            asyncio.run(_async_lock_environment(lockfile))
            frozen_lock = lockfile.read_bytes()
            asyncio.run(
                _async_smoke_runtime(lockfile, script_source, react_source, local_source, label),
            )
        else:
            frozen_lock = _sync_smoke_runtime(lockfile, script_source, react_source, local_source, label)

        assert lockfile.read_bytes() == frozen_lock, f"{label} frozen lockfile"
        assert (root / "local-command.txt").read_text(encoding="utf-8") == COMMAND_OUTPUT, (
            f"{label} local package command output"
        )


async def _async_lock_environment(lockfile: Path) -> None:
    async with Environment(dependencies()) as env:
        await env.lock(lockfile=lockfile)


def _sync_smoke_runtime(
    lockfile: Path,
    script_source: str,
    react_source: str,
    local_source: str,
    label: str,
) -> bytes:
    with Environment(dependencies()) as env:
        env.lock(lockfile=lockfile)
    frozen_lock = lockfile.read_bytes()

    with Environment(dependencies(), lockfile=lockfile, path=lockfile.parent) as env:
        env.install()
        with Runtime(env=env) as runtime:
            assert runtime(Script(script_source))() == ANSWER, f"{label} script"
            assert runtime(Script(react_source))() == REACT_VERSION, f"{label} React script"
            assert runtime(Script(local_source))() == ANSWER, f"{label} local package script"
            assert runtime(Command("semver"))("--help") is None, f"{label} npm command"
            assert runtime(Command("local-pkg"))() is None, f"{label} local package command"

    return frozen_lock


async def _async_smoke_runtime(
    lockfile: Path,
    script_source: str,
    react_source: str,
    local_source: str,
    label: str,
) -> None:
    async with Environment(dependencies(), lockfile=lockfile, path=lockfile.parent) as env:
        await env.install()
        async with Runtime(env=env) as runtime:
            assert await runtime(Script(script_source))() == ANSWER, f"{label} script"
            assert await runtime(Script(react_source))() == REACT_VERSION, f"{label} React script"
            assert await runtime(Script(local_source))() == ANSWER, f"{label} local package script"
            assert await runtime(Command("semver"))("--help") is None, f"{label} npm command"
            assert await runtime(Command("local-pkg"))() is None, f"{label} local package command"


def main() -> None:
    with TemporaryDirectory(prefix="belgie-wheel-sync-") as tmp:
        run_smoke(Path(tmp), async_mode=False)
    with TemporaryDirectory(prefix="belgie-wheel-async-") as tmp:
        run_smoke(Path(tmp), async_mode=True)


if __name__ == "__main__":
    main()
