from pathlib import Path
from typing import Final

from belgie import Runtime, Script

PACKAGE_DIR: Final[Path] = Path(__file__).resolve().parent
PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]


async def greet(name: str) -> str:
    script = Script.from_file(PACKAGE_DIR / "greet.ts")
    async with Runtime.from_folder(PROJECT_ROOT)(script) as run:
        result = await run({"name": name})
    return str(result["greeting"])


async def main() -> None:
    print(await greet("belgie"))  # noqa: T201


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
