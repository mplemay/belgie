from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from belgie_proto.stripe import StripeAdapterProtocol
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
        customer_id: UUID,
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
    ) -> SubscriptionT:
        subscription = self.subscription_model(
            plan=plan,
            customer_id=customer_id,
            stripe_customer_id=stripe_customer_id,
            stripe_subscription_id=stripe_subscription_id,
            status=status,
            period_start=period_start,
            period_end=period_end,
            cancel_at_period_end=cancel_at_period_end,
            cancel_at=cancel_at,
            canceled_at=canceled_at,
            ended_at=ended_at,
            billing_interval=billing_interval,
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
        customer_id: UUID,
    ) -> list[SubscriptionT]:
        stmt = (
            select(self.subscription_model)
            .where(self.subscription_model.customer_id == customer_id)
            .order_by(self.subscription_model.created_at.desc())
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_active_subscription(
        self,
        session: DBConnection,
        *,
        customer_id: UUID,
    ) -> SubscriptionT | None:
        stmt = (
            select(self.subscription_model)
            .where(
                self.subscription_model.customer_id == customer_id,
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
        customer_id: UUID,
    ) -> SubscriptionT | None:
        stmt = (
            select(self.subscription_model)
            .where(
                self.subscription_model.customer_id == customer_id,
                self.subscription_model.status == "incomplete",
            )
            .order_by(self.subscription_model.created_at.desc())
        )
        result = await session.execute(stmt)
        return result.scalars().first()

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
    ) -> SubscriptionT | None:
        subscription = await self.get_subscription_by_id(session, subscription_id)
        if subscription is None:
            return None

        updates = {
            "plan": plan,
            "stripe_customer_id": stripe_customer_id,
            "stripe_subscription_id": stripe_subscription_id,
            "status": status,
            "period_start": period_start,
            "period_end": period_end,
            "cancel_at_period_end": cancel_at_period_end,
            "billing_interval": billing_interval,
        }
        for field_name, value in updates.items():
            if value is not None:
                setattr(subscription, field_name, value)
        if cancel_at is not None:
            subscription.cancel_at = cancel_at
        if canceled_at is not None:
            subscription.canceled_at = canceled_at
        if ended_at is not None:
            subscription.ended_at = ended_at
        subscription.updated_at = datetime.now(UTC)

        try:
            await session.commit()
            await session.refresh(subscription)
        except Exception:
            await session.rollback()
            raise
        return subscription
