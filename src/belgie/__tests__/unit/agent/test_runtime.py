from __future__ import annotations

import asyncio

import pytest

from belgie.agent import BelgieRuntimeSession
from belgie.agent._runtime import RENDER_REQUEST_KEY, is_render_request


def test_is_render_request_accepts_integer_sentinel() -> None:
    assert is_render_request({RENDER_REQUEST_KEY: 1})


def test_is_render_request_rejects_bool_float_and_non_dicts() -> None:
    assert not is_render_request({RENDER_REQUEST_KEY: True})
    assert not is_render_request({RENDER_REQUEST_KEY: 1.0})
    assert not is_render_request({RENDER_REQUEST_KEY: 0})
    assert not is_render_request({})
    assert not is_render_request("not-a-dict")
    assert not is_render_request(None)


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
