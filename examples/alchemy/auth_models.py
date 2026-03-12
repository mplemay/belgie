"""Reference implementation of authentication models.

USAGE: Copy these models to your project and customize as needed.

Belgie's auth mixins provide the auth schema pieces. Brussels mixins add
the record defaults like `id` and timestamps.
"""

from __future__ import annotations

from brussels.base import DataclassBase
from brussels.mixins import PrimaryKeyMixin, TimestampMixin
from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column

from belgie.alchemy.mixins import AccountMixin, OAuthStateMixin, SessionMixin, UserMixin


class User(DataclassBase, PrimaryKeyMixin, TimestampMixin, UserMixin):
    # Example custom field to show extensibility.
    custom_field: Mapped[str | None] = mapped_column(Text, default=None)


class Account(DataclassBase, PrimaryKeyMixin, TimestampMixin, AccountMixin):
    pass


class Session(DataclassBase, PrimaryKeyMixin, TimestampMixin, SessionMixin):
    pass


class OAuthState(DataclassBase, PrimaryKeyMixin, TimestampMixin, OAuthStateMixin):
    pass


__all__ = ["Account", "OAuthState", "Session", "User"]
