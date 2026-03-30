from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from belgie_proto.stripe.subscription import StripeSubscriptionProtocol

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from belgie_proto.core.connection import DBConnection
    from belgie_proto.stripe.subscription import (
        StripeBillingInterval,
        StripeCustomerType,
        StripeSubscriptionStatus,
    )


@runtime_checkable
class StripeAdapterProtocol[
    SubscriptionT: StripeSubscriptionProtocol,
](Protocol):
    async def create_subscription(  # noqa: PLR0913
        self,
        session: DBConnection,
        *,
        plan: str,
        reference_id: UUID,
        customer_type: StripeCustomerType,
        stripe_customer_id: str | None = None,
        stripe_subscription_id: str | None = None,
        status: StripeSubscriptionStatus = "incomplete",
        period_start: datetime | None = None,
        period_end: datetime | None = None,
        cancel_at_period_end: bool = False,
        cancel_at: datetime | None = None,
        canceled_at: datetime | None = None,
        ended_at: datetime | None = None,
        billing_interval: StripeBillingInterval | None = None,
    ) -> SubscriptionT: ...

    async def get_subscription_by_id(
        self,
        session: DBConnection,
        subscription_id: UUID,
    ) -> SubscriptionT | None: ...

    async def get_subscription_by_stripe_subscription_id(
        self,
        session: DBConnection,
        *,
        stripe_subscription_id: str,
    ) -> SubscriptionT | None: ...

    async def list_subscriptions(
        self,
        session: DBConnection,
        *,
        reference_id: UUID,
        customer_type: StripeCustomerType,
    ) -> list[SubscriptionT]: ...

    async def get_active_subscription(
        self,
        session: DBConnection,
        *,
        reference_id: UUID,
        customer_type: StripeCustomerType,
    ) -> SubscriptionT | None: ...

    async def get_incomplete_subscription(
        self,
        session: DBConnection,
        *,
        reference_id: UUID,
        customer_type: StripeCustomerType,
    ) -> SubscriptionT | None: ...

    async def update_subscription(  # noqa: PLR0913
        self,
        session: DBConnection,
        *,
        subscription_id: UUID,
        plan: str | None = None,
        stripe_customer_id: str | None = None,
        stripe_subscription_id: str | None = None,
        status: StripeSubscriptionStatus | None = None,
        period_start: datetime | None = None,
        period_end: datetime | None = None,
        cancel_at_period_end: bool | None = None,
        cancel_at: datetime | None = None,
        canceled_at: datetime | None = None,
        ended_at: datetime | None = None,
        billing_interval: StripeBillingInterval | None = None,
    ) -> SubscriptionT | None: ...
