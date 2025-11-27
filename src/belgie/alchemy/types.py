from datetime import UTC, datetime
from typing import Any

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator


class DateTimeUTC(TypeDecorator[datetime]):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, _dialect: Any) -> datetime | None:  # type: ignore[override]  # noqa: ANN401
        if value is None:
            return None
        if not isinstance(value, datetime):
            type_name = type(value).__name__
            msg = (
                f"DateTimeUTC requires datetime object, got {type_name}. "
                f"If using a date, convert to datetime first: "
                f"datetime.combine(your_date, time())"
            )
            raise TypeError(msg)
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value: Any, _dialect: Any) -> datetime | None:  # type: ignore[override]  # noqa: ANN401
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
