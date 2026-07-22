from __future__ import annotations

import asyncio

import pytest

from belgie.agent import BelgieRuntimeSession


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
