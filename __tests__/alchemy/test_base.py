from datetime import datetime

from sqlalchemy import DateTime

from __tests__.alchemy.conftest import User
from belgie.alchemy.base import NAMING_CONVENTION, Base
from belgie.alchemy.types import DateTimeUTC


def test_type_annotation_map_uses_timezone() -> None:
    mapping = Base.type_annotation_map
    dt_type = mapping[datetime]
    assert isinstance(dt_type, DateTime)
    assert dt_type.timezone is True
    assert mapping[DateTimeUTC] is DateTimeUTC


def test_naming_convention_applied() -> None:
    assert Base.metadata.naming_convention == NAMING_CONVENTION


def test_dataclass_kw_only_init() -> None:
    user = User(email="a@b.com")
    assert user.email == "a@b.com"
