import pytest
from belgie_core.utils.callbacks import maybe_awaitable


class AsyncCallable:
    async def __call__(self, value: int) -> int:
        return value + 3


@pytest.mark.asyncio
async def test_maybe_awaitable_runs_sync_functions() -> None:
    def callback(value: int) -> int:
        return value + 1

    assert await maybe_awaitable(callback)(1) == 2


@pytest.mark.asyncio
async def test_maybe_awaitable_runs_async_functions() -> None:
    async def callback(value: int) -> int:
        return value + 2

    assert await maybe_awaitable(callback)(1) == 3


@pytest.mark.asyncio
async def test_maybe_awaitable_awaits_awaitable_results() -> None:
    async def resolved(value: int) -> int:
        return value + 4

    def callback(value: int):
        return resolved(value)

    assert await maybe_awaitable(callback)(1) == 5


@pytest.mark.asyncio
async def test_maybe_awaitable_detects_async_callable_instances() -> None:
    assert await maybe_awaitable(AsyncCallable())(1) == 4
