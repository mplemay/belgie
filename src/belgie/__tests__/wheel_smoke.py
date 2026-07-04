from __future__ import annotations

import asyncio
import json
from contextlib import chdir
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Final

from belgie import Command, Environment, Runtime, Script

ANSWER: Final[int] = 42
REACT_VERSION: Final[str] = "19.2.6"
COMMAND_OUTPUT: Final[str] = "ok\n"


def check_equal(actual: object, expected: object, description: str) -> None:
    if actual != expected:
        message = f"{description}: expected {expected!r}, got {actual!r}"
        raise RuntimeError(message)


def write_local_package(root: Path) -> None:
    package = root / "local-pkg"
    package.mkdir()
    (package / "package.json").write_text(
        json.dumps(
            {
                "name": "local-pkg",
                "version": "1.0.0",
                "type": "module",
                "exports": "./index.js",
                "bin": {"local-pkg": "./bin.js"},
            },
        ),
        encoding="utf-8",
    )
    (package / "index.js").write_text("export const answer = 42;\n", encoding="utf-8")
    (package / "bin.js").write_text(
        'import { writeFileSync } from "node:fs"; writeFileSync("local-command.txt", "ok\\n");\n',
        encoding="utf-8",
    )


def dependencies() -> dict[str, str]:
    return {
        "local-pkg": "file:./local-pkg",
        "react": REACT_VERSION,
        "semver": "7.7.2",
    }


def sync_smoke(root: Path) -> None:
    write_local_package(root)
    lockfile = root / "deno.lock"
    with chdir(root):
        with Environment(dependencies()) as env:
            env.lock(lockfile=lockfile)
        frozen_lock = lockfile.read_bytes()

        with Environment(dependencies(), lockfile=lockfile, path=root) as env:
            env.install()
            with Runtime(env=env) as runtime:
                check_equal(runtime(Script("export default () => 42"))(), ANSWER, "sync script")
                check_equal(
                    runtime(
                        Script('import React from "react"; export default () => React.version;'),
                    )(),
                    REACT_VERSION,
                    "sync React script",
                )
                check_equal(
                    runtime(
                        Script('import { answer } from "local-pkg"; export default () => answer;'),
                    )(),
                    ANSWER,
                    "sync local package script",
                )
                check_equal(runtime(Command("semver"))("--help"), None, "sync npm command")
                check_equal(runtime(Command("local-pkg"))(), None, "sync local package command")

        check_equal(lockfile.read_bytes(), frozen_lock, "sync frozen lockfile")
        check_equal(
            (root / "local-command.txt").read_text(encoding="utf-8"),
            COMMAND_OUTPUT,
            "sync local package command output",
        )


async def async_smoke(root: Path) -> None:
    write_local_package(root)
    lockfile = root / "deno.lock"
    with chdir(root):
        async with Environment(dependencies()) as env:
            await env.lock(lockfile=lockfile)
        frozen_lock = lockfile.read_bytes()

        async with Environment(dependencies(), lockfile=lockfile, path=root) as env:
            await env.install()
            async with Runtime(env=env) as runtime:
                check_equal(await runtime(Script("export default async () => 42"))(), ANSWER, "async script")
                check_equal(
                    await runtime(
                        Script('import React from "react"; export default async () => React.version;'),
                    )(),
                    REACT_VERSION,
                    "async React script",
                )
                check_equal(
                    await runtime(
                        Script('import { answer } from "local-pkg"; export default async () => answer;'),
                    )(),
                    ANSWER,
                    "async local package script",
                )
                check_equal(await runtime(Command("semver"))("--help"), None, "async npm command")
                check_equal(
                    await runtime(Command("local-pkg"))(),
                    None,
                    "async local package command",
                )

        check_equal(lockfile.read_bytes(), frozen_lock, "async frozen lockfile")
        check_equal(
            (root / "local-command.txt").read_text(encoding="utf-8"),
            COMMAND_OUTPUT,
            "async local package command output",
        )


def main() -> None:
    with TemporaryDirectory(prefix="belgie-wheel-sync-") as tmp:
        sync_smoke(Path(tmp))
    with TemporaryDirectory(prefix="belgie-wheel-async-") as tmp:
        asyncio.run(async_smoke(Path(tmp)))


if __name__ == "__main__":
    main()
