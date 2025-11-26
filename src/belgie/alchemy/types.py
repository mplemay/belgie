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
            msg = f"DateTimeUTC expects datetime or None, got {type(value)}"
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
