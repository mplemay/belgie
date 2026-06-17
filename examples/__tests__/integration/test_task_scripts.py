from __future__ import annotations

import sys
from pathlib import Path

import pytest

from belgie.dependencies import install
from belgie.tasks import RunTaskOptions, TaskRunner

pytestmark = pytest.mark.integration


@pytest.fixture
def task_scripts_module(task_scripts_example_dir: Path):
    src_dir = task_scripts_example_dir / "src"
    sys.path.insert(0, str(src_dir))
    try:
        import task_scripts.__main__ as task_scripts_main  # noqa: PLC0415

        yield task_scripts_main
    finally:
        sys.path.remove(str(src_dir))


async def test_task_scripts_example_runs_npm_bin_command(
    task_scripts_example_dir: Path,
    deno_executable: str,
) -> None:
    del deno_executable
    install(cwd=task_scripts_example_dir)
    await TaskRunner().run(RunTaskOptions(str(task_scripts_example_dir), "version"))


async def test_task_scripts_example_main_runs_version_task(
    task_scripts_module,
    deno_executable: str,
) -> None:
    del deno_executable
    await task_scripts_module.run_version_task()
