from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from belgie.agent import BelgieRuntimeSession, _runtime as agent_runtime
from belgie.agent._runtime import DEFAULT_VITE_SYS_PERMISSIONS, _render_runtime_options


def test_render_runtime_options_omit_host_path_grants(tmp_path: Path) -> None:
    assert not hasattr(agent_runtime, "DEFAULT_VITE_READ_PATHS")
    assert "hostname" not in DEFAULT_VITE_SYS_PERMISSIONS
    assert "networkInterfaces" not in DEFAULT_VITE_SYS_PERMISSIONS
    options = _render_runtime_options(tmp_path)
    assert "RuntimePermissions(configured)" in repr(options)


async def test_default_session_denies_network_access() -> None:
    session = BelgieRuntimeSession()
    async with session:
        result = await session.run_script(
            """
            export default async function run() {
              try {
                await fetch("https://example.com");
                return "allowed";
              } catch (error) {
                return String(error);
              }
            }
            """,
        )

    assert isinstance(result, str)
    assert "requires net access" in result.lower()


async def test_run_script_cancels_runner_when_caller_is_cancelled() -> None:
    session = BelgieRuntimeSession(timeout=30.0)
    async with session:
        task = asyncio.create_task(
            session.run_script("export default async function run() { await new Promise(() => {}); }"),
        )
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.sleep(0.05)
        assert task.cancelled()
