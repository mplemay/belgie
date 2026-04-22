from __future__ import annotations

from functools import partial
from typing import TYPE_CHECKING

from anyio import from_thread

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


def run_async[T](func: Callable[..., Awaitable[T]], /, *args: object, **kwargs: object) -> T:
    if kwargs:
        return from_thread.run(partial(func, *args, **kwargs))
    return from_thread.run(func, *args)
