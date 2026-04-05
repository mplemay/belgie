from __future__ import annotations

from belgie_proto.stripe.subscription import StripeSubscriptionProtocol
from brussels.base import DataclassBase
from brussels.mixins import PrimaryKeyMixin, TimestampMixin

from belgie.alchemy.mixins import (
    AccountMixin,
    IndividualMixin,
    OAuthAccountMixin,
    OAuthStateMixin,
    SessionMixin,
    StripeAccountMixin,
    StripeSubscriptionMixin,
)


class Account(DataclassBase, PrimaryKeyMixin, TimestampMixin, AccountMixin, StripeAccountMixin):
    pass


class Individual(IndividualMixin, Account):
    pass


class Subscription(DataclassBase, PrimaryKeyMixin, TimestampMixin, StripeSubscriptionMixin, StripeSubscriptionProtocol):
    pass


class OAuthAccount(DataclassBase, PrimaryKeyMixin, TimestampMixin, OAuthAccountMixin):
    pass


class Session(DataclassBase, PrimaryKeyMixin, TimestampMixin, SessionMixin):
    pass


class OAuthState(DataclassBase, PrimaryKeyMixin, TimestampMixin, OAuthStateMixin):
    pass


__all__ = [
    "Account",
    "Individual",
    "OAuthAccount",
    "OAuthState",
    "Session",
    "Subscription",
]
