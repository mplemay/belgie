from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from brussels.base import NAMING_CONVENTION, DataclassBase
from brussels.types import DateTimeUTC
from sqlalchemy import Integer, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Mapped, mapped_column

from belgie_alchemy.__tests__.fixtures.models import User
from belgie_alchemy.settings import SqliteSettings


def test_type_annotation_map_uses_datetimeutc() -> None:
    mapping = DataclassBase.type_annotation_map
    assert mapping[datetime] is DateTimeUTC


def test_datetime_annotation_auto_uses_datetimeutc() -> None:
    """Verify that Mapped[datetime] automatically uses DateTimeUTC without explicit column type."""

    class TestModel(DataclassBase):
        __tablename__ = "test_auto_datetime"
        id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, init=False)
        # No explicit DateTimeUTC type specified - should be inferred from type_annotation_map
        timestamp: Mapped[datetime]

    timestamp_column = TestModel.__table__.c.timestamp  # type: ignore[attr-defined]
    assert isinstance(timestamp_column.type, DateTimeUTC)


def test_naming_convention_applied() -> None:
    assert DataclassBase.metadata.naming_convention == NAMING_CONVENTION


def test_dataclass_kw_only_init() -> None:
    user = User(email="a@b.com")
    assert user.email == "a@b.com"


@pytest.mark.asyncio
async def test_file_based_sqlite_database() -> None:
    """Test that models work correctly with file-based SQLite database."""
    with TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        settings = SqliteSettings(database=str(db_path), echo=False, enable_foreign_keys=True)
        engine = settings.engine

        # Create tables
        async with engine.begin() as conn:
            await conn.run_sync(DataclassBase.metadata.create_all)

        # Create session factory
        session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        # Test basic operations
        async with session_factory() as session:
            # Create user
            user = User(email="file_db_test@example.com", name="Test User")
            session.add(user)
            await session.commit()

            user_id = user.id

        # Verify persistence by reading in new session
        async with session_factory() as session:
            result = await session.execute(select(User).where(User.id == user_id))
            retrieved_user = result.scalar_one()

            assert retrieved_user.email == "file_db_test@example.com"
            assert retrieved_user.name == "Test User"
            assert retrieved_user.created_at is not None
            assert retrieved_user.created_at.tzinfo is UTC

        # Cleanup
        await engine.dispose()

        # Verify database file was created
        assert db_path.exists()
        assert db_path.stat().st_size > 0
