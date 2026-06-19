from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


async def test_command_example_runs_vite_version(command_module) -> None:
    await command_module.run_version_command()
