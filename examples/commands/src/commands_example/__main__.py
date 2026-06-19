from asyncio import run as asyncio_run
from typing import Final

from belgie import Command, Environment, Runtime

VITE_VERSION: Final[str] = "6"


async def run_version_command() -> None:
    async with Environment({"vite": VITE_VERSION}) as env:
        await env.install()
        async with Runtime(env=env) as runtime:
            await runtime(Command("vite"))("--version")


def main() -> None:
    asyncio_run(run_version_command())


if __name__ == "__main__":
    main()
