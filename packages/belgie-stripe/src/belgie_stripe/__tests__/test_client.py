from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from belgie_core.core.settings import BelgieSettings
from fastapi import HTTPException

from belgie_stripe import Stripe, StripeOrganization, StripePlan, StripeSubscription
from belgie_stripe.__tests__.fakes import (
    FakeBelgieClient,
    FakeOrganizationAdapter,
    FakeStripeSDK,
    FakeSubscription,
    InMemoryStripeAdapter,
    make_organization,
    make_session,
    make_user,
)
from belgie_stripe.client import StripeClient
from belgie_stripe.models import (
    BillingPortalRequest,
    ListSubscriptionsRequest,
    UpgradeSubscriptionRequest,
)
from belgie_stripe.utils import sign_success_token


def _build_client(
    *,
    stripe_sdk: FakeStripeSDK | None = None,
    adapter: InMemoryStripeAdapter | None = None,
    user=None,
    organization_adapter: FakeOrganizationAdapter | None = None,
    organization: StripeOrganization | None = None,
    authorize_reference=None,
    on_subscription_created=None,
) -> tuple[StripeClient[FakeSubscription], FakeBelgieClient, FakeStripeSDK, InMemoryStripeAdapter]:
    settings = BelgieSettings(secret="test-secret", base_url="http://localhost:8000")
    user = make_user() if user is None else user
    session = make_session(user_id=user.id)
    belgie_client = FakeBelgieClient(user=user, session=session)
    stripe_sdk = FakeStripeSDK() if stripe_sdk is None else stripe_sdk
    adapter = InMemoryStripeAdapter() if adapter is None else adapter

    client = StripeClient(
        client=belgie_client,
        belgie_settings=settings,
        settings=Stripe(
            stripe_client=stripe_sdk,
            stripe_webhook_secret="whsec_test",
            subscription=StripeSubscription(
                adapter=adapter,
                plans=[StripePlan(name="pro", price_id="price_pro")],
                authorize_reference=authorize_reference,
                on_subscription_created=on_subscription_created,
            ),
            organization=organization,
        ),
        current_user=user,
        current_session=session,
        organization_adapter=organization_adapter,
    )
    return client, belgie_client, stripe_sdk, adapter


@pytest.mark.asyncio
async def test_upgrade_rejects_cross_origin_urls() -> None:
    client, _belgie_client, _stripe_sdk, _adapter = _build_client()

    with pytest.raises(HTTPException, match="same-origin"):
        await client.upgrade(
            data=UpgradeSubscriptionRequest(
                plan="pro",
                success_url="https://evil.example/dashboard",
                cancel_url="/pricing",
            ),
        )


@pytest.mark.asyncio
async def test_ensure_user_customer_lazily_creates_and_persists_customer() -> None:
    client, belgie_client, stripe_sdk, _adapter = _build_client()

    customer_id = await client.ensure_user_customer(metadata={"source": "test"})

    assert customer_id == "cus_1"
    assert belgie_client.user.stripe_customer_id == "cus_1"
    assert stripe_sdk.created_customers == [
        {
            "email": belgie_client.user.email,
            "name": belgie_client.user.name,
            "metadata": {
                "customer_type": "user",
                "reference_id": str(belgie_client.user.id),
                "source": "test",
            },
        },
    ]


@pytest.mark.asyncio
async def test_ensure_organization_customer_creates_customer() -> None:
    organization = make_organization()
    organization_adapter = FakeOrganizationAdapter(organizations={organization.id: organization})
    client, _belgie_client, stripe_sdk, _adapter = _build_client(
        organization_adapter=organization_adapter,
        organization=StripeOrganization(enabled=True),
    )

    customer_id = await client.ensure_organization_customer(
        reference_id=organization.id,
        metadata={"source": "test"},
    )

    assert customer_id == "cus_1"
    assert organization.stripe_customer_id == "cus_1"
    assert stripe_sdk.created_customers == [
        {
            "name": organization.name,
            "metadata": {
                "customer_type": "organization",
                "reference_id": str(organization.id),
                "source": "test",
            },
        },
    ]


@pytest.mark.asyncio
async def test_upgrade_same_plan_does_not_create_customer() -> None:
    user = make_user(stripe_customer_id=None)
    client, _belgie_client, stripe_sdk, adapter = _build_client(user=user)
    await adapter.create_subscription(
        client.client.db,
        plan="pro",
        reference_id=user.id,
        customer_type="user",
        stripe_customer_id=None,
        stripe_subscription_id="sub_existing",
        status="active",
    )

    with pytest.raises(HTTPException, match="already subscribed to this plan"):
        await client.upgrade(
            data=UpgradeSubscriptionRequest(
                plan="pro",
                success_url="/dashboard",
                cancel_url="/pricing",
            ),
        )

    assert stripe_sdk.created_customers == []
    assert client.current_user is not None
    assert client.current_user.stripe_customer_id is None


@pytest.mark.asyncio
async def test_list_subscriptions_requires_reference_for_organization() -> None:
    authorize_reference = AsyncMock(return_value=True)
    client, _belgie_client, _stripe_sdk, _adapter = _build_client(
        authorize_reference=authorize_reference,
    )

    with pytest.raises(HTTPException, match="reference_id is required"):
        await client.list_subscriptions(
            data=ListSubscriptionsRequest(customer_type="organization"),
        )

    authorize_reference.assert_not_awaited()


@pytest.mark.asyncio
async def test_billing_portal_defaults_return_url() -> None:
    client, _belgie_client, stripe_sdk, _adapter = _build_client()

    result = await client.create_billing_portal(
        data=BillingPortalRequest(),
    )

    assert result.url == "https://billing.stripe.test/session"
    assert stripe_sdk.created_billing_portal_sessions == [
        {
            "customer": "cus_1",
            "return_url": "http://localhost:8000/",
        },
    ]


@pytest.mark.asyncio
async def test_handle_webhook_verifies_signature_and_upserts_subscription() -> None:
    hook = AsyncMock()
    stripe_sdk = FakeStripeSDK()
    construct_event = MagicMock()
    user = make_user()
    stripe_sdk.event = {
        "type": "customer.subscription.created",
        "data": {
            "object": {
                "id": "sub_123",
                "customer": "cus_123",
                "status": "active",
                "current_period_start": 1_710_000_000,
                "current_period_end": 1_712_592_000,
                "cancel_at_period_end": False,
                "cancel_at": None,
                "canceled_at": None,
                "ended_at": None,
                "metadata": {
                    "reference_id": str(user.id),
                    "customer_type": "user",
                    "plan": "pro",
                },
                "items": {
                    "data": [
                        {
                            "price": {
                                "id": "price_pro",
                                "recurring": {"interval": "month"},
                            },
                        },
                    ],
                },
            },
        },
    }
    construct_event.return_value = stripe_sdk.event
    stripe_sdk.webhooks.construct_event = construct_event
    client, _belgie_client, _stripe_sdk, adapter = _build_client(
        stripe_sdk=stripe_sdk,
        user=user,
        on_subscription_created=hook,
    )
    request = MagicMock()
    request.body = AsyncMock(return_value=b"{}")
    request.headers = {"stripe-signature": "sig_test"}

    result = await client.handle_webhook(request=request)
    stored = await adapter.get_subscription_by_stripe_subscription_id(
        client.client.db,
        stripe_subscription_id="sub_123",
    )

    assert result == {"received": True}
    construct_event.assert_called_once_with(
        b"{}",
        "sig_test",
        "whsec_test",
    )
    assert stored is not None
    assert stored.plan == "pro"
    assert stored.reference_id == user.id
    assert stored.status == "active"
    assert stored.billing_interval == "month"
    hook.assert_awaited_once()


@pytest.mark.asyncio
async def test_handle_webhook_rejects_invalid_local_subscription_id() -> None:
    stripe_sdk = FakeStripeSDK()
    stripe_sdk.event = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "subscription": "sub_123",
                "metadata": {
                    "local_subscription_id": "not-a-uuid",
                },
            },
        },
    }
    client, _belgie_client, _stripe_sdk, _adapter = _build_client(stripe_sdk=stripe_sdk)
    request = MagicMock()
    request.body = AsyncMock(return_value=b"{}")
    request.headers = {"stripe-signature": "sig_test"}

    with pytest.raises(HTTPException, match="local_subscription_id"):
        await client.handle_webhook(request=request)


@pytest.mark.asyncio
async def test_handle_webhook_rejects_invalid_reference_id() -> None:
    stripe_sdk = FakeStripeSDK()
    stripe_sdk.event = {
        "type": "customer.subscription.created",
        "data": {
            "object": {
                "id": "sub_123",
                "customer": "cus_123",
                "status": "active",
                "metadata": {
                    "reference_id": "not-a-uuid",
                    "customer_type": "user",
                    "plan": "pro",
                },
                "items": {
                    "data": [
                        {
                            "price": {
                                "id": "price_pro",
                                "recurring": {"interval": "month"},
                            },
                        },
                    ],
                },
            },
        },
    }
    client, _belgie_client, _stripe_sdk, _adapter = _build_client(stripe_sdk=stripe_sdk)
    request = MagicMock()
    request.body = AsyncMock(return_value=b"{}")
    request.headers = {"stripe-signature": "sig_test"}

    with pytest.raises(HTTPException, match="reference_id"):
        await client.handle_webhook(request=request)


@pytest.mark.asyncio
async def test_checkout_completed_does_not_double_fire_created_hook() -> None:
    hook = AsyncMock()
    stripe_sdk = FakeStripeSDK()
    user = make_user()
    client, _belgie_client, _stripe_sdk, adapter = _build_client(
        stripe_sdk=stripe_sdk,
        user=user,
        on_subscription_created=hook,
    )
    subscription = await adapter.create_subscription(
        client.client.db,
        plan="pro",
        reference_id=user.id,
        customer_type="user",
        status="incomplete",
    )
    stripe_subscription = {
        "id": "sub_123",
        "customer": "cus_123",
        "status": "active",
        "current_period_start": 1_710_000_000,
        "current_period_end": 1_712_592_000,
        "cancel_at_period_end": False,
        "cancel_at": None,
        "canceled_at": None,
        "ended_at": None,
        "metadata": {
            "local_subscription_id": str(subscription.id),
            "reference_id": str(user.id),
            "customer_type": "user",
            "plan": "pro",
        },
        "items": {
            "data": [
                {
                    "price": {
                        "id": "price_pro",
                        "recurring": {"interval": "month"},
                    },
                },
            ],
        },
    }
    stripe_sdk.subscription_responses["sub_123"] = stripe_subscription
    request = MagicMock()
    request.body = AsyncMock(return_value=b"{}")
    request.headers = {"stripe-signature": "sig_test"}

    stripe_sdk.event = {
        "type": "checkout.session.completed",
        "data": {
            "object": {
                "subscription": "sub_123",
                "metadata": {
                    "local_subscription_id": str(subscription.id),
                },
            },
        },
    }
    checkout_result = await client.handle_webhook(request=request)

    stripe_sdk.event = {
        "type": "customer.subscription.created",
        "data": {
            "object": stripe_subscription,
        },
    }
    created_result = await client.handle_webhook(request=request)
    stored = await adapter.get_subscription_by_stripe_subscription_id(
        client.client.db,
        stripe_subscription_id="sub_123",
    )

    assert checkout_result == {"received": True}
    assert created_result == {"received": True}
    assert stored is not None
    assert stored.status == "active"
    hook.assert_awaited_once()


@pytest.mark.asyncio
async def test_subscription_success_polls_until_subscription_ready() -> None:
    client, _belgie_client, _stripe_sdk, adapter = _build_client()
    subscription_id = uuid4()
    now = datetime.now(UTC)
    adapter.get_subscription_by_id = AsyncMock(
        side_effect=[
            FakeSubscription(
                id=subscription_id,
                plan="pro",
                reference_id=client.current_user.id,
                customer_type="user",
                stripe_customer_id="cus_1",
                stripe_subscription_id=None,
                status="incomplete",
                period_start=None,
                period_end=None,
                cancel_at_period_end=False,
                cancel_at=None,
                canceled_at=None,
                ended_at=None,
                billing_interval=None,
                created_at=now,
                updated_at=now,
            ),
            FakeSubscription(
                id=subscription_id,
                plan="pro",
                reference_id=client.current_user.id,
                customer_type="user",
                stripe_customer_id="cus_1",
                stripe_subscription_id="sub_123",
                status="active",
                period_start=now,
                period_end=now,
                cancel_at_period_end=False,
                cancel_at=None,
                canceled_at=None,
                ended_at=None,
                billing_interval="month",
                created_at=now,
                updated_at=now,
            ),
        ],
    )
    token = sign_success_token(
        secret="test-secret",
        subscription_id=subscription_id,
        redirect_to="/dashboard",
    )

    response = await client.subscription_success(token=token)

    assert response.status_code == 302
    assert response.headers["location"] == "http://localhost:8000/dashboard"
