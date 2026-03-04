"""Reference implementation of authentication models.

USAGE: Copy these models to your project and customize as needed.

The defaults come from belgie's auth mixins. Override any field,
relationship, or __tablename__ when your app needs different behavior.
"""

from __future__ import annotations

from brussels.base import DataclassBase
from sqlalchemy.orm import Mapped, mapped_column

from belgie.alchemy.mixins import AccountMixin, OAuthStateMixin, SessionMixin, UserMixin


class User(DataclassBase, UserMixin):
    # Example custom field to show extensibility.
    custom_field: Mapped[str | None] = mapped_column(default=None)


class Account(DataclassBase, AccountMixin):
    pass


class Session(DataclassBase, SessionMixin):
    pass


class OAuthState(DataclassBase, OAuthStateMixin):
    pass


__all__ = ["Account", "OAuthState", "Session", "User"]
