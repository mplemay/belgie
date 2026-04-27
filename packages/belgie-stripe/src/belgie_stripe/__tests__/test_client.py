from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
import stripe
from belgie_core.core.settings import BelgieSettings
from belgie_proto.core.account import AccountType
from fastapi import HTTPException
from stripe.checkout import Session as CheckoutSession
from stripe.params import checkout

from belgie_stripe import Stripe, StripeFreeTrial, StripePlan, StripeSubscription
from belgie_stripe.__tests__.fakes import (
    FakeAccount,
    FakeBelgieClient,
    FakeIndividual,
    FakeStripeSDK,
    FakeSubscription,
    InMemoryStripeAdapter,
    make_checkout_completed_event,
    make_customer,
    make_individual,
    make_organization,
    make_price,
    make_session,
    make_stripe_subscription,
    make_subscription_event,
    make_team,
)
from belgie_stripe.client import DesiredSubscriptionItem, StripeClient
from belgie_stripe.metadata import parse_customer_metadata, parse_schedule_metadata, parse_subscription_metadata
from belgie_stripe.models import (
    BillingPortalRequest,
    CancelSubscriptionRequest,
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
    accounts: dict[UUID, FakeAccount] | None = None,
    authorize_account=None,
    get_account_create_params=None,
    get_checkout_session_params=None,
    on_account_create=None,
    on_subscription_complete=None,
    on_subscription_created=None,
    on_subscription_updated=None,
    on_subscription_cancel_requested=None,
    on_subscription_canceled=None,
    on_subscription_deleted=None,
    on_event=None,
    organization_adapter=None,
) -> tuple[StripeClient[FakeSubscription], FakeBelgieClient, FakeStripeSDK, InMemoryStripeAdapter]:
    settings = BelgieSettings(secret="test-secret", base_url=base_url)
    individual = make_individual() if individual is None else individual
    session = make_session(individual_id=individual.id)
    belgie_client = FakeBelgieClient(
        individual=individual,
        accounts=accounts,
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
            get_account_create_params=get_account_create_params,
            on_account_create=on_account_create,
            on_event=on_event,
            subscription=StripeSubscription(
                adapter=adapter,
                plans=plans,
                authorize_account=authorize_account,
                get_checkout_session_params=get_checkout_session_params,
                on_subscription_complete=on_subscription_complete,
                on_subscription_created=on_subscription_created,
                on_subscription_updated=on_subscription_updated,
                on_subscription_cancel_requested=on_subscription_cancel_requested,
                on_subscription_canceled=on_subscription_canceled,
                on_subscription_deleted=on_subscription_deleted,
            ),
        ),
        current_individual=individual,
        current_session=session,
        organization_adapter=organization_adapter,
    )
    return client, belgie_client, stripe_sdk, adapter


def _webhook_request() -> MagicMock:
    request = MagicMock()
    request.body = AsyncMock(return_value=b"{}")
    request.headers = {"stripe-signature": "sig_test"}
    return request


def _subscription_item(
    *,
    item_id: str,
    price_id: str,
    quantity: int | None = 1,
    interval: str = "month",
    usage_type: str | None = None,
) -> dict[str, object]:
    return {
        "id": item_id,
        "object": "subscription_item",
        "price": make_price(
            price_id=price_id,
            interval=interval,
            usage_type=usage_type,
        )._to_dict_recursive(),
        "quantity": quantity,
    }


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

    account_id = await client.ensure_account(
        account_id=belgie_client.individual.id,
        metadata={"source": "test"},
    )

    assert account_id == "cus_1"
    assert belgie_client.individual.stripe_customer_id == "cus_1"
    assert stripe_sdk.created_customers == [
        {
            "email": belgie_client.individual.email,
            "name": belgie_client.individual.name,
            "metadata": {
                "source": "test",
                "account_id": str(belgie_client.individual.id),
                "account_type": AccountType.INDIVIDUAL,
            },
        },
    ]


@pytest.mark.asyncio
async def test_ensure_customer_overwrites_reserved_metadata_keys() -> None:
    hook = AsyncMock(
        return_value={
            "description": "custom customer",
            "metadata": {
                "account_id": str(uuid4()),
                "account_type": AccountType.ORGANIZATION,
                "hook_only": "present",
            },
        },
    )
    client, belgie_client, stripe_sdk, _adapter = _build_client(
        get_account_create_params=hook,
    )

    account_id = await client.ensure_account(
        account_id=belgie_client.individual.id,
        metadata={"source": "test", "account_type": "invalid"},
    )

    assert account_id == "cus_1"
    assert stripe_sdk.created_customers == [
        {
            "email": belgie_client.individual.email,
            "name": belgie_client.individual.name,
            "description": "custom customer",
            "metadata": {
                "hook_only": "present",
                "source": "test",
                "account_id": str(belgie_client.individual.id),
                "account_type": AccountType.INDIVIDUAL,
            },
        },
    ]
    hook.assert_awaited_once()


@pytest.mark.asyncio
async def test_ensure_organization_customer_uses_name_only() -> None:
    organization = make_organization()
    client, belgie_client, stripe_sdk, _adapter = _build_client(
        accounts={organization.id: organization},
    )

    account_id = await client.ensure_account(
        account_id=organization.id,
        metadata={"source": "test"},
    )

    assert account_id == "cus_1"
    assert belgie_client.accounts[organization.id].stripe_customer_id == "cus_1"
    assert stripe_sdk.created_customers == [
        {
            "name": organization.name,
            "metadata": {
                "source": "test",
                "account_id": str(organization.id),
                "account_type": AccountType.ORGANIZATION,
            },
        },
    ]


@pytest.mark.asyncio
async def test_ensure_team_customer_uses_name_only() -> None:
    team = make_team()
    client, belgie_client, stripe_sdk, _adapter = _build_client(
        accounts={team.id: team},
    )

    account_id = await client.ensure_account(
        account_id=team.id,
        metadata={"source": "test"},
    )

    assert account_id == "cus_1"
    assert belgie_client.accounts[team.id].stripe_customer_id == "cus_1"
    assert stripe_sdk.created_customers == [
        {
            "name": team.name,
            "metadata": {
                "source": "test",
                "account_id": str(team.id),
                "account_type": AccountType.TEAM,
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
        account_id=individual.id,
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
        account_id="cus_existing",
        status="active",
        price_id="price_pro",
        interval="month",
        item_id="si_existing",
    )
    await adapter.create_subscription(
        client.client.db,
        plan="pro",
        account_id=individual.id,
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
    authorize_account = AsyncMock(return_value=True)
    client, belgie_client, stripe_sdk, adapter = _build_client(
        accounts={organization.id: organization},
        authorize_account=authorize_account,
    )

    result = await client.upgrade(
        data=UpgradeSubscriptionRequest(
            plan="pro",
            account_id=organization.id,
            success_url="/dashboard",
            cancel_url="/pricing",
            metadata={"source": "test"},
        ),
    )

    assert result.url == "https://checkout.stripe.test/session"
    authorize_account.assert_awaited_once()
    assert belgie_client.accounts[organization.id].stripe_customer_id == "cus_1"
    stored = next(iter(adapter.subscriptions.values()))
    assert stored.account_id == organization.id
    assert stripe_sdk.created_customers == [
        {
            "name": organization.name,
            "metadata": {
                "source": "test",
                "account_id": str(organization.id),
                "account_type": AccountType.ORGANIZATION,
            },
        },
    ]
    assert stripe_sdk.created_checkout_sessions[0]["metadata"]["account_id"] == str(organization.id)
    assert stripe_sdk.created_checkout_sessions[0]["metadata"]["account_type"] == AccountType.ORGANIZATION
    assert stripe_sdk.created_checkout_sessions[0]["metadata"]["plan"] == "pro"
    assert stripe_sdk.created_checkout_sessions[0]["subscription_data"]["metadata"]["account_id"] == str(
        organization.id,
    )


@pytest.mark.asyncio
async def test_list_subscriptions_defaults_to_current_individual() -> None:
    organization = make_organization()
    client, _belgie_client, _stripe_sdk, adapter = _build_client(
        accounts={organization.id: organization},
    )
    assert client.current_individual is not None
    individual_subscription = await adapter.create_subscription(
        client.client.db,
        plan="pro",
        account_id=client.current_individual.id,
        status="active",
    )
    await adapter.create_subscription(
        client.client.db,
        plan="enterprise",
        account_id=organization.id,
        status="active",
    )

    subscriptions = await client.list_subscriptions(data=ListSubscriptionsRequest())

    assert [subscription.id for subscription in subscriptions] == [individual_subscription.id]


@pytest.mark.asyncio
async def test_list_subscriptions_for_team_customer_uses_authorization_hook() -> None:
    team = make_team()
    authorize_account = AsyncMock(return_value=True)
    client, _belgie_client, _stripe_sdk, adapter = _build_client(
        accounts={team.id: team},
        authorize_account=authorize_account,
    )
    await adapter.create_subscription(
        client.client.db,
        plan="team",
        account_id=team.id,
        status="active",
    )

    subscriptions = await client.list_subscriptions(
        data=ListSubscriptionsRequest(account_id=team.id),
    )

    authorize_account.assert_awaited_once()
    assert len(subscriptions) == 1
    assert subscriptions[0].account_id == team.id


@pytest.mark.asyncio
async def test_list_subscriptions_requires_authorize_account_for_other_account() -> None:
    organization = make_organization()
    client, _belgie_client, _stripe_sdk, _adapter = _build_client(
        accounts={organization.id: organization},
    )

    with pytest.raises(HTTPException, match="authorize_account"):
        await client.list_subscriptions(
            data=ListSubscriptionsRequest(account_id=organization.id),
        )


@pytest.mark.asyncio
async def test_restore_subscription_updates_cancel_at_period_end() -> None:
    individual = make_individual(stripe_customer_id="cus_existing")
    client, _belgie_client, stripe_sdk, adapter = _build_client(individual=individual)
    subscription = await adapter.create_subscription(
        client.client.db,
        plan="pro",
        account_id=individual.id,
        stripe_customer_id="cus_existing",
        stripe_subscription_id="sub_existing",
        status="active",
        cancel_at_period_end=True,
        billing_interval="month",
    )
    stripe_sdk.subscription_responses["sub_existing"] = make_stripe_subscription(
        subscription_id="sub_existing",
        account_id="cus_existing",
        status="active",
        cancel_at_period_end=True,
        metadata={"account_id": str(individual.id), "plan": "pro"},
    )

    restored = await client.restore(
        data=RestoreSubscriptionRequest(account_id=individual.id),
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
        data=BillingPortalRequest(account_id=individual.id),
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
        metadata={"account_id": str(individual.id), "plan": "pro"},
    )
    stripe_sdk.subscription_responses["sub_123"] = make_stripe_subscription(
        subscription_id="sub_123",
        account_id="cus_123",
        metadata={"account_id": str(individual.id), "plan": "pro"},
    )

    response = await client.handle_webhook(request=_webhook_request())

    assert response == {"received": True}
    stored = next(iter(adapter.subscriptions.values()))
    assert stored.account_id == individual.id
    assert stored.stripe_subscription_id == "sub_123"
    assert stored.status == "active"


@pytest.mark.asyncio
async def test_handle_webhook_checkout_completed_calls_on_subscription_complete_after_sync() -> None:
    individual = make_individual()
    captured_contexts = []
    captured_statuses = []
    adapter_ref: InMemoryStripeAdapter | None = None

    async def on_subscription_complete(context) -> None:
        assert adapter_ref is not None
        captured_contexts.append(context)
        captured_statuses.append(adapter_ref.subscriptions[context.subscription.id].status)

    client, belgie_client, stripe_sdk, adapter = _build_client(
        individual=individual,
        on_subscription_complete=on_subscription_complete,
    )
    adapter_ref = adapter
    stripe_sdk.event = make_checkout_completed_event(
        subscription_id="sub_123",
        metadata={"account_id": str(individual.id), "plan": "pro"},
    )
    stripe_sdk.subscription_responses["sub_123"] = make_stripe_subscription(
        subscription_id="sub_123",
        account_id="cus_123",
        metadata={"account_id": str(individual.id), "plan": "pro"},
    )

    response = await client.handle_webhook(request=_webhook_request())

    assert response == {"received": True}
    assert captured_statuses == ["active"]
    assert len(captured_contexts) == 1
    context = captured_contexts[0]
    assert isinstance(context.checkout_session, CheckoutSession)
    assert isinstance(context.raw_event, stripe.Subscription)
    assert context.checkout_session.id == "cs_123"
    assert context.plan is not None
    assert context.plan.name == "pro"
    assert context.subscription.status == "active"
    assert context.subscription.stripe_subscription_id == "sub_123"
    assert context.account is belgie_client.individual


@pytest.mark.asyncio
async def test_handle_webhook_checkout_completed_skips_subscription_complete_without_account_mapping() -> None:
    on_subscription_complete = AsyncMock()
    client, _belgie_client, stripe_sdk, adapter = _build_client(
        on_subscription_complete=on_subscription_complete,
    )
    stripe_sdk.event = make_checkout_completed_event(
        subscription_id="sub_123",
        metadata={"plan": "pro"},
    )
    stripe_sdk.subscription_responses["sub_123"] = make_stripe_subscription(
        subscription_id="sub_123",
        account_id="cus_123",
        metadata={"plan": "pro"},
    )

    response = await client.handle_webhook(request=_webhook_request())

    assert response == {"received": True}
    assert adapter.subscriptions == {}
    on_subscription_complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_webhook_checkout_completed_skips_subscription_complete_without_matching_plan() -> None:
    individual = make_individual()
    on_subscription_complete = AsyncMock()
    client, _belgie_client, stripe_sdk, adapter = _build_client(
        individual=individual,
        on_subscription_complete=on_subscription_complete,
    )
    stripe_sdk.event = make_checkout_completed_event(
        subscription_id="sub_123",
        metadata={"account_id": str(individual.id), "plan": "missing"},
    )
    stripe_sdk.subscription_responses["sub_123"] = make_stripe_subscription(
        subscription_id="sub_123",
        account_id="cus_123",
        metadata={"account_id": str(individual.id), "plan": "missing"},
        price_id="price_missing",
    )

    response = await client.handle_webhook(request=_webhook_request())

    assert response == {"received": True}
    assert adapter.subscriptions == {}
    on_subscription_complete.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_webhook_rejects_invalid_account_id() -> None:
    on_subscription_created = AsyncMock()
    client, _belgie_client, stripe_sdk, _adapter = _build_client(
        on_subscription_created=on_subscription_created,
    )
    stripe_sdk.event = make_subscription_event(
        event_type="customer.subscription.created",
        subscription=make_stripe_subscription(
            metadata={"account_id": "not-a-uuid", "plan": "pro"},
        ),
    )

    with pytest.raises(HTTPException, match="account_id"):
        await client.handle_webhook(request=_webhook_request())
    on_subscription_created.assert_not_awaited()


@pytest.mark.asyncio
async def test_handle_webhook_updates_existing_subscription_without_customer_metadata() -> None:
    individual = make_individual(stripe_customer_id="cus_existing")
    client, _belgie_client, stripe_sdk, adapter = _build_client(individual=individual)
    subscription = await adapter.create_subscription(
        client.client.db,
        plan="pro",
        account_id=individual.id,
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
            account_id="cus_existing",
            status="canceled",
            metadata={},
            cancel_at_period_end=True,
        ),
    )

    response = await client.handle_webhook(request=_webhook_request())

    assert response == {"received": True}
    updated = adapter.subscriptions[subscription.id]
    assert updated.account_id == individual.id
    assert updated.status == "canceled"
    assert updated.cancel_at_period_end is True


@pytest.mark.asyncio
async def test_handle_webhook_updated_calls_on_subscription_cancel_requested_once() -> None:
    individual = make_individual(stripe_customer_id="cus_existing")
    on_subscription_cancel_requested = AsyncMock()
    on_subscription_updated = AsyncMock()
    client, _belgie_client, stripe_sdk, adapter = _build_client(
        individual=individual,
        on_subscription_cancel_requested=on_subscription_cancel_requested,
        on_subscription_updated=on_subscription_updated,
    )
    subscription = await adapter.create_subscription(
        client.client.db,
        plan="pro",
        account_id=individual.id,
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
            account_id="cus_existing",
            status="active",
            metadata={},
            cancel_at_period_end=True,
            cancellation_details={
                "feedback": "too_expensive",
                "comment": "Customer canceled subscription",
                "reason": "cancellation_requested",
            },
        ),
    )

    first_response = await client.handle_webhook(request=_webhook_request())
    second_response = await client.handle_webhook(request=_webhook_request())

    assert first_response == {"received": True}
    assert second_response == {"received": True}
    assert adapter.subscriptions[subscription.id].cancel_at_period_end is True
    on_subscription_updated.assert_awaited()
    assert on_subscription_updated.await_count == 2
    on_subscription_cancel_requested.assert_awaited_once()
    context = on_subscription_cancel_requested.await_args.args[0]
    assert context.plan is not None
    assert context.plan.name == "pro"
    assert context.subscription.cancel_at_period_end is True
    assert isinstance(context.cancellation_details, stripe.Subscription.CancellationDetails)
    assert context.cancellation_details.feedback == "too_expensive"


@pytest.mark.asyncio
async def test_subscription_success_redirects_after_subscription_is_active() -> None:
    client, _belgie_client, _stripe_sdk, adapter = _build_client()
    assert client.current_individual is not None
    subscription = await adapter.create_subscription(
        client.client.db,
        plan="pro",
        account_id=client.current_individual.id,
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


@pytest.mark.asyncio
async def test_ensure_account_reuses_existing_individual_customer_from_search() -> None:
    individual = make_individual(stripe_customer_id=None)
    client, belgie_client, stripe_sdk, _adapter = _build_client(individual=individual)
    stripe_sdk.customer_responses["cus_existing"] = make_customer(
        customer_id="cus_existing",
        email=individual.email,
        metadata={
            "account_id": str(individual.id),
            "account_type": AccountType.INDIVIDUAL,
        },
    )

    account_id = await client.ensure_account(account_id=individual.id, metadata={})

    assert account_id == "cus_existing"
    assert belgie_client.individual.stripe_customer_id == "cus_existing"
    assert stripe_sdk.created_customers == []
    assert stripe_sdk.searched_customers[0]["query"] == f'email:"{individual.email}"'


@pytest.mark.asyncio
async def test_ensure_account_falls_back_to_customer_list_when_search_fails() -> None:
    individual = make_individual(stripe_customer_id=None)
    client, belgie_client, stripe_sdk, _adapter = _build_client(individual=individual)
    stripe_sdk.customer_search_errors.append(stripe.error.StripeError("search unavailable"))
    stripe_sdk.customer_responses["cus_existing"] = make_customer(
        customer_id="cus_existing",
        email=individual.email,
    )

    account_id = await client.ensure_account(account_id=individual.id, metadata={})

    assert account_id == "cus_existing"
    assert belgie_client.individual.stripe_customer_id == "cus_existing"
    assert stripe_sdk.created_customers == []
    assert stripe_sdk.listed_customers[0]["email"] == individual.email


@pytest.mark.asyncio
async def test_ensure_individual_customer_ignores_group_customer_with_same_email() -> None:
    individual = make_individual(stripe_customer_id=None)
    client, belgie_client, stripe_sdk, _adapter = _build_client(individual=individual)
    stripe_sdk.customer_responses["cus_org"] = make_customer(
        customer_id="cus_org",
        email=individual.email,
        metadata={
            "account_id": str(uuid4()),
            "account_type": AccountType.ORGANIZATION,
        },
    )

    account_id = await client.ensure_account(account_id=individual.id, metadata={})

    assert account_id == "cus_1"
    assert belgie_client.individual.stripe_customer_id == "cus_1"
    assert stripe_sdk.created_customers[0]["metadata"] == {
        "account_id": str(individual.id),
        "account_type": AccountType.INDIVIDUAL,
    }


@pytest.mark.asyncio
async def test_ensure_account_reuses_existing_organization_customer_from_metadata_search() -> None:
    organization = make_organization(stripe_customer_id=None)
    client, belgie_client, stripe_sdk, _adapter = _build_client(
        accounts={organization.id: organization},
    )
    stripe_sdk.customer_responses["cus_org_existing"] = make_customer(
        customer_id="cus_org_existing",
        name=organization.name,
        metadata={
            "account_id": str(organization.id),
            "account_type": AccountType.ORGANIZATION,
        },
    )

    account_id = await client.ensure_account(account_id=organization.id, metadata={})

    assert account_id == "cus_org_existing"
    assert belgie_client.accounts[organization.id].stripe_customer_id == "cus_org_existing"
    assert stripe_sdk.created_customers == []


@pytest.mark.asyncio
async def test_list_subscriptions_active_only_returns_limits_and_price_id() -> None:
    plans = [
        StripePlan(
            name="pro",
            price_id="price_pro",
            annual_price_id="price_pro_year",
            limits={"seats": {"soft": 5}},
        ),
    ]
    client, _belgie_client, _stripe_sdk, adapter = _build_client(plans=plans)
    assert client.current_individual is not None
    await adapter.create_subscription(
        client.client.db,
        plan="pro",
        account_id=client.current_individual.id,
        status="canceled",
        billing_interval="month",
    )
    active_subscription = await adapter.create_subscription(
        client.client.db,
        plan="pro",
        account_id=client.current_individual.id,
        status="active",
        billing_interval="year",
    )

    subscriptions = await client.list_subscriptions(
        data=ListSubscriptionsRequest(active_only=True),
    )

    assert len(subscriptions) == 1
    assert subscriptions[0].id == active_subscription.id
    assert subscriptions[0].price_id == "price_pro_year"
    assert subscriptions[0].limits == {"seats": {"soft": 5}}


@pytest.mark.asyncio
async def test_upgrade_schedule_at_period_end_creates_subscription_schedule() -> None:
    individual = make_individual(stripe_customer_id="cus_existing")
    plans = [
        StripePlan(name="pro", price_id="price_pro"),
        StripePlan(name="starter", price_id="price_starter"),
    ]
    client, _belgie_client, stripe_sdk, adapter = _build_client(individual=individual, plans=plans)
    subscription = await adapter.create_subscription(
        client.client.db,
        plan="pro",
        account_id=individual.id,
        stripe_customer_id="cus_existing",
        stripe_subscription_id="sub_existing",
        status="active",
        billing_interval="month",
    )
    stripe_sdk.subscription_responses["sub_existing"] = make_stripe_subscription(
        subscription_id="sub_existing",
        account_id="cus_existing",
        metadata={"account_id": str(individual.id), "plan": "pro"},
        price_id="price_pro",
        item_id="si_existing",
    )

    result = await client.upgrade(
        data=UpgradeSubscriptionRequest(
            plan="starter",
            success_url="/dashboard",
            cancel_url="/pricing",
            return_url="/billing",
            schedule_at_period_end=True,
        ),
    )

    assert result.url == "http://localhost:8000/billing"
    assert stripe_sdk.created_subscription_schedules[0]["from_subscription"] == "sub_existing"
    schedule_update = stripe_sdk.updated_subscription_schedules[0][1]
    assert schedule_update["phases"][1]["items"][0]["price"] == "price_starter"
    assert adapter.subscriptions[subscription.id].stripe_schedule_id == "sub_sched_1"


@pytest.mark.asyncio
async def test_upgrade_metered_checkout_omits_quantity() -> None:
    plans = [StripePlan(name="metered", price_id="price_metered")]
    client, _belgie_client, stripe_sdk, _adapter = _build_client(plans=plans)
    stripe_sdk.price_responses["price_metered"] = make_price(
        price_id="price_metered",
        usage_type="metered",
    )

    await client.upgrade(
        data=UpgradeSubscriptionRequest(
            plan="metered",
            success_url="/dashboard",
            cancel_url="/pricing",
        ),
    )

    line_item = stripe_sdk.created_checkout_sessions[0]["line_items"][0]
    assert line_item["price"] == "price_metered"
    assert "quantity" not in line_item


@pytest.mark.asyncio
async def test_upgrade_applies_free_trial_only_once() -> None:
    plans = [
        StripePlan(
            name="starter",
            price_id="price_starter",
            free_trial=StripeFreeTrial(days=7),
        ),
    ]
    client, _belgie_client, stripe_sdk, adapter = _build_client(plans=plans)
    assert client.current_individual is not None

    await client.upgrade(
        data=UpgradeSubscriptionRequest(
            plan="starter",
            success_url="/dashboard",
            cancel_url="/pricing",
        ),
    )

    trial_days = stripe_sdk.created_checkout_sessions[0]["subscription_data"]["trial_period_days"]
    assert trial_days == 7

    stripe_sdk.created_checkout_sessions.clear()
    await adapter.create_subscription(
        client.client.db,
        plan="starter",
        account_id=client.current_individual.id,
        status="canceled",
        trial_start=datetime.now(tz=UTC),
        trial_end=datetime.now(tz=UTC),
    )

    await client.upgrade(
        data=UpgradeSubscriptionRequest(
            plan="starter",
            success_url="/dashboard",
            cancel_url="/pricing",
        ),
    )

    assert "trial_period_days" not in stripe_sdk.created_checkout_sessions[0]["subscription_data"]


@pytest.mark.asyncio
async def test_cancel_targets_active_subscription_when_newer_canceled_subscription_exists() -> None:
    individual = make_individual(stripe_customer_id="cus_existing")
    client, _belgie_client, stripe_sdk, adapter = _build_client(individual=individual)
    await adapter.create_subscription(
        client.client.db,
        plan="pro",
        account_id=individual.id,
        stripe_customer_id="cus_existing",
        stripe_subscription_id="sub_active",
        status="active",
    )
    await adapter.create_subscription(
        client.client.db,
        plan="pro",
        account_id=individual.id,
        stripe_customer_id="cus_existing",
        stripe_subscription_id="sub_canceled",
        status="canceled",
    )

    result = await client.cancel(
        data=CancelSubscriptionRequest(return_url="/billing"),
    )

    assert result.url == "https://billing.stripe.test/session"
    portal_payload = stripe_sdk.created_billing_portal_sessions[0]
    assert portal_payload["flow_data"]["subscription_cancel"]["subscription"] == "sub_active"


@pytest.mark.asyncio
async def test_cancel_uses_targeted_subscription_cancel_flow() -> None:
    individual = make_individual(stripe_customer_id="cus_existing")
    client, _belgie_client, stripe_sdk, adapter = _build_client(individual=individual)
    subscription = await adapter.create_subscription(
        client.client.db,
        plan="pro",
        account_id=individual.id,
        stripe_customer_id="cus_existing",
        stripe_subscription_id="sub_existing",
        status="active",
    )

    result = await client.cancel(
        data=CancelSubscriptionRequest(
            account_id=individual.id,
            subscription_id=subscription.id,
            return_url="/billing",
        ),
    )

    assert result.url == "https://billing.stripe.test/session"
    portal_payload = stripe_sdk.created_billing_portal_sessions[0]
    assert portal_payload["flow_data"]["type"] == "subscription_cancel"
    assert portal_payload["flow_data"]["subscription_cancel"]["subscription"] == "sub_existing"


@pytest.mark.asyncio
async def test_cancel_rejects_cross_account_targeted_subscription() -> None:
    organization = make_organization()
    individual = make_individual(stripe_customer_id="cus_existing")
    client, _belgie_client, _stripe_sdk, adapter = _build_client(
        individual=individual,
        accounts={organization.id: organization},
    )
    subscription = await adapter.create_subscription(
        client.client.db,
        plan="pro",
        account_id=individual.id,
        stripe_customer_id="cus_existing",
        stripe_subscription_id="sub_existing",
        status="active",
    )

    with pytest.raises(HTTPException, match="subscription not found"):
        await client.cancel(
            data=CancelSubscriptionRequest(
                account_id=organization.id,
                subscription_id=subscription.id,
                return_url="/billing",
            ),
        )


@pytest.mark.asyncio
async def test_restore_clears_cancel_at_timestamp() -> None:
    individual = make_individual(stripe_customer_id="cus_existing")
    client, _belgie_client, stripe_sdk, adapter = _build_client(individual=individual)
    cancel_at = 1_720_000_000
    subscription = await adapter.create_subscription(
        client.client.db,
        plan="pro",
        account_id=individual.id,
        stripe_customer_id="cus_existing",
        stripe_subscription_id="sub_existing",
        status="active",
        cancel_at=datetime.fromtimestamp(cancel_at, UTC),
        canceled_at=datetime.now(tz=UTC),
    )
    stripe_sdk.subscription_responses["sub_existing"] = make_stripe_subscription(
        subscription_id="sub_existing",
        account_id="cus_existing",
        status="active",
        cancel_at=cancel_at,
        metadata={"account_id": str(individual.id), "plan": "pro"},
    )

    restored = await client.restore(
        data=RestoreSubscriptionRequest(subscription_id=subscription.id),
    )

    assert restored.id == subscription.id
    assert restored.cancel_at is None
    assert stripe_sdk.modified_subscriptions[-1] == ("sub_existing", {"cancel_at": ""})


@pytest.mark.asyncio
async def test_restore_rejects_cross_account_targeted_subscription() -> None:
    organization = make_organization()
    individual = make_individual(stripe_customer_id="cus_existing")
    client, _belgie_client, _stripe_sdk, adapter = _build_client(
        individual=individual,
        accounts={organization.id: organization},
    )
    subscription = await adapter.create_subscription(
        client.client.db,
        plan="pro",
        account_id=individual.id,
        stripe_customer_id="cus_existing",
        stripe_subscription_id="sub_existing",
        status="active",
        cancel_at_period_end=True,
    )

    with pytest.raises(HTTPException, match="subscription not found"):
        await client.restore(
            data=RestoreSubscriptionRequest(
                account_id=organization.id,
                subscription_id=subscription.id,
            ),
        )


@pytest.mark.asyncio
async def test_restore_releases_pending_schedule() -> None:
    individual = make_individual(stripe_customer_id="cus_existing")
    client, _belgie_client, stripe_sdk, adapter = _build_client(individual=individual)
    subscription = await adapter.create_subscription(
        client.client.db,
        plan="pro",
        account_id=individual.id,
        stripe_customer_id="cus_existing",
        stripe_subscription_id="sub_existing",
        stripe_schedule_id="sub_sched_existing",
        status="active",
    )

    restored = await client.restore(
        data=RestoreSubscriptionRequest(subscription_id=subscription.id),
    )

    assert restored.id == subscription.id
    assert restored.stripe_schedule_id is None
    assert stripe_sdk.released_subscription_schedules[0][0] == "sub_sched_existing"


@pytest.mark.asyncio
async def test_subscription_success_syncs_via_checkout_session_id() -> None:
    client, _belgie_client, stripe_sdk, adapter = _build_client()
    assert client.current_individual is not None
    subscription = await adapter.create_subscription(
        client.client.db,
        plan="pro",
        account_id=client.current_individual.id,
        stripe_customer_id="cus_success",
        status="incomplete",
    )
    token = sign_success_token(
        secret=client.belgie_settings.secret,
        subscription_id=subscription.id,
        redirect_to="/dashboard",
    )
    stripe_sdk.checkout_session_responses["cs_success"] = CheckoutSession.construct_from(
        {
            "id": "cs_success",
            "object": "checkout.session",
            "subscription": "sub_success",
            "metadata": {
                "local_subscription_id": str(subscription.id),
                "account_id": str(client.current_individual.id),
                "plan": "pro",
            },
        },
        key=None,
    )
    stripe_sdk.subscription_responses["sub_success"] = make_stripe_subscription(
        subscription_id="sub_success",
        account_id="cus_success",
        status="active",
        metadata={
            "local_subscription_id": str(subscription.id),
            "account_id": str(client.current_individual.id),
            "plan": "pro",
        },
    )

    response = await client.subscription_success(
        token=token,
        checkout_session_id="cs_success",
    )

    assert response.status_code == 302
    assert adapter.subscriptions[subscription.id].status == "active"
    assert adapter.subscriptions[subscription.id].stripe_subscription_id == "sub_success"


@pytest.mark.asyncio
async def test_handle_webhook_syncs_trial_seats_and_schedule() -> None:
    organization = make_organization(stripe_customer_id="cus_team")
    plans = [
        StripePlan(
            name="team",
            price_id="price_team",
            seat_price_id="price_team_seat",
        ),
    ]
    client, _belgie_client, stripe_sdk, adapter = _build_client(
        accounts={organization.id: organization},
        plans=plans,
    )
    subscription = await adapter.create_subscription(
        client.client.db,
        plan="team",
        account_id=organization.id,
        stripe_customer_id="cus_team",
        stripe_subscription_id="sub_team",
        stripe_schedule_id="sub_sched_team",
        status="active",
    )
    stripe_sdk.event = make_subscription_event(
        event_type="customer.subscription.updated",
        subscription=make_stripe_subscription(
            subscription_id="sub_team",
            account_id="cus_team",
            metadata={"account_id": str(organization.id), "plan": "team"},
            trial_start=1_720_000_000,
            trial_end=1_720_604_800,
            schedule="sub_sched_team",
            items=[
                _subscription_item(item_id="si_base", price_id="price_team"),
                _subscription_item(item_id="si_seat", price_id="price_team_seat", quantity=5),
            ],
        ),
    )

    response = await client.handle_webhook(request=_webhook_request())

    assert response == {"received": True}
    updated = adapter.subscriptions[subscription.id]
    assert updated.trial_start is not None
    assert updated.trial_end is not None
    assert updated.seats == 5
    assert updated.stripe_schedule_id == "sub_sched_team"


@pytest.mark.asyncio
async def test_handle_webhook_created_calls_on_trial_start_when_trial_is_first_synced() -> None:
    individual = make_individual()
    captured_contexts = []
    captured_statuses = []
    adapter_ref: InMemoryStripeAdapter | None = None

    async def on_trial_start(context) -> None:
        assert adapter_ref is not None
        captured_contexts.append(context)
        captured_statuses.append(adapter_ref.subscriptions[context.subscription.id].status)

    client, belgie_client, stripe_sdk, adapter = _build_client(
        individual=individual,
        plans=[
            StripePlan(
                name="starter",
                price_id="price_starter",
                free_trial=StripeFreeTrial(days=7, on_trial_start=on_trial_start),
            ),
        ],
    )
    adapter_ref = adapter
    stripe_sdk.event = make_subscription_event(
        event_type="customer.subscription.created",
        subscription=make_stripe_subscription(
            subscription_id="sub_trial_start",
            account_id="cus_trial_start",
            status="trialing",
            trial_start=1_720_000_000,
            trial_end=1_720_604_800,
            metadata={"account_id": str(individual.id), "plan": "starter"},
            price_id="price_starter",
        ),
    )

    response = await client.handle_webhook(request=_webhook_request())

    assert response == {"received": True}
    assert captured_statuses == ["trialing"]
    assert len(captured_contexts) == 1
    context = captured_contexts[0]
    assert context.account is belgie_client.individual
    assert context.plan is not None
    assert context.plan.name == "starter"
    assert context.subscription.status == "trialing"
    assert context.subscription.trial_start == datetime.fromtimestamp(1_720_000_000, UTC)
    assert context.subscription.trial_end == datetime.fromtimestamp(1_720_604_800, UTC)


@pytest.mark.asyncio
async def test_handle_webhook_updated_calls_on_trial_end() -> None:
    individual = make_individual(stripe_customer_id="cus_trial_end")
    captured_contexts = []
    adapter_ref: InMemoryStripeAdapter | None = None

    async def on_trial_end(context) -> None:
        assert adapter_ref is not None
        captured_contexts.append((context, adapter_ref.subscriptions[context.subscription.id].status))

    client, _belgie_client, stripe_sdk, adapter = _build_client(
        individual=individual,
        plans=[
            StripePlan(
                name="starter",
                price_id="price_starter",
                free_trial=StripeFreeTrial(days=7, on_trial_end=on_trial_end),
            ),
        ],
    )
    adapter_ref = adapter
    subscription = await adapter.create_subscription(
        client.client.db,
        plan="starter",
        account_id=individual.id,
        stripe_customer_id="cus_trial_end",
        stripe_subscription_id="sub_trial_end",
        status="trialing",
        trial_start=datetime.fromtimestamp(1_720_000_000, UTC),
        trial_end=datetime.fromtimestamp(1_720_604_800, UTC),
        billing_interval="month",
    )
    stripe_sdk.event = make_subscription_event(
        event_type="customer.subscription.updated",
        subscription=make_stripe_subscription(
            subscription_id="sub_trial_end",
            account_id="cus_trial_end",
            status="active",
            trial_start=1_720_000_000,
            trial_end=1_720_604_800,
            metadata={},
            price_id="price_starter",
        ),
    )

    response = await client.handle_webhook(request=_webhook_request())

    assert response == {"received": True}
    assert adapter.subscriptions[subscription.id].status == "active"
    assert len(captured_contexts) == 1
    context, persisted_status = captured_contexts[0]
    assert persisted_status == "active"
    assert context.subscription.status == "active"


@pytest.mark.asyncio
async def test_handle_webhook_updated_calls_on_trial_expired() -> None:
    individual = make_individual(stripe_customer_id="cus_trial_expired")
    captured_contexts = []
    adapter_ref: InMemoryStripeAdapter | None = None

    async def on_trial_expired(context) -> None:
        assert adapter_ref is not None
        captured_contexts.append((context, adapter_ref.subscriptions[context.subscription.id].status))

    client, _belgie_client, stripe_sdk, adapter = _build_client(
        individual=individual,
        plans=[
            StripePlan(
                name="starter",
                price_id="price_starter",
                free_trial=StripeFreeTrial(days=7, on_trial_expired=on_trial_expired),
            ),
        ],
    )
    adapter_ref = adapter
    subscription = await adapter.create_subscription(
        client.client.db,
        plan="starter",
        account_id=individual.id,
        stripe_customer_id="cus_trial_expired",
        stripe_subscription_id="sub_trial_expired",
        status="trialing",
        trial_start=datetime.fromtimestamp(1_720_000_000, UTC),
        trial_end=datetime.fromtimestamp(1_720_604_800, UTC),
        billing_interval="month",
    )
    stripe_sdk.event = make_subscription_event(
        event_type="customer.subscription.updated",
        subscription=make_stripe_subscription(
            subscription_id="sub_trial_expired",
            account_id="cus_trial_expired",
            status="incomplete_expired",
            trial_start=1_720_000_000,
            trial_end=1_720_604_800,
            metadata={},
            price_id="price_starter",
        ),
    )

    response = await client.handle_webhook(request=_webhook_request())

    assert response == {"received": True}
    assert adapter.subscriptions[subscription.id].status == "incomplete_expired"
    assert len(captured_contexts) == 1
    context, persisted_status = captured_contexts[0]
    assert persisted_status == "incomplete_expired"
    assert context.subscription.status == "incomplete_expired"


@pytest.mark.asyncio
async def test_sync_organization_name_updates_customer() -> None:
    organization = make_organization(stripe_customer_id="cus_org")
    client, _belgie_client, stripe_sdk, _adapter = _build_client(
        accounts={organization.id: organization},
    )

    await client.sync_organization_name(organization_id=organization.id)

    assert stripe_sdk.updated_customers == [
        ("cus_org", {"name": organization.name}),
    ]


@pytest.mark.asyncio
async def test_sync_organization_seats_updates_subscription_quantity() -> None:
    organization = make_organization(stripe_customer_id="cus_org")
    plans = [
        StripePlan(
            name="team",
            price_id="price_team",
            seat_price_id="price_team_seat",
        ),
    ]
    organization_adapter = SimpleNamespace(
        list_members=AsyncMock(
            return_value=[SimpleNamespace(id=uuid4()) for _ in range(3)],
        ),
    )
    client, _belgie_client, stripe_sdk, adapter = _build_client(
        accounts={organization.id: organization},
        plans=plans,
        organization_adapter=organization_adapter,
    )
    subscription = await adapter.create_subscription(
        client.client.db,
        plan="team",
        account_id=organization.id,
        stripe_customer_id="cus_org",
        stripe_subscription_id="sub_org",
        status="active",
        seats=1,
        billing_interval="month",
    )
    stripe_sdk.subscription_responses["sub_org"] = make_stripe_subscription(
        subscription_id="sub_org",
        account_id="cus_org",
        metadata={"account_id": str(organization.id), "plan": "team"},
        items=[
            _subscription_item(item_id="si_base", price_id="price_team"),
            _subscription_item(item_id="si_seat", price_id="price_team_seat", quantity=1),
        ],
    )

    await client.sync_organization_seats(organization_id=organization.id)

    update_items = stripe_sdk.modified_subscriptions[0][1]["items"]
    assert {"id": "si_seat", "quantity": 3} in update_items
    assert adapter.subscriptions[subscription.id].seats == 3


@pytest.mark.asyncio
async def test_ensure_organization_can_delete_rejects_active_subscription() -> None:
    organization = make_organization()
    client, _belgie_client, _stripe_sdk, adapter = _build_client(
        accounts={organization.id: organization},
    )
    await adapter.create_subscription(
        client.client.db,
        plan="team",
        account_id=organization.id,
        status="active",
    )

    with pytest.raises(HTTPException, match="active subscription"):
        await client.ensure_organization_can_delete(organization_id=organization.id)


@pytest.mark.asyncio
async def test_ensure_account_calls_on_account_create_with_typed_context() -> None:
    on_account_create = AsyncMock()
    client, belgie_client, _stripe_sdk, _adapter = _build_client(
        on_account_create=on_account_create,
    )

    stripe_customer_id = await client.ensure_account(
        account_id=belgie_client.individual.id,
        metadata={"source": "signup"},
    )

    callback_context = on_account_create.await_args.args[0]
    assert callback_context.account is belgie_client.individual
    assert callback_context.stripe_customer_id == stripe_customer_id
    assert callback_context.metadata == {"source": "signup"}


@pytest.mark.asyncio
async def test_cancel_syncs_pending_cancellation_when_portal_creation_fails() -> None:
    individual = make_individual(stripe_customer_id="cus_existing")
    client, _belgie_client, stripe_sdk, adapter = _build_client(individual=individual)
    subscription = await adapter.create_subscription(
        client.client.db,
        plan="pro",
        account_id=individual.id,
        stripe_customer_id="cus_existing",
        stripe_subscription_id="sub_existing",
        status="active",
    )
    cancel_at = 1_720_000_000
    canceled_at = cancel_at - 300
    stripe_sdk.subscription_responses["sub_existing"] = make_stripe_subscription(
        subscription_id="sub_existing",
        account_id="cus_existing",
        status="active",
        cancel_at=cancel_at,
        canceled_at=canceled_at,
        metadata={},
    )
    stripe_sdk.billing_portal_session_errors.append(
        stripe.error.InvalidRequestError(
            "This subscription is already set to be canceled",
            "flow_data[subscription_cancel][subscription]",
        ),
    )

    with pytest.raises(stripe.error.InvalidRequestError, match="already set to be canceled"):
        await client.cancel(
            data=CancelSubscriptionRequest(
                subscription_id=subscription.id,
                return_url="/billing",
            ),
        )

    updated = adapter.subscriptions[subscription.id]
    assert updated.cancel_at_period_end is False
    assert updated.cancel_at == datetime.fromtimestamp(cancel_at, UTC)
    assert updated.canceled_at == datetime.fromtimestamp(canceled_at, UTC)


@pytest.mark.asyncio
async def test_handle_webhook_rejects_missing_signature_header() -> None:
    client, _belgie_client, _stripe_sdk, _adapter = _build_client()
    request = MagicMock()
    request.body = AsyncMock(return_value=b"{}")
    request.headers = {}

    with pytest.raises(HTTPException, match="missing stripe-signature"):
        await client.handle_webhook(request=request)


@pytest.mark.asyncio
async def test_handle_webhook_rejects_invalid_signature() -> None:
    client, _belgie_client, stripe_sdk, _adapter = _build_client()
    stripe_sdk.construct_event_error = stripe.error.SignatureVerificationError(
        "invalid signature",
        sig_header="sig_test",
        http_body=b"{}",
    )

    with pytest.raises(HTTPException, match="invalid stripe webhook"):
        await client.handle_webhook(request=_webhook_request())


@pytest.mark.asyncio
async def test_handle_webhook_deleted_subscription_syncs_cancel_and_end_timestamps() -> None:
    individual = make_individual(stripe_customer_id="cus_existing")
    client, _belgie_client, stripe_sdk, adapter = _build_client(individual=individual)
    subscription = await adapter.create_subscription(
        client.client.db,
        plan="pro",
        account_id=individual.id,
        stripe_customer_id="cus_existing",
        stripe_subscription_id="sub_existing",
        status="active",
    )
    cancel_at = 1_720_000_000
    canceled_at = cancel_at - 120
    ended_at = cancel_at + 120
    stripe_sdk.event = make_subscription_event(
        event_type="customer.subscription.deleted",
        subscription=make_stripe_subscription(
            subscription_id="sub_existing",
            account_id="cus_existing",
            status="canceled",
            cancel_at=cancel_at,
            canceled_at=canceled_at,
            ended_at=ended_at,
            metadata={},
        ),
    )

    response = await client.handle_webhook(request=_webhook_request())

    assert response == {"received": True}
    updated = adapter.subscriptions[subscription.id]
    assert updated.status == "canceled"
    assert updated.cancel_at == datetime.fromtimestamp(cancel_at, UTC)
    assert updated.canceled_at == datetime.fromtimestamp(canceled_at, UTC)
    assert updated.ended_at == datetime.fromtimestamp(ended_at, UTC)


@pytest.mark.asyncio
async def test_handle_webhook_created_skips_duplicate_subscription_and_created_hook() -> None:
    individual = make_individual(stripe_customer_id="cus_existing")
    on_subscription_created = AsyncMock()
    client, _belgie_client, stripe_sdk, adapter = _build_client(
        individual=individual,
        on_subscription_created=on_subscription_created,
    )
    existing = await adapter.create_subscription(
        client.client.db,
        plan="pro",
        account_id=individual.id,
        stripe_customer_id="cus_existing",
        stripe_subscription_id="sub_existing",
        status="active",
        billing_interval="month",
    )
    stripe_sdk.event = make_subscription_event(
        event_type="customer.subscription.created",
        subscription=make_stripe_subscription(
            subscription_id="sub_existing",
            account_id="cus_existing",
            status="active",
            metadata={"account_id": str(individual.id), "plan": "pro"},
        ),
    )

    response = await client.handle_webhook(request=_webhook_request())

    assert response == {"received": True}
    assert len(adapter.subscriptions) == 1
    assert adapter.subscriptions[existing.id].stripe_subscription_id == "sub_existing"
    on_subscription_created.assert_not_awaited()


@pytest.mark.asyncio
async def test_subscription_event_hooks_receive_persisted_local_state() -> None:
    individual = make_individual(stripe_customer_id="cus_existing")
    adapter_ref: InMemoryStripeAdapter | None = None
    created_states = []
    updated_states = []
    deleted_states = []
    canceled_states = []

    async def on_subscription_created(context) -> None:
        assert adapter_ref is not None
        created_states.append(
            (
                context.subscription.status,
                adapter_ref.subscriptions[context.subscription.id].status,
            ),
        )

    async def on_subscription_updated(context) -> None:
        assert adapter_ref is not None
        updated_states.append(
            (
                context.subscription.seats,
                adapter_ref.subscriptions[context.subscription.id].seats,
            ),
        )

    async def on_subscription_deleted(context) -> None:
        assert adapter_ref is not None
        deleted_states.append(
            (
                context.subscription.status,
                adapter_ref.subscriptions[context.subscription.id].status,
            ),
        )

    async def on_subscription_canceled(context) -> None:
        assert adapter_ref is not None
        canceled_states.append(
            (
                context.subscription.status,
                adapter_ref.subscriptions[context.subscription.id].status,
            ),
        )

    client, _belgie_client, stripe_sdk, adapter = _build_client(
        individual=individual,
        on_subscription_created=on_subscription_created,
        on_subscription_updated=on_subscription_updated,
        on_subscription_deleted=on_subscription_deleted,
        on_subscription_canceled=on_subscription_canceled,
    )
    adapter_ref = adapter
    stripe_sdk.event = make_subscription_event(
        event_type="customer.subscription.created",
        subscription=make_stripe_subscription(
            subscription_id="sub_existing",
            account_id="cus_existing",
            status="active",
            metadata={"account_id": str(individual.id), "plan": "pro"},
        ),
    )

    created_response = await client.handle_webhook(request=_webhook_request())

    created_subscription = next(iter(adapter.subscriptions.values()))
    stripe_sdk.event = make_subscription_event(
        event_type="customer.subscription.updated",
        subscription=make_stripe_subscription(
            subscription_id="sub_existing",
            account_id="cus_existing",
            status="active",
            metadata={},
            items=[_subscription_item(item_id="si_base", price_id="price_pro", quantity=5)],
        ),
    )

    updated_response = await client.handle_webhook(request=_webhook_request())

    stripe_sdk.event = make_subscription_event(
        event_type="customer.subscription.deleted",
        subscription=make_stripe_subscription(
            subscription_id="sub_existing",
            account_id="cus_existing",
            status="canceled",
            ended_at=1_720_000_120,
            metadata={},
        ),
    )

    deleted_response = await client.handle_webhook(request=_webhook_request())

    assert created_response == {"received": True}
    assert updated_response == {"received": True}
    assert deleted_response == {"received": True}
    assert created_states == [("active", "active")]
    assert updated_states == [(5, 5)]
    assert deleted_states == [("canceled", "canceled")]
    assert canceled_states == [("canceled", "canceled")]
    assert adapter.subscriptions[created_subscription.id].status == "canceled"


@pytest.mark.asyncio
async def test_handle_webhook_clears_plugin_schedule_when_schedule_removed() -> None:
    individual = make_individual(stripe_customer_id="cus_existing")
    client, _belgie_client, stripe_sdk, adapter = _build_client(individual=individual)
    subscription = await adapter.create_subscription(
        client.client.db,
        plan="pro",
        account_id=individual.id,
        stripe_customer_id="cus_existing",
        stripe_subscription_id="sub_existing",
        stripe_schedule_id="sub_sched_existing",
        status="active",
    )
    stripe_sdk.event = make_subscription_event(
        event_type="customer.subscription.updated",
        subscription=make_stripe_subscription(
            subscription_id="sub_existing",
            account_id="cus_existing",
            status="active",
            metadata={},
            schedule=None,
        ),
    )

    response = await client.handle_webhook(request=_webhook_request())

    assert response == {"received": True}
    assert adapter.subscriptions[subscription.id].stripe_schedule_id is None


def test_build_subscription_update_items_swaps_and_deletes_removed_items() -> None:
    client, _belgie_client, _stripe_sdk, _adapter = _build_client()
    current_items = list(
        make_stripe_subscription(
            items=[
                _subscription_item(item_id="si_base", price_id="price_pro"),
                _subscription_item(item_id="si_addon", price_id="price_addon"),
            ],
        ).items.data,
    )

    update_items = client._build_subscription_update_items(
        current_items=current_items,
        desired_items=[DesiredSubscriptionItem(price_id="price_starter", quantity=1)],
    )

    assert {"id": "si_base", "price": "price_starter", "quantity": 1} in update_items
    assert {"id": "si_addon", "deleted": True} in update_items


@pytest.mark.asyncio
async def test_stripe_param_helpers_build_stripe_15_typed_payloads() -> None:
    client, _belgie_client, _stripe_sdk, _adapter = _build_client()
    line_items = await client._build_checkout_line_items(
        [DesiredSubscriptionItem(price_id="price_pro", quantity=2)],
    )

    checkout_params = await client._build_checkout_session_params(
        extra_params=checkout.SessionCreateParams(
            metadata={"source": "hook", "plan": "spoofed"},
            subscription_data={"metadata": {"subscription": "hook"}},
        ),
        customer_id="cus_123",
        line_items=line_items,
        redirect_urls=("http://localhost:8000/success", "http://localhost:8000/cancel"),
        metadata={"plan": "pro", "local_subscription_id": str(uuid4())},
        locale="en",
        trial_days=14,
        proration_behavior="none",
    )
    cancel_portal_params = client._build_cancel_portal_params(
        customer_id="cus_123",
        return_url="http://localhost:8000/account",
        subscription_id="sub_123",
        locale="en",
    )
    phase_items = client._build_schedule_phase_items(
        [DesiredSubscriptionItem(price_id="price_pro", quantity=2)],
    )

    assert checkout_params["mode"] == "subscription"
    assert checkout_params["line_items"] == [{"price": "price_pro", "quantity": 2}]
    assert checkout_params["metadata"]["source"] == "hook"
    assert checkout_params["metadata"]["plan"] == "pro"
    assert checkout_params["subscription_data"]["trial_period_days"] == 14
    assert checkout_params["subscription_data"]["proration_behavior"] == "none"
    assert checkout_params["subscription_data"]["metadata"]["subscription"] == "hook"
    assert checkout_params["subscription_data"]["metadata"]["plan"] == "pro"
    assert cancel_portal_params["flow_data"]["type"] == "subscription_cancel"
    assert cancel_portal_params["flow_data"]["subscription_cancel"]["subscription"] == "sub_123"
    assert phase_items == [{"price": "price_pro", "quantity": 2}]


def test_parse_subscription_metadata_extracts_typed_values() -> None:
    account_id = uuid4()
    subscription_id = uuid4()

    parsed = parse_subscription_metadata(
        {
            "account_id": str(account_id),
            "account_type": AccountType.ORGANIZATION,
            "local_subscription_id": str(subscription_id),
            "plan": "team",
        },
    )

    assert parsed.account_id == account_id
    assert parsed.account_type == AccountType.ORGANIZATION
    assert parsed.local_subscription_id == subscription_id
    assert parsed.plan == "team"


def test_parse_customer_metadata_ignores_invalid_values() -> None:
    parsed = parse_customer_metadata(
        {
            "account_id": "not-a-uuid",
            "account_type": "not-an-account-type",
        },
    )

    assert parsed.raw["account_id"] == "not-a-uuid"
    assert parsed.account_id is None
    assert parsed.account_type is None


def test_parse_schedule_metadata_marks_plugin_owned_schedules() -> None:
    parsed = parse_schedule_metadata({"managed_by": "belgie-stripe"})

    assert parsed.is_managed_by_plugin is True
