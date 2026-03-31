"""Test models for alchemy tests."""

from __future__ import annotations

from brussels.base import DataclassBase
from brussels.mixins import PrimaryKeyMixin, TimestampMixin
from sqlalchemy.orm import Mapped, mapped_column

from belgie_alchemy.core.mixins import AccountMixin, CustomerMixin, IndividualMixin, OAuthStateMixin, SessionMixin
from belgie_alchemy.stripe.mixins import StripeCustomerMixin


class Customer(DataclassBase, PrimaryKeyMixin, TimestampMixin, CustomerMixin, StripeCustomerMixin):
    pass


class Individual(IndividualMixin, Customer):
    custom_field: Mapped[str | None] = mapped_column(default=None)


class Account(DataclassBase, PrimaryKeyMixin, TimestampMixin, AccountMixin):
    pass


class Session(DataclassBase, PrimaryKeyMixin, TimestampMixin, SessionMixin):
    pass


class OAuthState(DataclassBase, PrimaryKeyMixin, TimestampMixin, OAuthStateMixin):
    pass
