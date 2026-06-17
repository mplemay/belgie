import asyncio
from pathlib import Path
from typing import Final

from belgie.dependencies import ainstall
from belgie.tasks import RunTaskOptions, TaskRunner

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]


async def run_version_task() -> None:
    await ainstall(cwd=PROJECT_ROOT)
    await TaskRunner().run(RunTaskOptions(str(PROJECT_ROOT), "version"))


def main() -> None:
    asyncio.run(run_version_task())


if __name__ == "__main__":
    main()
