from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class DBConnection(Protocol):
    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...

    async def close(self) -> None: ...
