from typing import Final

from belgie import Environment, Runtime, Script

SOURCE: Final[str] = """
import { join } from "std_path";

export default function run() {
  return join.name;
}
"""


def resolve_join_export() -> str:
    with Environment({"std_path": "jsr:@std/path@^1"}) as env, Runtime(env=env)(Script(SOURCE)) as run:
        return str(run())


async def resolve_join_export_async() -> str:
    async with Environment({"std_path": "jsr:@std/path@^1"}) as env, Runtime(env=env)(Script(SOURCE)) as run:
        return str(await run())


async def main() -> None:
    print(await resolve_join_export_async())  # noqa: T201


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
