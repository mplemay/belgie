from datetime import UTC, datetime
from typing import Any

from sqlalchemy import ARRAY, JSON, DateTime, String
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


class Scopes(TypeDecorator[list[str] | None]):
    """TypeDecorator for storing scopes with dialect-specific optimizations.

    Uses the most efficient storage for each database:
    - PostgreSQL: ARRAY of TEXT (native array type)
    - SQLite/MySQL/Others: JSON

    Supports any str subclass including StrEnum.
    Converts enum members to string values for storage.

    Example:
        from enum import StrEnum

        class AppScope(StrEnum):
            READ = "resource:read"
            ADMIN = "admin"

        user.scopes = [AppScope.READ, AppScope.ADMIN]
        # PostgreSQL stores as: ARRAY['resource:read', 'admin']
        # SQLite stores as: ["resource:read", "admin"] (JSON)
    """

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect: Any) -> Any:  # noqa: ANN401
        """Load dialect-specific implementation.

        PostgreSQL gets native ARRAY, others get JSON.
        """
        if dialect.name == "postgresql":
            return dialect.type_descriptor(ARRAY(String))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: list[str] | None, _dialect: Any) -> list[str] | None:  # type: ignore[override]  # noqa: ANN401
        """Convert Python value to database value.

        Converts StrEnum members to their string values.
        """
        if value is None:
            return None
        return [str(scope) for scope in value]

    def process_result_value(self, value: Any, _dialect: Any) -> list[str] | None:  # type: ignore[override]  # noqa: ANN401
        """Convert database value to Python value.

        Both ARRAY and JSON return list[str] naturally.
        """
        if value is None:
            return None
        return value
