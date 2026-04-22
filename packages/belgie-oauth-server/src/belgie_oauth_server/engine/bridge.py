from __future__ import annotations

from typing import TYPE_CHECKING

from asyncer import syncify

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


def run_async[T](func: Callable[..., Awaitable[T]], /, *args: object, **kwargs: object) -> T:
    return syncify(func)(*args, **kwargs)
