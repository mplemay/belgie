"""Reference implementation of authentication models."""

from __future__ import annotations

from brussels.base import DataclassBase
from brussels.mixins import PrimaryKeyMixin, TimestampMixin
from sqlalchemy import Text
from sqlalchemy.orm import Mapped, mapped_column

from belgie.alchemy.mixins import AccountMixin, CustomerMixin, IndividualMixin, OAuthStateMixin, SessionMixin


class Customer(DataclassBase, PrimaryKeyMixin, TimestampMixin, CustomerMixin):
    pass


class Individual(IndividualMixin, Customer):
    custom_field: Mapped[str | None] = mapped_column(Text, default=None)


class Account(DataclassBase, PrimaryKeyMixin, TimestampMixin, AccountMixin):
    pass


class Session(DataclassBase, PrimaryKeyMixin, TimestampMixin, SessionMixin):
    pass


class OAuthState(DataclassBase, PrimaryKeyMixin, TimestampMixin, OAuthStateMixin):
    pass


__all__ = ["Account", "Customer", "Individual", "OAuthState", "Session"]
