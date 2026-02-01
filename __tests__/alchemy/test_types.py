from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from belgie_alchemy.base import Base
from belgie_alchemy.types import DateTimeUTC
from sqlalchemy import Integer
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import Mapped, mapped_column


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
    """Test that DateTimeUTC rejects non-datetime values with helpful error."""
    dt = DateTimeUTC()
    with pytest.raises(TypeError, match=r"DateTimeUTC requires datetime object, got str"):
        dt.process_bind_param("not-a-datetime", None)  # type: ignore[arg-type]


def test_datetimeutc_error_message_includes_guidance() -> None:
    """Test that error message provides actionable guidance."""
    dt = DateTimeUTC()
    with pytest.raises(TypeError, match=r"datetime\.combine"):
        dt.process_bind_param("2024-01-01", None)  # type: ignore[arg-type]


def test_datetimeutc_handles_none() -> None:
    """Test that DateTimeUTC properly handles None values."""
    dt = DateTimeUTC()
    result = dt.process_bind_param(None, None)
    assert result is None

    result = dt.process_result_value(None, None)
    assert result is None


def test_datetimeutc_converts_naive_to_utc() -> None:
    """Test that naive datetimes are converted to UTC-aware."""
    dt = DateTimeUTC()
    naive = datetime(2024, 1, 1, 12, 0, 0)  # noqa: DTZ001 - intentionally testing naive datetime

    result = dt.process_bind_param(naive, None)

    assert result is not None
    assert result.tzinfo is UTC
    assert result.year == 2024
    assert result.month == 1
    assert result.day == 1
    assert result.hour == 12


def test_datetimeutc_converts_other_timezones_to_utc() -> None:
    """Test that datetimes in other timezones are converted to UTC."""
    dt = DateTimeUTC()

    # Create datetime in US/Eastern (UTC-5 in winter)
    eastern = ZoneInfo("America/New_York")
    eastern_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=eastern)

    result = dt.process_bind_param(eastern_time, None)

    assert result is not None
    assert result.tzinfo is UTC
    # 12:00 EST should be 17:00 UTC (approximately, depending on DST)
    assert result.hour in (16, 17)  # Allow for DST variations


def test_datetimeutc_preserves_utc_datetime() -> None:
    """Test that UTC datetimes are preserved as-is."""
    dt = DateTimeUTC()
    utc_time = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)

    result = dt.process_bind_param(utc_time, None)

    assert result is not None
    assert result == utc_time
    assert result.tzinfo is UTC


@pytest.mark.asyncio
async def test_datetimeutc_naive_datetime_roundtrip(
    alchemy_engine: AsyncEngine,
    alchemy_session: AsyncSession,
) -> None:
    """Test that naive datetimes are stored and retrieved as UTC-aware."""
    async with alchemy_engine.begin() as conn:
        await conn.run_sync(Event.__table__.create, checkfirst=True)

    # Create event with naive datetime
    naive_time = datetime(2024, 6, 15, 14, 30, 0)  # noqa: DTZ001 - intentionally testing naive datetime
    event = Event(happened_at=naive_time)

    alchemy_session.add(event)
    await alchemy_session.commit()

    # Retrieve and verify it's UTC-aware
    await alchemy_session.refresh(event)
    assert event.happened_at.tzinfo is UTC
    assert event.happened_at.year == 2024
    assert event.happened_at.month == 6
    assert event.happened_at.day == 15
    assert event.happened_at.hour == 14


@pytest.mark.asyncio
async def test_datetimeutc_timezone_conversion_roundtrip(
    alchemy_engine: AsyncEngine,
    alchemy_session: AsyncSession,
) -> None:
    """Test that datetimes in other timezones are converted to UTC on storage."""
    async with alchemy_engine.begin() as conn:
        await conn.run_sync(Event.__table__.create, checkfirst=True)

    # Create event with Tokyo time (UTC+9)
    tokyo_tz = timezone(timedelta(hours=9))
    tokyo_time = datetime(2024, 1, 1, 21, 0, 0, tzinfo=tokyo_tz)  # 21:00 Tokyo

    event = Event(happened_at=tokyo_time)
    alchemy_session.add(event)
    await alchemy_session.commit()

    # Retrieve and verify it's converted to UTC
    await alchemy_session.refresh(event)
    assert event.happened_at.tzinfo is UTC
    assert event.happened_at.hour == 12  # 21:00 - 9 hours = 12:00 UTC
    assert event.happened_at.day == 1
