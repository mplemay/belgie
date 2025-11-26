from datetime import UTC, datetime
from enum import StrEnum
from unittest.mock import Mock

import pytest
from sqlalchemy import ARRAY, Integer, String
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from belgie.alchemy.base import Base
from belgie.alchemy.types import DateTimeUTC, Scopes


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
    scopes: Mapped[list[str] | None] = mapped_column(Scopes, nullable=True)


@pytest.mark.asyncio
async def test_scopes_roundtrip_with_strenum(
    alchemy_engine: AsyncEngine,
    alchemy_session: AsyncSession,
) -> None:
    """Test that Scopes handles StrEnum values correctly."""

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
async def test_scopes_handles_none(
    alchemy_engine: AsyncEngine,
    alchemy_session: AsyncSession,
) -> None:
    """Test that Scopes handles None values."""
    async with alchemy_engine.begin() as conn:
        await conn.run_sync(ScopeModel.__table__.create, checkfirst=True)

    model = ScopeModel(scopes=None)
    alchemy_session.add(model)
    await alchemy_session.commit()

    refreshed = await alchemy_session.get(ScopeModel, model.id)
    assert refreshed is not None
    assert refreshed.scopes is None


def test_scopes_converts_enum_to_string() -> None:
    """Test that Scopes process_bind_param converts StrEnum to strings."""

    class TestScope(StrEnum):
        FOO = "foo"
        BAR = "bar"

    scopes_type = Scopes()
    result = scopes_type.process_bind_param([TestScope.FOO, TestScope.BAR], None)
    assert result == ["foo", "bar"]


def test_scopes_handles_none_in_bind() -> None:
    """Test that Scopes process_bind_param handles None."""
    scopes_type = Scopes()
    result = scopes_type.process_bind_param(None, None)
    assert result is None


def test_scopes_uses_array_for_postgresql() -> None:
    """Test that Scopes uses ARRAY type for PostgreSQL dialect."""
    scopes_type = Scopes()

    # Mock PostgreSQL dialect
    pg_dialect = Mock()
    pg_dialect.name = "postgresql"
    pg_dialect.type_descriptor.return_value = ARRAY(String)

    result = scopes_type.load_dialect_impl(pg_dialect)
    pg_dialect.type_descriptor.assert_called_once()
    # Verify it was called with ARRAY type
    call_args = pg_dialect.type_descriptor.call_args[0][0]
    assert isinstance(call_args, ARRAY)


def test_scopes_uses_json_for_sqlite() -> None:
    """Test that Scopes uses JSON type for SQLite dialect."""
    scopes_type = Scopes()

    # Mock SQLite dialect
    sqlite_dialect = Mock()
    sqlite_dialect.name = "sqlite"

    scopes_type.load_dialect_impl(sqlite_dialect)
    sqlite_dialect.type_descriptor.assert_called_once()
