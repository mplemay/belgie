from collections.abc import Awaitable


async def as_coroutine[T](awaitable: Awaitable[T]) -> T:
    return await awaitable
