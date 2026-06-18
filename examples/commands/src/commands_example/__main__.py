import asyncio
from pathlib import Path
from typing import Final

from belgie import Command, Runtime
from belgie.dependencies import ainstall

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]


async def run_version_command() -> None:
    await ainstall(cwd=PROJECT_ROOT)
    async with Runtime.from_folder(PROJECT_ROOT) as runtime:
        await runtime(Command("vite"))("--version")


def main() -> None:
    asyncio.run(run_version_command())


if __name__ == "__main__":
    main()
