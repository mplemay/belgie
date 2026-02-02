"""SQLAlchemy 2.0 building blocks for database models.

This module provides opinionated defaults and utilities for SQLAlchemy:
- Base: Declarative base with dataclass mapping and sensible defaults
- Mixins: PrimaryKeyMixin (UUID), TimestampMixin (created/updated/deleted)
- Types: DateTimeUTC (timezone-aware datetime storage)

Usage:
    from belgie_alchemy import Base, PrimaryKeyMixin, TimestampMixin, DateTimeUTC

    class MyModel(Base, PrimaryKeyMixin, TimestampMixin):
        __tablename__ = "my_models"

        name: Mapped[str]
        created_on: Mapped[datetime] = mapped_column(DateTimeUTC)

For complete auth model examples, see examples/alchemy/auth_models.py
"""

from belgie_alchemy.adapter import AlchemyAdapter
from belgie_alchemy.base import Base
from belgie_alchemy.mixins import PrimaryKeyMixin, TimestampMixin
from belgie_alchemy.settings import DatabaseSettings
from belgie_alchemy.types import DateTimeUTC

__all__ = [
    "AlchemyAdapter",
    "Base",
    "DatabaseSettings",
    "DateTimeUTC",
    "PrimaryKeyMixin",
    "TimestampMixin",
]
