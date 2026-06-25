import asyncio
from pathlib import Path
from typing import Final

from belgie import Environment, Runtime, Script

SOURCE: Final[str] = """
import { join } from "std_path";

export default function run() {
  return join.name;
}
"""


def resolve_join_export() -> str:
    with Environment({"std_path": "jsr:@std/path@^1"}) as env:
        env.install()
        with Runtime(env=env) as runtime:
            return str(runtime(Script(SOURCE))())


async def resolve_join_export_async() -> str:
    async with Environment({"std_path": "jsr:@std/path@^1"}) as env:
        await env.install()
        async with Runtime(env=env) as runtime:
            return str(await runtime(Script(SOURCE))())


async def _main() -> None:
    async with Environment({"std_path": "jsr:@std/path@^1"}, path=Path.cwd()) as env:
        await env.install()
        async with Runtime(env=env) as runtime:
            print(str(await runtime(Script(SOURCE))()))  # noqa: T201


def main() -> None:
    asyncio.run(_main())


if __name__ == "__main__":
    main()
