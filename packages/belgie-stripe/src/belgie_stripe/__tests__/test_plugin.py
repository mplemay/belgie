from dataclasses import replace
from typing import Annotated
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from belgie_core.core.settings import BelgieSettings
from belgie_organization import Organization, OrganizationPlugin
from belgie_proto.organization import OrganizationAdapterProtocol
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from belgie_stripe import Stripe, StripeClient, StripePlan, StripePlugin, StripeSubscription
from belgie_stripe.__tests__.fakes import (
    DummyBelgie,
    FakeAccount,
    FakeBelgieClient,
    FakeStripeSDK,
    InMemoryStripeAdapter,
    make_customer,
    make_individual,
    make_session,
    make_team,
)


class FakeOrganizationAdapter(OrganizationAdapterProtocol):
    def __getattr__(self, _name: str) -> AsyncMock:
        return AsyncMock()


def _build_plugin(
    *,
    stripe_sdk: FakeStripeSDK | None = None,
    adapter: InMemoryStripeAdapter | None = None,
    create_account_on_sign_up: bool = False,
    accounts: dict[UUID, FakeAccount] | None = None,
    authorize_account=None,
) -> tuple[StripePlugin, DummyBelgie, FakeBelgieClient, FakeStripeSDK, InMemoryStripeAdapter]:
    settings = BelgieSettings(secret="test-secret", base_url="http://localhost:8000")
    individual = make_individual()
    belgie_client = FakeBelgieClient(
        individual=individual,
        accounts=accounts,
        session=make_session(individual_id=individual.id),
    )
    stripe_sdk = FakeStripeSDK() if stripe_sdk is None else stripe_sdk
    adapter = InMemoryStripeAdapter() if adapter is None else adapter
    plugin = StripePlugin(
        settings,
        Stripe(
            stripe=stripe_sdk,
            stripe_webhook_secret="whsec_test",
            create_account_on_sign_up=create_account_on_sign_up,
            subscription=StripeSubscription(
                adapter=adapter,
                plans=[StripePlan(name="pro", price_id="price_pro", annual_price_id="price_pro_year")],
                authorize_account=authorize_account,
            ),
        ),
    )
    belgie = DummyBelgie(belgie_client, plugins=[plugin])
    return plugin, belgie, belgie_client, stripe_sdk, adapter


def test_plugin_injects_stripe_client() -> None:
    plugin, belgie, belgie_client, _stripe_sdk, _adapter = _build_plugin()

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)

    @app.get("/stripe-client")
    async def stripe_client_route(stripe: Annotated[StripeClient, Depends(plugin)]) -> dict[str, str]:
        assert stripe.current_individual is not None
        return {"individual_id": str(stripe.current_individual.id)}

    with TestClient(app) as test_client:
        response = test_client.get("/stripe-client")

    assert response.status_code == 200
    assert response.json() == {"individual_id": str(belgie_client.individual.id)}


def test_upgrade_route_redirects_by_default() -> None:
    plugin, belgie, _belgie_client, stripe_sdk, _adapter = _build_plugin()

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)

    with TestClient(app) as test_client:
        response = test_client.post(
            "/auth/subscription/upgrade",
            json={
                "plan": "pro",
                "success_url": "/dashboard",
                "cancel_url": "/pricing",
            },
            follow_redirects=False,
        )

    assert response.status_code == 302
    assert response.headers["location"] == "https://checkout.stripe.test/session"
    assert stripe_sdk.created_checkout_sessions
    assert stripe_sdk.created_checkout_sessions[0]["success_url"].startswith(
        "http://localhost:8000/auth/subscription/success?token=",
    )
    assert "{CHECKOUT_SESSION_ID}" in stripe_sdk.created_checkout_sessions[0]["success_url"]


def test_upgrade_route_returns_json_when_redirect_disabled() -> None:
    plugin, belgie, _belgie_client, _stripe_sdk, _adapter = _build_plugin()

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)

    with TestClient(app) as test_client:
        response = test_client.post(
            "/auth/subscription/upgrade",
            json={
                "plan": "pro",
                "success_url": "/dashboard",
                "cancel_url": "/pricing",
                "disable_redirect": True,
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "url": "https://checkout.stripe.test/session",
        "redirect": False,
    }


def test_list_subscriptions_rejects_invalid_account_id() -> None:
    plugin, belgie, _belgie_client, _stripe_sdk, _adapter = _build_plugin()

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)

    with TestClient(app) as test_client:
        response = test_client.get(
            "/auth/subscription/list",
            params={"account_id": "invalid"},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_subscriptions_route_supports_team_account_id() -> None:
    team = make_team()
    authorize_account = AsyncMock(return_value=True)
    plugin, belgie, belgie_client, _stripe_sdk, adapter = _build_plugin(
        accounts={team.id: team},
        authorize_account=authorize_account,
    )

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)

    await adapter.create_subscription(
        belgie_client.db,
        plan="pro",
        account_id=team.id,
        status="active",
    )

    with TestClient(app) as test_client:
        response = test_client.get(
            "/auth/subscription/list",
            params={"account_id": str(team.id)},
        )

    assert response.status_code == 200
    assert response.json()[0]["account_id"] == str(team.id)


@pytest.mark.asyncio
async def test_dependency_requires_router_initialization() -> None:
    plugin, _belgie, _belgie_client, _stripe_sdk, _adapter = _build_plugin()

    with pytest.raises(RuntimeError, match="router initialization"):
        await plugin(object(), object())


@pytest.mark.asyncio
async def test_after_sign_up_creates_customer_when_enabled() -> None:
    plugin, belgie, belgie_client, stripe_sdk, _adapter = _build_plugin(
        create_account_on_sign_up=True,
    )

    await plugin.after_sign_up(
        belgie=belgie,
        client=belgie_client,
        request=None,
        individual=belgie_client.individual,
    )

    assert stripe_sdk.created_customers
    assert belgie_client.individual.stripe_customer_id == "cus_1"


@pytest.mark.asyncio
async def test_after_update_individual_syncs_changed_email_to_stripe() -> None:
    plugin, belgie, belgie_client, stripe_sdk, _adapter = _build_plugin()
    previous_individual = replace(
        belgie_client.individual,
        email="old@example.com",
        stripe_customer_id="cus_existing",
    )
    updated_individual = replace(
        belgie_client.individual,
        email="new@example.com",
        stripe_customer_id="cus_existing",
    )
    stripe_sdk.customer_responses["cus_existing"] = make_customer(
        customer_id="cus_existing",
        email="old@example.com",
    )

    await plugin.after_update_individual(
        belgie=belgie,
        client=belgie_client,
        request=None,
        previous_individual=previous_individual,
        individual=updated_individual,
    )

    assert stripe_sdk.retrieved_customers == ["cus_existing"]
    assert stripe_sdk.updated_customers == [
        ("cus_existing", {"email": "new@example.com"}),
    ]


def test_router_configures_organization_hooks_when_plugin_present() -> None:
    plugin, belgie, _belgie_client, _stripe_sdk, _adapter = _build_plugin()
    organization_plugin = OrganizationPlugin(
        BelgieSettings(secret="test-secret", base_url="http://localhost:8000"),
        Organization(adapter=FakeOrganizationAdapter()),
    )
    belgie.plugins = [organization_plugin, plugin]

    _ = plugin.router(belgie)

    assert organization_plugin.settings.after_update is not None
    assert organization_plugin.settings.before_delete is not None
    assert organization_plugin.settings.after_member_add is not None
    assert organization_plugin.settings.after_member_remove is not None
    assert organization_plugin.settings.after_invitation_accept is not None
