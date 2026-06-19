from os import PathLike
from pathlib import Path
from typing import Final

from belgie import Environment, Runtime, Script

SOURCE: Final[str] = """
import { join } from "std_path";

export default function run() {
  return join.name;
}
"""


def resolve_join_export(cwd: str | PathLike[str] | None = None) -> str:
    with Environment({"std_path": "jsr:@std/path@^1"}, cwd=cwd) as env:
        env.install()
        with Runtime(env=env) as runtime:
            return str(runtime(Script(SOURCE))())


async def resolve_join_export_async(cwd: str | PathLike[str] | None = None) -> str:
    async with Environment({"std_path": "jsr:@std/path@^1"}, cwd=cwd) as env:
        await env.install()
        async with Runtime(env=env) as runtime:
            return str(await runtime(Script(SOURCE))())


async def main() -> None:
    print(await resolve_join_export_async(Path.cwd()))  # noqa: T201


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
