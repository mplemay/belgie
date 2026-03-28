from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from belgie_proto.stripe import StripeAdapterProtocol
from sqlalchemy.ext.asyncio import AsyncSession

from belgie_alchemy.__tests__.fixtures.stripe.models import Subscription
from belgie_alchemy.stripe import StripeAdapter


@pytest_asyncio.fixture
async def adapter(alchemy_session: AsyncSession):  # noqa: ARG001
    yield StripeAdapter(subscription=Subscription)


def test_subscription_mixin_exposes_expected_columns() -> None:
    columns = set(Subscription.__table__.c.keys())  # type: ignore[attr-defined]

    assert {
        "id",
        "plan",
        "reference_id",
        "customer_type",
        "stripe_customer_id",
        "stripe_subscription_id",
        "status",
        "period_start",
        "period_end",
        "cancel_at_period_end",
        "cancel_at",
        "canceled_at",
        "ended_at",
        "billing_interval",
        "created_at",
        "updated_at",
    } <= columns


def test_adapter_satisfies_stripe_protocol(adapter: StripeAdapter[Subscription]) -> None:
    assert isinstance(adapter, StripeAdapterProtocol)


@pytest.mark.asyncio
async def test_create_and_lookup_subscription(
    adapter: StripeAdapter[Subscription],
    alchemy_session: AsyncSession,
) -> None:
    reference_id = uuid4()
    subscription = await adapter.create_subscription(
        alchemy_session,
        plan="pro",
        reference_id=reference_id,
        customer_type="user",
        stripe_customer_id="cus_123",
        stripe_subscription_id="sub_123",
        status="active",
        billing_interval="month",
    )

    by_id = await adapter.get_subscription_by_id(alchemy_session, subscription.id)
    by_stripe_id = await adapter.get_subscription_by_stripe_subscription_id(
        alchemy_session,
        stripe_subscription_id="sub_123",
    )

    assert by_id is not None
    assert by_id.id == subscription.id
    assert by_stripe_id is not None
    assert by_stripe_id.id == subscription.id


@pytest.mark.asyncio
async def test_list_active_and_incomplete_subscriptions(
    adapter: StripeAdapter[Subscription],
    alchemy_session: AsyncSession,
) -> None:
    reference_id = uuid4()
    await adapter.create_subscription(
        alchemy_session,
        plan="starter",
        reference_id=reference_id,
        customer_type="user",
        status="incomplete",
    )
    active_subscription = await adapter.create_subscription(
        alchemy_session,
        plan="pro",
        reference_id=reference_id,
        customer_type="user",
        stripe_subscription_id="sub_active",
        status="active",
    )
    await adapter.create_subscription(
        alchemy_session,
        plan="team",
        reference_id=uuid4(),
        customer_type="organization",
        status="active",
    )

    listed = await adapter.list_subscriptions(
        alchemy_session,
        reference_id=reference_id,
        customer_type="user",
    )
    active = await adapter.get_active_subscription(
        alchemy_session,
        reference_id=reference_id,
        customer_type="user",
    )
    incomplete = await adapter.get_incomplete_subscription(
        alchemy_session,
        reference_id=reference_id,
        customer_type="user",
    )

    assert len(listed) == 2
    assert active is not None
    assert active.id == active_subscription.id
    assert incomplete is not None
    assert incomplete.status == "incomplete"


@pytest.mark.asyncio
async def test_update_subscription_persists_fields(
    adapter: StripeAdapter[Subscription],
    alchemy_session: AsyncSession,
) -> None:
    reference_id = uuid4()
    original = await adapter.create_subscription(
        alchemy_session,
        plan="starter",
        reference_id=reference_id,
        customer_type="user",
        status="incomplete",
    )
    period_start = datetime(2026, 1, 1, tzinfo=UTC)
    period_end = datetime(2026, 2, 1, tzinfo=UTC)

    updated = await adapter.update_subscription(
        alchemy_session,
        subscription_id=original.id,
        plan="pro",
        stripe_customer_id="cus_456",
        stripe_subscription_id="sub_456",
        status="active",
        period_start=period_start,
        period_end=period_end,
        cancel_at_period_end=True,
        billing_interval="month",
    )

    assert updated is not None
    assert updated.plan == "pro"
    assert updated.stripe_customer_id == "cus_456"
    assert updated.stripe_subscription_id == "sub_456"
    assert updated.status == "active"
    assert updated.period_start == period_start
    assert updated.period_end == period_end
    assert updated.cancel_at_period_end is True
    assert updated.billing_interval == "month"
