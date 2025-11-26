from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime
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


class ScopesJSON(TypeDecorator[list[str] | None]):
    """TypeDecorator for storing scopes as JSON.

    Supports any str subclass including StrEnum.
    Converts enum members to string values for storage.

    Example:
        from enum import StrEnum

        class AppScope(StrEnum):
            READ = "resource:read"
            ADMIN = "admin"

        user.scopes = [AppScope.READ, AppScope.ADMIN]
        # Stored as: ["resource:read", "admin"]
    """

    impl = JSON
    cache_ok = True

    def process_bind_param(self, value: list[str] | None, _dialect: Any) -> list[str] | None:  # type: ignore[override]  # noqa: ANN401
        if value is None:
            return None
        return [str(scope) for scope in value]

    def process_result_value(self, value: Any, _dialect: Any) -> list[str] | None:  # type: ignore[override]  # noqa: ANN401
        if value is None:
            return None
        return value
