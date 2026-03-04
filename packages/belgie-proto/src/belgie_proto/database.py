from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable

    from belgie_proto.connection import DBConnection


@runtime_checkable
class DatabaseProtocol(Protocol):
    @property
    def dependency(self) -> Callable[[], DBConnection | AsyncGenerator[DBConnection, None]]: ...
