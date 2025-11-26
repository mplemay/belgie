from __future__ import annotations

from collections.abc import AsyncGenerator, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Protocol, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql.base import ExecutableOption

from belgie.alchemy.mixins import PrimaryKeyMixin, TimestampMixin

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

type Options = Sequence[ExecutableOption]
M = TypeVar("M", bound=DeclarativeBase)


class RepositoryProtocol[M: DeclarativeBase](Protocol):
    model: ClassVar[type[M]]
    session: AsyncSession

    async def one(self, statement: Select[tuple[M]]) -> M: ...

    async def one_or_none(self, statement: Select[tuple[M]]) -> M | None: ...

    async def list(self, statement: Select[tuple[M]]) -> Sequence[M]: ...

    async def paginate(
        self,
        statement: Select[tuple[M]],
        *,
        limit: int,
        page: int,
    ) -> tuple[list[M], int]: ...

    @property
    def base(self) -> Select[tuple[M]]: ...

    async def create(self, obj: M, *, flush: bool = False) -> M: ...

    async def update(
        self,
        obj: M,
        *,
        update_dict: dict[str, Any] | None = None,
        flush: bool = False,
    ) -> M: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class Repository[M: DeclarativeBase]:
    model: ClassVar[type[M]]
    session: AsyncSession

    async def one(self, statement: Select[tuple[M]]) -> M:
        result = await self.session.execute(statement)
        return result.scalar_one()

    async def one_or_none(self, statement: Select[tuple[M]]) -> M | None:
        result = await self.session.execute(statement)
        return result.scalar_one_or_none()

    async def list(self, statement: Select[tuple[M]]) -> Sequence[M]:
        result = await self.session.execute(statement)
        return result.scalars().all()

    async def stream(self, statement: Select[tuple[M]]) -> AsyncGenerator[M, None]:
        async for row in await self.session.stream_scalars(statement):
            yield row

    async def paginate(
        self,
        statement: Select[tuple[M]],
        *,
        limit: int,
        page: int,
    ) -> tuple[Sequence[M], int]:
        offset = max(page - 1, 0) * limit

        count_stmt = select(func.count()).select_from(statement.order_by(None).subquery())
        total = await self.session.execute(count_stmt)

        page_stmt = statement.limit(limit).offset(offset)
        items = await self.list(page_stmt)

        return items, total.scalar_one()

    @property
    def base(self) -> Select[tuple[M]]:
        return select(self.model)

    async def create(self, obj: M, *, flush: bool = False) -> M:
        self.session.add(obj)

        await self._flush(flush=flush)

        return obj

    async def update(
        self,
        obj: M,
        *,
        update_dict: dict[str, Any] | None = None,
        flush: bool = False,
    ) -> M:
        if update_dict:
            for key, value in update_dict.items():
                if hasattr(obj, key):
                    setattr(obj, key, value)

        await self._flush(flush=flush)

        return obj

    async def count(self, statement: Select[tuple[M]]) -> int:
        count_stmt = select(func.count()).select_from(statement.order_by(None).subquery())
        result = await self.session.execute(count_stmt)
        return result.scalar_one()

    async def _flush(self, *, flush: bool) -> None:
        if flush:
            await self.session.flush()


class RepositorySoftDeletionMixin[M: DeclarativeBase, E: TimestampMixin]:
    async def soft_delete(self: RepositoryProtocol[M], obj: E, *, flush: bool = False) -> E:
        obj.deleted_at = func.now()

        self.session.add(obj)
        if flush:
            await self.session.flush()

        return obj


class HasTimestampMixin[M: DeclarativeBase]:
    async def soft_delete(self: RepositoryProtocol[M], obj: M) -> M:
        pass


class HasPrimaryKeyMixin[M: DeclarativeBase, E: PrimaryKeyMixin]:
    model: type[E]

    async def get_by_id(
        self: RepositoryProtocol[M],
        id: UUID,
        *,
        options: Options = (),
    ) -> M | None:
        stmt = self.base.where(self.model.id == id).options(*options)
        return await self.one_or_none(stmt)


class Thing(DeclarativeBase):
    pass


class ThingRepository(Repository[Thing], HasPrimaryKeyMixin[Thing]):
    model = Thing


async def main() -> None:
    from uuid import uuid4

    a = ThingRepository(session=AsyncSession())

    result = await a.get_by_id(id=uuid4())
