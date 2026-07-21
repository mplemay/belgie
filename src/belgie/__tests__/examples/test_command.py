from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


async def test_command_example_runs_vite_version(
    command_module,
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    await command_module.run_version_command()
