from datetime import UTC, datetime

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator


class DateTimeUTC(TypeDecorator[datetime]):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, _dialect):  # type: ignore[override]
        if value is None:
            return None
        if not isinstance(value, datetime):
            msg = f"DateTimeUTC expects datetime or None, got {type(value)}"
            raise TypeError(msg)
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    def process_result_value(self, value, _dialect):  # type: ignore[override]
        if value is None:
            return None
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)
        return value.astimezone(UTC)
