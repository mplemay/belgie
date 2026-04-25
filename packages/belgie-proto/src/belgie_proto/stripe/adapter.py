from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from belgie_proto.stripe.subscription import StripeSubscriptionProtocol

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from belgie_proto.core.connection import DBConnection
    from belgie_proto.stripe.subscription import StripeBillingInterval, StripeSubscriptionStatus


@dataclass(slots=True, frozen=True)
class StripeUnset:
    pass


UNSET = StripeUnset()

type StripePatchValue[T] = T | StripeUnset
type StripeNullablePatchValue[T] = T | None | StripeUnset


@runtime_checkable
class StripeAdapterProtocol[
    SubscriptionT: StripeSubscriptionProtocol,
](Protocol):
    async def create_subscription(  # noqa: PLR0913
        self,
        session: DBConnection,
        *,
        plan: str,
        account_id: UUID,
        stripe_customer_id: str | None = None,
        stripe_subscription_id: str | None = None,
        status: StripeSubscriptionStatus = "incomplete",
        period_start: datetime | None = None,
        period_end: datetime | None = None,
        trial_start: datetime | None = None,
        trial_end: datetime | None = None,
        seats: int | None = None,
        cancel_at_period_end: bool = False,
        cancel_at: datetime | None = None,
        canceled_at: datetime | None = None,
        ended_at: datetime | None = None,
        billing_interval: StripeBillingInterval | None = None,
        stripe_schedule_id: str | None = None,
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
        account_id: UUID,
        active_only: bool = False,
    ) -> list[SubscriptionT]: ...

    async def get_active_subscription(
        self,
        session: DBConnection,
        *,
        account_id: UUID,
    ) -> SubscriptionT | None: ...

    async def get_incomplete_subscription(
        self,
        session: DBConnection,
        *,
        account_id: UUID,
    ) -> SubscriptionT | None: ...

    async def update_subscription(  # noqa: PLR0913
        self,
        session: DBConnection,
        *,
        subscription_id: UUID,
        plan: StripePatchValue[str] = UNSET,
        stripe_customer_id: StripeNullablePatchValue[str] = UNSET,
        stripe_subscription_id: StripeNullablePatchValue[str] = UNSET,
        status: StripePatchValue[StripeSubscriptionStatus] = UNSET,
        period_start: StripeNullablePatchValue[datetime] = UNSET,
        period_end: StripeNullablePatchValue[datetime] = UNSET,
        trial_start: StripeNullablePatchValue[datetime] = UNSET,
        trial_end: StripeNullablePatchValue[datetime] = UNSET,
        seats: StripeNullablePatchValue[int] = UNSET,
        cancel_at_period_end: StripePatchValue[bool] = UNSET,
        cancel_at: StripeNullablePatchValue[datetime] = UNSET,
        canceled_at: StripeNullablePatchValue[datetime] = UNSET,
        ended_at: StripeNullablePatchValue[datetime] = UNSET,
        billing_interval: StripeNullablePatchValue[StripeBillingInterval] = UNSET,
        stripe_schedule_id: StripeNullablePatchValue[str] = UNSET,
    ) -> SubscriptionT | None: ...
