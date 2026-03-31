from __future__ import annotations

from belgie_proto.stripe.subscription import StripeSubscriptionProtocol
from brussels.base import DataclassBase
from brussels.mixins import PrimaryKeyMixin, TimestampMixin

from belgie.alchemy.mixins import (
    AccountMixin,
    CustomerMixin,
    IndividualMixin,
    OAuthStateMixin,
    SessionMixin,
    StripeCustomerMixin,
    StripeSubscriptionMixin,
)


class Customer(DataclassBase, PrimaryKeyMixin, TimestampMixin, CustomerMixin, StripeCustomerMixin):
    pass


class Individual(IndividualMixin, Customer):
    pass


class Subscription(DataclassBase, PrimaryKeyMixin, TimestampMixin, StripeSubscriptionMixin, StripeSubscriptionProtocol):
    pass


class Account(DataclassBase, PrimaryKeyMixin, TimestampMixin, AccountMixin):
    pass


class Session(DataclassBase, PrimaryKeyMixin, TimestampMixin, SessionMixin):
    pass


class OAuthState(DataclassBase, PrimaryKeyMixin, TimestampMixin, OAuthStateMixin):
    pass


__all__ = [
    "Account",
    "Customer",
    "Individual",
    "OAuthState",
    "Session",
    "Subscription",
]
