from __future__ import annotations

from typing import TYPE_CHECKING, Literal, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


type StripeSubscriptionStatus = Literal[
    "active",
    "canceled",
    "incomplete",
    "incomplete_expired",
    "past_due",
    "paused",
    "trialing",
    "unpaid",
]
type StripeBillingInterval = Literal["day", "week", "month", "year"]


@runtime_checkable
class StripeSubscriptionProtocol(Protocol):
    id: UUID
    plan: str
    account_id: UUID
    stripe_customer_id: str | None
    stripe_subscription_id: str | None
    status: StripeSubscriptionStatus
    period_start: datetime | None
    period_end: datetime | None
    trial_start: datetime | None
    trial_end: datetime | None
    seats: int | None
    cancel_at_period_end: bool
    cancel_at: datetime | None
    canceled_at: datetime | None
    ended_at: datetime | None
    billing_interval: StripeBillingInterval | None
    stripe_schedule_id: str | None
    created_at: datetime
    updated_at: datetime
