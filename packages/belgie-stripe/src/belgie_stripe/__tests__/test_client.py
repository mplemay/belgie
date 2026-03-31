from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from belgie_core.core.settings import BelgieSettings
from belgie_proto.core.customer import CustomerType
from fastapi import HTTPException

from belgie_stripe import Stripe, StripePlan, StripeSubscription
from belgie_stripe.__tests__.fakes import (
    FakeBelgieClient,
    FakeCustomer,
    FakeIndividual,
    FakeStripeSDK,
    FakeSubscription,
    InMemoryStripeAdapter,
    make_checkout_completed_event,
    make_individual,
    make_organization,
    make_session,
    make_stripe_subscription,
    make_subscription_event,
    make_team,
)
from belgie_stripe.client import StripeClient
from belgie_stripe.models import (
    BillingPortalRequest,
    ListSubscriptionsRequest,
    RestoreSubscriptionRequest,
    UpgradeSubscriptionRequest,
)
from belgie_stripe.utils import sign_success_token


def _build_client(
    *,
    stripe_sdk: FakeStripeSDK | None = None,
    adapter: InMemoryStripeAdapter | None = None,
    base_url: str = "http://localhost:8000",
    plans: list[StripePlan] | None = None,
    individual: FakeIndividual | None = None,
    customers: dict[UUID, FakeCustomer] | None = None,
    authorize_customer=None,
    get_customer_create_params=None,
    get_checkout_session_params=None,
    on_customer_create=None,
    on_subscription_created=None,
    on_subscription_updated=None,
    on_subscription_deleted=None,
    on_event=None,
) -> tuple[StripeClient[FakeSubscription], FakeBelgieClient, FakeStripeSDK, InMemoryStripeAdapter]:
    settings = BelgieSettings(secret="test-secret", base_url=base_url)
    individual = make_individual() if individual is None else individual
    session = make_session(individual_id=individual.id)
    belgie_client = FakeBelgieClient(
        individual=individual,
        customers=customers,
        session=session,
    )
    stripe_sdk = FakeStripeSDK() if stripe_sdk is None else stripe_sdk
    adapter = InMemoryStripeAdapter() if adapter is None else adapter
    plans = [StripePlan(name="pro", price_id="price_pro", annual_price_id="price_pro_year")] if plans is None else plans

    client = StripeClient(
        client=belgie_client,
        belgie_settings=settings,
        settings=Stripe(
            stripe=stripe_sdk,
            stripe_webhook_secret="whsec_test",
            get_customer_create_params=get_customer_create_params,
            on_customer_create=on_customer_create,
            on_event=on_event,
            subscription=StripeSubscription(
                adapter=adapter,
                plans=plans,
                authorize_customer=authorize_customer,
                get_checkout_session_params=get_checkout_session_params,
                on_subscription_created=on_subscription_created,
                on_subscription_updated=on_subscription_updated,
                on_subscription_deleted=on_subscription_deleted,
            ),
        ),
        current_individual=individual,
        current_session=session,
    )
    return client, belgie_client, stripe_sdk, adapter


def _webhook_request() -> MagicMock:
    request = MagicMock()
    request.body = AsyncMock(return_value=b"{}")
    request.headers = {"stripe-signature": "sig_test"}
    return request


def test_client_exposes_raw_stripe_sdk() -> None:
    client, _belgie_client, stripe_sdk, _adapter = _build_client()

    assert client.stripe is stripe_sdk


@pytest.mark.asyncio
async def test_upgrade_rejects_cross_origin_urls() -> None:
    client, _belgie_client, _stripe_sdk, _adapter = _build_client()

    with pytest.raises(HTTPException, match="relative or same-origin"):
        await client.upgrade(
            data=UpgradeSubscriptionRequest(
                plan="pro",
                success_url="https://evil.example/dashboard",
                cancel_url="/pricing",
            ),
        )


@pytest.mark.asyncio
async def test_ensure_individual_customer_lazily_creates_and_persists_customer() -> None:
    client, belgie_client, stripe_sdk, _adapter = _build_client()

    customer_id = await client.ensure_customer(
        customer_id=belgie_client.individual.id,
        metadata={"source": "test"},
    )

    assert customer_id == "cus_1"
    assert belgie_client.individual.stripe_customer_id == "cus_1"
    assert stripe_sdk.created_customers == [
        {
            "email": belgie_client.individual.email,
            "name": belgie_client.individual.name,
            "metadata": {
                "source": "test",
                "customer_id": str(belgie_client.individual.id),
                "customer_type": CustomerType.INDIVIDUAL,
            },
        },
    ]


@pytest.mark.asyncio
async def test_ensure_customer_overwrites_reserved_metadata_keys() -> None:
    hook = AsyncMock(
        return_value={
            "description": "custom customer",
            "metadata": {
                "customer_id": str(uuid4()),
                "customer_type": CustomerType.ORGANIZATION,
                "hook_only": "present",
            },
        },
    )
    client, belgie_client, stripe_sdk, _adapter = _build_client(
        get_customer_create_params=hook,
    )

    customer_id = await client.ensure_customer(
        customer_id=belgie_client.individual.id,
        metadata={"source": "test", "customer_type": "invalid"},
    )

    assert customer_id == "cus_1"
    assert stripe_sdk.created_customers == [
        {
            "email": belgie_client.individual.email,
            "name": belgie_client.individual.name,
            "description": "custom customer",
            "metadata": {
                "hook_only": "present",
                "source": "test",
                "customer_id": str(belgie_client.individual.id),
                "customer_type": CustomerType.INDIVIDUAL,
            },
        },
    ]
    hook.assert_awaited_once()


@pytest.mark.asyncio
async def test_ensure_organization_customer_uses_name_only() -> None:
    organization = make_organization()
    client, belgie_client, stripe_sdk, _adapter = _build_client(
        customers={organization.id: organization},
    )

    customer_id = await client.ensure_customer(
        customer_id=organization.id,
        metadata={"source": "test"},
    )

    assert customer_id == "cus_1"
    assert belgie_client.customers[organization.id].stripe_customer_id == "cus_1"
    assert stripe_sdk.created_customers == [
        {
            "name": organization.name,
            "metadata": {
                "source": "test",
                "customer_id": str(organization.id),
                "customer_type": CustomerType.ORGANIZATION,
            },
        },
    ]


@pytest.mark.asyncio
async def test_ensure_team_customer_uses_name_only() -> None:
    team = make_team()
    client, belgie_client, stripe_sdk, _adapter = _build_client(
        customers={team.id: team},
    )

    customer_id = await client.ensure_customer(
        customer_id=team.id,
        metadata={"source": "test"},
    )

    assert customer_id == "cus_1"
    assert belgie_client.customers[team.id].stripe_customer_id == "cus_1"
    assert stripe_sdk.created_customers == [
        {
            "name": team.name,
            "metadata": {
                "source": "test",
                "customer_id": str(team.id),
                "customer_type": CustomerType.TEAM,
            },
        },
    ]


@pytest.mark.asyncio
async def test_upgrade_same_plan_same_cadence_does_not_create_customer() -> None:
    individual = make_individual(stripe_customer_id=None)
    client, _belgie_client, stripe_sdk, adapter = _build_client(individual=individual)
    await adapter.create_subscription(
        client.client.db,
        plan="pro",
        customer_id=individual.id,
        stripe_customer_id=None,
        stripe_subscription_id="sub_existing",
        status="active",
        billing_interval="month",
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
    assert stripe_sdk.created_checkout_sessions == []


@pytest.mark.asyncio
async def test_upgrade_same_plan_allows_switch_to_annual_billing_with_portal() -> None:
    individual = make_individual(stripe_customer_id="cus_existing")
    client, _belgie_client, stripe_sdk, adapter = _build_client(individual=individual)
    stripe_sdk.subscription_responses["sub_existing"] = make_stripe_subscription(
        subscription_id="sub_existing",
        customer_id="cus_existing",
        status="active",
        price_id="price_pro",
        interval="month",
        item_id="si_existing",
    )
    await adapter.create_subscription(
        client.client.db,
        plan="pro",
        customer_id=individual.id,
        stripe_customer_id="cus_existing",
        stripe_subscription_id="sub_existing",
        status="active",
        billing_interval="month",
    )

    result = await client.upgrade(
        data=UpgradeSubscriptionRequest(
            plan="pro",
            annual=True,
            success_url="/dashboard",
            cancel_url="/pricing",
            return_url="/billing",
        ),
    )

    assert result.url == "https://billing.stripe.test/session"
    assert stripe_sdk.created_customers == []
    assert stripe_sdk.created_billing_portal_sessions[0]["customer"] == "cus_existing"
    assert stripe_sdk.created_billing_portal_sessions[0]["flow_data"]["type"] == "subscription_update_confirm"


@pytest.mark.asyncio
async def test_upgrade_creates_checkout_session_for_organization_customer() -> None:
    organization = make_organization()
    authorize_customer = AsyncMock(return_value=True)
    client, belgie_client, stripe_sdk, adapter = _build_client(
        customers={organization.id: organization},
        authorize_customer=authorize_customer,
    )

    result = await client.upgrade(
        data=UpgradeSubscriptionRequest(
            plan="pro",
            customer_id=organization.id,
            success_url="/dashboard",
            cancel_url="/pricing",
            metadata={"source": "test"},
        ),
    )

    assert result.url == "https://checkout.stripe.test/session"
    authorize_customer.assert_awaited_once()
    assert belgie_client.customers[organization.id].stripe_customer_id == "cus_1"
    stored = next(iter(adapter.subscriptions.values()))
    assert stored.customer_id == organization.id
    assert stripe_sdk.created_customers == [
        {
            "name": organization.name,
            "metadata": {
                "source": "test",
                "customer_id": str(organization.id),
                "customer_type": CustomerType.ORGANIZATION,
            },
        },
    ]
    assert stripe_sdk.created_checkout_sessions[0]["metadata"]["customer_id"] == str(organization.id)
    assert stripe_sdk.created_checkout_sessions[0]["metadata"]["customer_type"] == CustomerType.ORGANIZATION
    assert stripe_sdk.created_checkout_sessions[0]["metadata"]["plan"] == "pro"
    assert stripe_sdk.created_checkout_sessions[0]["subscription_data"]["metadata"]["customer_id"] == str(
        organization.id,
    )


@pytest.mark.asyncio
async def test_list_subscriptions_defaults_to_current_individual() -> None:
    organization = make_organization()
    client, _belgie_client, _stripe_sdk, adapter = _build_client(
        customers={organization.id: organization},
    )
    assert client.current_individual is not None
    individual_subscription = await adapter.create_subscription(
        client.client.db,
        plan="pro",
        customer_id=client.current_individual.id,
        status="active",
    )
    await adapter.create_subscription(
        client.client.db,
        plan="enterprise",
        customer_id=organization.id,
        status="active",
    )

    subscriptions = await client.list_subscriptions(data=ListSubscriptionsRequest())

    assert [subscription.id for subscription in subscriptions] == [individual_subscription.id]


@pytest.mark.asyncio
async def test_list_subscriptions_for_team_customer_uses_authorization_hook() -> None:
    team = make_team()
    authorize_customer = AsyncMock(return_value=True)
    client, _belgie_client, _stripe_sdk, adapter = _build_client(
        customers={team.id: team},
        authorize_customer=authorize_customer,
    )
    await adapter.create_subscription(
        client.client.db,
        plan="team",
        customer_id=team.id,
        status="active",
    )

    subscriptions = await client.list_subscriptions(
        data=ListSubscriptionsRequest(customer_id=team.id),
    )

    authorize_customer.assert_awaited_once()
    assert len(subscriptions) == 1
    assert subscriptions[0].customer_id == team.id


@pytest.mark.asyncio
async def test_list_subscriptions_requires_authorize_customer_for_other_customer() -> None:
    organization = make_organization()
    client, _belgie_client, _stripe_sdk, _adapter = _build_client(
        customers={organization.id: organization},
    )

    with pytest.raises(HTTPException, match="authorize_customer"):
        await client.list_subscriptions(
            data=ListSubscriptionsRequest(customer_id=organization.id),
        )


@pytest.mark.asyncio
async def test_restore_subscription_updates_cancel_at_period_end() -> None:
    individual = make_individual(stripe_customer_id="cus_existing")
    client, _belgie_client, stripe_sdk, adapter = _build_client(individual=individual)
    subscription = await adapter.create_subscription(
        client.client.db,
        plan="pro",
        customer_id=individual.id,
        stripe_customer_id="cus_existing",
        stripe_subscription_id="sub_existing",
        status="active",
        cancel_at_period_end=True,
        billing_interval="month",
    )
    stripe_sdk.subscription_responses["sub_existing"] = make_stripe_subscription(
        subscription_id="sub_existing",
        customer_id="cus_existing",
        status="active",
        cancel_at_period_end=True,
        metadata={"customer_id": str(individual.id), "plan": "pro"},
    )

    restored = await client.restore(
        data=RestoreSubscriptionRequest(customer_id=individual.id),
    )

    assert restored.id == subscription.id
    assert restored.cancel_at_period_end is False
    assert stripe_sdk.modified_subscriptions == [
        ("sub_existing", {"cancel_at_period_end": False}),
    ]


@pytest.mark.asyncio
async def test_create_billing_portal_defaults_to_root_return_url() -> None:
    individual = make_individual(stripe_customer_id="cus_existing")
    client, _belgie_client, stripe_sdk, _adapter = _build_client(individual=individual)

    result = await client.create_billing_portal(
        data=BillingPortalRequest(customer_id=individual.id),
    )

    assert result.url == "https://billing.stripe.test/session"
    assert stripe_sdk.created_billing_portal_sessions == [
        {
            "customer": "cus_existing",
            "return_url": "http://localhost:8000/",
        },
    ]


@pytest.mark.asyncio
async def test_handle_webhook_checkout_completed_creates_subscription() -> None:
    individual = make_individual()
    client, _belgie_client, stripe_sdk, adapter = _build_client(individual=individual)
    stripe_sdk.event = make_checkout_completed_event(
        subscription_id="sub_123",
        metadata={"customer_id": str(individual.id), "plan": "pro"},
    )
    stripe_sdk.subscription_responses["sub_123"] = make_stripe_subscription(
        subscription_id="sub_123",
        customer_id="cus_123",
        metadata={"customer_id": str(individual.id), "plan": "pro"},
    )

    response = await client.handle_webhook(request=_webhook_request())

    assert response == {"received": True}
    stored = next(iter(adapter.subscriptions.values()))
    assert stored.customer_id == individual.id
    assert stored.stripe_subscription_id == "sub_123"
    assert stored.status == "active"


@pytest.mark.asyncio
async def test_handle_webhook_rejects_invalid_customer_id() -> None:
    client, _belgie_client, stripe_sdk, _adapter = _build_client()
    stripe_sdk.event = make_subscription_event(
        event_type="customer.subscription.created",
        subscription=make_stripe_subscription(
            metadata={"customer_id": "not-a-uuid", "plan": "pro"},
        ),
    )

    with pytest.raises(HTTPException, match="customer_id"):
        await client.handle_webhook(request=_webhook_request())


@pytest.mark.asyncio
async def test_handle_webhook_updates_existing_subscription_without_customer_metadata() -> None:
    individual = make_individual(stripe_customer_id="cus_existing")
    client, _belgie_client, stripe_sdk, adapter = _build_client(individual=individual)
    subscription = await adapter.create_subscription(
        client.client.db,
        plan="pro",
        customer_id=individual.id,
        stripe_customer_id="cus_existing",
        stripe_subscription_id="sub_existing",
        status="active",
        cancel_at_period_end=False,
        billing_interval="month",
    )
    stripe_sdk.event = make_subscription_event(
        event_type="customer.subscription.updated",
        subscription=make_stripe_subscription(
            subscription_id="sub_existing",
            customer_id="cus_existing",
            status="canceled",
            metadata={},
            cancel_at_period_end=True,
        ),
    )

    response = await client.handle_webhook(request=_webhook_request())

    assert response == {"received": True}
    updated = adapter.subscriptions[subscription.id]
    assert updated.customer_id == individual.id
    assert updated.status == "canceled"
    assert updated.cancel_at_period_end is True


@pytest.mark.asyncio
async def test_subscription_success_redirects_after_subscription_is_active() -> None:
    client, _belgie_client, _stripe_sdk, adapter = _build_client()
    assert client.current_individual is not None
    subscription = await adapter.create_subscription(
        client.client.db,
        plan="pro",
        customer_id=client.current_individual.id,
        stripe_subscription_id="sub_123",
        status="active",
    )
    token = sign_success_token(
        secret=client.belgie_settings.secret,
        subscription_id=subscription.id,
        redirect_to="/dashboard",
    )

    response = await client.subscription_success(token=token)

    assert response.status_code == 302
    assert response.headers["location"] == "http://localhost:8000/dashboard"
