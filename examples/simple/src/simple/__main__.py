from pathlib import Path

from belgie import Runtime, Script

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parents[1]


async def greet(name: str) -> str:
    script = Script.from_file(PACKAGE_DIR / "greet.ts")
    async with Runtime(cwd=PROJECT_ROOT)(script) as run:
        result = await run({"name": name})
    return str(result["greeting"])


async def main() -> None:
    print(await greet("belgie"))  # noqa: T201


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
