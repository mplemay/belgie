from datetime import UTC, datetime

from sqlalchemy import DateTime


def utc_now() -> datetime:
    return datetime.now(UTC)


def build_type_annotation_map() -> dict[type, object]:
    # Lazy import to avoid circular dependency with base.py
    from belgie.alchemy.types import DateTimeUTC

    return {
        datetime: DateTime(timezone=True),
        datetime | None: DateTime(timezone=True),
        DateTimeUTC: DateTimeUTC,
    }
