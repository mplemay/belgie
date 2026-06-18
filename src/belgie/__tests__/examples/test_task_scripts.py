from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


async def test_task_scripts_example_main_runs_version_task(task_scripts_module) -> None:
    await task_scripts_module.run_version_task()
