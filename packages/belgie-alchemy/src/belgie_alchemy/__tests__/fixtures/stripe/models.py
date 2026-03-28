from __future__ import annotations

from brussels.base import DataclassBase
from brussels.mixins import PrimaryKeyMixin, TimestampMixin

from belgie_alchemy.stripe.mixins import StripeSubscriptionMixin


class Subscription(DataclassBase, PrimaryKeyMixin, TimestampMixin, StripeSubscriptionMixin):
    pass
