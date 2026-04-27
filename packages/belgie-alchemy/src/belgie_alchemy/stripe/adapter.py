from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from belgie_proto.stripe import UNSET, StripeAdapterProtocol, StripeUnset
from belgie_proto.stripe.subscription import StripeSubscriptionProtocol
from sqlalchemy import select

if TYPE_CHECKING:
    from uuid import UUID

    from belgie_proto.core.connection import DBConnection
    from belgie_proto.stripe.subscription import StripeBillingInterval, StripeSubscriptionStatus


ACTIVE_SUBSCRIPTION_STATUSES = ("active", "past_due", "paused", "trialing", "unpaid")


class StripeAdapter[
    SubscriptionT: StripeSubscriptionProtocol,
](StripeAdapterProtocol[SubscriptionT]):
    def __init__(self, *, subscription: type[SubscriptionT]) -> None:
        self.subscription_model = subscription

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
    ) -> SubscriptionT:
        subscription = self.subscription_model(
            plan=plan,
            account_id=account_id,
            stripe_customer_id=stripe_customer_id,
            stripe_subscription_id=stripe_subscription_id,
            status=status,
            period_start=period_start,
            period_end=period_end,
            trial_start=trial_start,
            trial_end=trial_end,
            seats=seats,
            cancel_at_period_end=cancel_at_period_end,
            cancel_at=cancel_at,
            canceled_at=canceled_at,
            ended_at=ended_at,
            billing_interval=billing_interval,
            stripe_schedule_id=stripe_schedule_id,
        )
        session.add(subscription)
        try:
            await session.commit()
            await session.refresh(subscription)
        except Exception:
            await session.rollback()
            raise
        return subscription

    async def get_subscription_by_id(
        self,
        session: DBConnection,
        subscription_id: UUID,
    ) -> SubscriptionT | None:
        stmt = select(self.subscription_model).where(self.subscription_model.id == subscription_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_subscription_by_stripe_subscription_id(
        self,
        session: DBConnection,
        *,
        stripe_subscription_id: str,
    ) -> SubscriptionT | None:
        stmt = select(self.subscription_model).where(
            self.subscription_model.stripe_subscription_id == stripe_subscription_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_subscriptions(
        self,
        session: DBConnection,
        *,
        account_id: UUID,
        active_only: bool = False,
    ) -> list[SubscriptionT]:
        stmt = select(self.subscription_model).where(self.subscription_model.account_id == account_id)
        if active_only:
            stmt = stmt.where(self.subscription_model.status.in_(ACTIVE_SUBSCRIPTION_STATUSES))
        stmt = stmt.order_by(self.subscription_model.created_at.desc())
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_active_subscription(
        self,
        session: DBConnection,
        *,
        account_id: UUID,
    ) -> SubscriptionT | None:
        stmt = (
            select(self.subscription_model)
            .where(
                self.subscription_model.account_id == account_id,
                self.subscription_model.status.in_(ACTIVE_SUBSCRIPTION_STATUSES),
            )
            .order_by(self.subscription_model.created_at.desc())
        )
        result = await session.execute(stmt)
        return result.scalars().first()

    async def get_incomplete_subscription(
        self,
        session: DBConnection,
        *,
        account_id: UUID,
    ) -> SubscriptionT | None:
        stmt = (
            select(self.subscription_model)
            .where(
                self.subscription_model.account_id == account_id,
                self.subscription_model.status == "incomplete",
            )
            .order_by(self.subscription_model.created_at.desc())
        )
        result = await session.execute(stmt)
        return result.scalars().first()

    async def update_subscription(  # noqa: C901, PLR0912, PLR0913
        self,
        session: DBConnection,
        *,
        subscription_id: UUID,
        plan: str | StripeUnset = UNSET,
        stripe_customer_id: str | None | StripeUnset = UNSET,
        stripe_subscription_id: str | None | StripeUnset = UNSET,
        status: StripeSubscriptionStatus | StripeUnset = UNSET,
        period_start: datetime | None | StripeUnset = UNSET,
        period_end: datetime | None | StripeUnset = UNSET,
        trial_start: datetime | None | StripeUnset = UNSET,
        trial_end: datetime | None | StripeUnset = UNSET,
        seats: int | None | StripeUnset = UNSET,
        cancel_at_period_end: bool | StripeUnset = UNSET,
        cancel_at: datetime | None | StripeUnset = UNSET,
        canceled_at: datetime | None | StripeUnset = UNSET,
        ended_at: datetime | None | StripeUnset = UNSET,
        billing_interval: StripeBillingInterval | None | StripeUnset = UNSET,
        stripe_schedule_id: str | None | StripeUnset = UNSET,
    ) -> SubscriptionT | None:
        subscription = await self.get_subscription_by_id(session, subscription_id)
        if subscription is None:
            return None

        if not isinstance(plan, StripeUnset):
            subscription.plan = plan
        if not isinstance(stripe_customer_id, StripeUnset):
            subscription.stripe_customer_id = stripe_customer_id
        if not isinstance(stripe_subscription_id, StripeUnset):
            subscription.stripe_subscription_id = stripe_subscription_id
        if not isinstance(status, StripeUnset):
            subscription.status = status
        if not isinstance(period_start, StripeUnset):
            subscription.period_start = period_start
        if not isinstance(period_end, StripeUnset):
            subscription.period_end = period_end
        if not isinstance(trial_start, StripeUnset):
            subscription.trial_start = trial_start
        if not isinstance(trial_end, StripeUnset):
            subscription.trial_end = trial_end
        if not isinstance(seats, StripeUnset):
            subscription.seats = seats
        if not isinstance(cancel_at_period_end, StripeUnset):
            subscription.cancel_at_period_end = cancel_at_period_end
        if not isinstance(cancel_at, StripeUnset):
            subscription.cancel_at = cancel_at
        if not isinstance(canceled_at, StripeUnset):
            subscription.canceled_at = canceled_at
        if not isinstance(ended_at, StripeUnset):
            subscription.ended_at = ended_at
        if not isinstance(billing_interval, StripeUnset):
            subscription.billing_interval = billing_interval
        if not isinstance(stripe_schedule_id, StripeUnset):
            subscription.stripe_schedule_id = stripe_schedule_id
        subscription.updated_at = datetime.now(UTC)

        try:
            await session.commit()
            await session.refresh(subscription)
        except Exception:
            await session.rollback()
            raise
        return subscription
