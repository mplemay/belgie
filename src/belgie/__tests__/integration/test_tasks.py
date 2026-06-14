from __future__ import annotations

import pytest

from belgie._core import RunTaskOptions, TaskRunner
from belgie.dependencies import install

pytestmark = pytest.mark.integration


async def test_task_runs_npm_bin_command(
    write_belgie_pyproject,
    deno_executable: str,
) -> None:
    del deno_executable
    pyproject = write_belgie_pyproject(
        dependencies={"vite": "^6"},
        scripts={"version": "vite --version"},
    )
    install(cwd=pyproject.parent)
    await TaskRunner().run(RunTaskOptions(str(pyproject.parent), "version"))


async def test_task_runs_deno_custom_command(
    write_belgie_pyproject,
    deno_executable: str,
) -> None:
    del deno_executable
    pyproject = write_belgie_pyproject(scripts={"deno": "deno --version"})
    await TaskRunner().run(RunTaskOptions(str(pyproject.parent), "deno"))
