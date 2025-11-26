from datetime import UTC, datetime
from enum import StrEnum

import pytest
from sqlalchemy import Integer
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from belgie.alchemy.base import Base
from belgie.alchemy.types import DateTimeUTC, ScopesJSON


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, init=False)
    happened_at: Mapped[datetime] = mapped_column(DateTimeUTC, nullable=False)


@pytest.mark.asyncio
async def test_datetimeutc_roundtrip(
    alchemy_engine: AsyncEngine,
    alchemy_session: AsyncSession,
) -> None:
    async with alchemy_engine.begin() as conn:
        await conn.run_sync(Event.__table__.create, checkfirst=True)

    naive = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    aware = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

    event1 = Event(happened_at=naive)
    event2 = Event(happened_at=aware)

    alchemy_session.add_all([event1, event2])
    await alchemy_session.commit()

    rows = (await alchemy_session.execute(Event.__table__.select())).all()
    values = [row.happened_at for row in rows]
    assert all(val.tzinfo is UTC for val in values)


def test_datetimeutc_rejects_non_datetime() -> None:
    dt = DateTimeUTC()
    with pytest.raises(TypeError):
        dt.process_bind_param("not-a-datetime", None)  # type: ignore[arg-type]


class ScopeModel(Base):
    __tablename__ = "scope_test"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, init=False)
    scopes: Mapped[list[str] | None] = mapped_column(ScopesJSON, nullable=True)


@pytest.mark.asyncio
async def test_scopesjson_roundtrip_with_strenum(
    alchemy_engine: AsyncEngine,
    alchemy_session: AsyncSession,
) -> None:
    """Test that ScopesJSON handles StrEnum values correctly."""

    class AppScope(StrEnum):
        READ = "resource:read"
        WRITE = "resource:write"
        ADMIN = "admin"

    async with alchemy_engine.begin() as conn:
        await conn.run_sync(ScopeModel.__table__.create, checkfirst=True)

    # Create model with StrEnum scopes
    model = ScopeModel(scopes=[AppScope.READ, AppScope.ADMIN])
    alchemy_session.add(model)
    await alchemy_session.commit()

    # Retrieve and verify
    refreshed = await alchemy_session.get(ScopeModel, model.id)
    assert refreshed is not None
    assert refreshed.scopes == ["resource:read", "admin"]


@pytest.mark.asyncio
async def test_scopesjson_handles_none(
    alchemy_engine: AsyncEngine,
    alchemy_session: AsyncSession,
) -> None:
    """Test that ScopesJSON handles None values."""
    async with alchemy_engine.begin() as conn:
        await conn.run_sync(ScopeModel.__table__.create, checkfirst=True)

    model = ScopeModel(scopes=None)
    alchemy_session.add(model)
    await alchemy_session.commit()

    refreshed = await alchemy_session.get(ScopeModel, model.id)
    assert refreshed is not None
    assert refreshed.scopes is None


def test_scopesjson_converts_enum_to_string() -> None:
    """Test that ScopesJSON process_bind_param converts StrEnum to strings."""

    class TestScope(StrEnum):
        FOO = "foo"
        BAR = "bar"

    sj = ScopesJSON()
    result = sj.process_bind_param([TestScope.FOO, TestScope.BAR], None)
    assert result == ["foo", "bar"]


def test_scopesjson_handles_none_in_bind() -> None:
    """Test that ScopesJSON process_bind_param handles None."""
    sj = ScopesJSON()
    result = sj.process_bind_param(None, None)
    assert result is None
