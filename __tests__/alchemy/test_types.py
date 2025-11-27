from datetime import UTC, datetime

import pytest
from sqlalchemy import Integer
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from sqlalchemy.orm import Mapped, mapped_column

from belgie.alchemy.base import Base
from belgie.alchemy.types import DateTimeUTC


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
