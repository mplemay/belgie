from __future__ import annotations

from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass
from typing import Any, Protocol, TypeVar, runtime_checkable

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.base import ExecutableOption

from belgie.alchemy.base import Base
from belgie.alchemy.utils import utc_now

type Options = Sequence[ExecutableOption]

M = TypeVar("M", bound=Base)
ID = TypeVar("ID")


@runtime_checkable
class ModelIDProtocol(Protocol):
    id: Any


@runtime_checkable
class ModelDeletedAtProtocol(Protocol):
    deleted_at: Any


class RepositoryProtocol[M_co](Protocol):
    model: type[M_co]

    async def one(self, statement: Select[tuple[M_co]]) -> M_co: ...

    async def one_or_none(self, statement: Select[tuple[M_co]]) -> M_co | None: ...

    async def list(self, statement: Select[tuple[M_co]]) -> Sequence[M_co]: ...

    async def paginate(
        self,
        statement: Select[tuple[M_co]],
        *,
        limit: int,
        page: int,
    ) -> tuple[list[M_co], int]: ...

    @property
    def base(self) -> Select[tuple[M_co]]: ...

    async def create(self, obj: M_co, *, flush: bool = False) -> M_co: ...

    async def update(
        self,
        obj: M_co,
        *,
        update_dict: dict[str, Any] | None = None,
        flush: bool = False,
    ) -> M_co: ...


@dataclass(kw_only=True)
class RepositoryBase[M_co: M]:
    session: AsyncSession
    model: type[M_co] | None = None

    def __post_init__(self) -> None:
        if self.model is None:
            self.model = getattr(type(self), "model", None)
        if self.model is None:
            msg = "RepositoryBase requires a model"
            raise ValueError(msg)

    async def one(self, statement: Select[tuple[M_co]]) -> M_co:
        result = await self.session.execute(statement)
        return result.scalar_one()

    async def one_or_none(self, statement: Select[tuple[M_co]]) -> M_co | None:
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def list(self, statement: Select[tuple[M_co]]) -> Sequence[M_co]:
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def stream(self, statement: Select[tuple[M_co]]) -> AsyncGenerator[M_co, None]:
        async for row in self.session.stream_scalars(statement):
            yield row

    async def paginate(
        self,
        statement: Select[tuple[M_co]],
        *,
        limit: int,
        page: int,
    ) -> tuple[list[M_co], int]:
        offset = max(page - 1, 0) * limit
        count_stmt = select(func.count()).select_from(statement.order_by(None).subquery())
        total = (await self.session.execute(count_stmt)).scalar_one()
        page_stmt = statement.limit(limit).offset(offset)
        items = list(await self.list(page_stmt))
        return items, int(total)

    @property
    def base(self) -> Select[tuple[M_co]]:
        return select(self.model)

    async def create(self, obj: M_co, *, flush: bool = False) -> M_co:
        self.session.add(obj)
        if flush:
            await self.session.flush()
        return obj

    async def update(
        self,
        obj: M_co,
        *,
        update_dict: dict[str, Any] | None = None,
        flush: bool = False,
    ) -> M_co:
        if update_dict:
            for key, value in update_dict.items():
                if hasattr(obj, key):
                    setattr(obj, key, value)
        if flush:
            await self.session.flush()
        return obj

    async def count(self, statement: Select[tuple[M_co]]) -> int:
        count_stmt = select(func.count()).select_from(statement.order_by(None).subquery())
        return int((await self.session.execute(count_stmt)).scalar_one())


class RepositorySoftDeletionMixin[M_co: ModelDeletedAtProtocol](RepositoryBase[M_co]):
    @property  # type: ignore[override]
    def base(self) -> Select[tuple[M_co]]:
        return select(self.model).where(self.model.deleted_at.is_(None))

    @property
    def all(self) -> Select[tuple[M_co]]:
        return select(self.model)

    async def soft_delete(self, obj: M_co, *, flush: bool = False) -> M_co:
        obj.deleted_at = utc_now()
        self.session.add(obj)
        if flush:
            await self.session.flush()
        return obj


class RepositoryIDMixin[M_co: ModelIDProtocol, ID_co](RepositoryBase[M_co]):
    async def get_by_id(
        self,
        id: ID_co,  # noqa: A002
        *,
        options: Options = (),
        include_deleted: bool = False,
    ) -> M_co | None:
        base_stmt = self.all if include_deleted and hasattr(self, "all") else self.base
        stmt = base_stmt.where(self.model.id == id).options(*options)
        return await self.one_or_none(stmt)
