from datetime import datetime

from sqlalchemy import Integer
from sqlalchemy.orm import Mapped, mapped_column

from __tests__.alchemy.conftest import User
from belgie.alchemy.base import NAMING_CONVENTION, Base
from belgie.alchemy.types import DateTimeUTC


def test_type_annotation_map_uses_datetimeutc() -> None:
    mapping = Base.type_annotation_map
    assert mapping[datetime] is DateTimeUTC


def test_datetime_annotation_auto_uses_datetimeutc() -> None:
    """Verify that Mapped[datetime] automatically uses DateTimeUTC without explicit column type."""

    class TestModel(Base):
        __tablename__ = "test_auto_datetime"
        id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True, init=False)
        # No explicit DateTimeUTC type specified - should be inferred from type_annotation_map
        timestamp: Mapped[datetime]

    timestamp_column = TestModel.__table__.c.timestamp  # type: ignore[attr-defined]
    assert isinstance(timestamp_column.type, DateTimeUTC)


def test_naming_convention_applied() -> None:
    assert Base.metadata.naming_convention == NAMING_CONVENTION


def test_dataclass_kw_only_init() -> None:
    user = User(email="a@b.com")
    assert user.email == "a@b.com"
