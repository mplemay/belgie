from __future__ import annotations

import functools
from collections.abc import Awaitable, Callable
from typing import cast, overload

type MaybeAwaitable[T] = T | Awaitable[T]


@overload
def maybe_awaitable[**P, T](callback: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]: ...


@overload
def maybe_awaitable[**P, T](callback: Callable[P, MaybeAwaitable[T]]) -> Callable[P, Awaitable[T]]: ...


def maybe_awaitable[**P, T](callback: Callable[P, MaybeAwaitable[T]]) -> Callable[P, Awaitable[T]]:
    @functools.wraps(callback)
    async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
        result = callback(*args, **kwargs)
        if isinstance(result, Awaitable):
            return await cast("Awaitable[T]", result)
        return result

    return wrapper
