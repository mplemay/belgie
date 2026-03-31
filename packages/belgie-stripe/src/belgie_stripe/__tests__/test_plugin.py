from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest
from belgie_core.core.settings import BelgieSettings
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from belgie_stripe import Stripe, StripeClient, StripePlan, StripePlugin, StripeSubscription
from belgie_stripe.__tests__.fakes import (
    DummyBelgie,
    FakeBelgieClient,
    FakeCustomer,
    FakeStripeSDK,
    InMemoryStripeAdapter,
    make_individual,
    make_session,
    make_team,
)

if TYPE_CHECKING:
    from uuid import UUID


def _build_plugin(
    *,
    stripe_sdk: FakeStripeSDK | None = None,
    adapter: InMemoryStripeAdapter | None = None,
    create_customer_on_sign_up: bool = False,
    customers: dict[UUID, FakeCustomer] | None = None,
    authorize_customer=None,
) -> tuple[StripePlugin, DummyBelgie, FakeBelgieClient, FakeStripeSDK, InMemoryStripeAdapter]:
    settings = BelgieSettings(secret="test-secret", base_url="http://localhost:8000")
    individual = make_individual()
    belgie_client = FakeBelgieClient(
        individual=individual,
        customers=customers,
        session=make_session(individual_id=individual.id),
    )
    stripe_sdk = FakeStripeSDK() if stripe_sdk is None else stripe_sdk
    adapter = InMemoryStripeAdapter() if adapter is None else adapter
    plugin = StripePlugin(
        settings,
        Stripe(
            stripe=stripe_sdk,
            stripe_webhook_secret="whsec_test",
            create_customer_on_sign_up=create_customer_on_sign_up,
            subscription=StripeSubscription(
                adapter=adapter,
                plans=[StripePlan(name="pro", price_id="price_pro", annual_price_id="price_pro_year")],
                authorize_customer=authorize_customer,
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
    async def stripe_client_route(stripe: StripeClient = Depends(plugin)) -> dict[str, str]:
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


def test_list_subscriptions_rejects_invalid_customer_id() -> None:
    plugin, belgie, _belgie_client, _stripe_sdk, _adapter = _build_plugin()

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)

    with TestClient(app) as test_client:
        response = test_client.get(
            "/auth/subscription/list",
            params={"customer_id": "invalid"},
        )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_list_subscriptions_route_supports_team_customer_id() -> None:
    team = make_team()
    authorize_customer = AsyncMock(return_value=True)
    plugin, belgie, belgie_client, _stripe_sdk, adapter = _build_plugin(
        customers={team.id: team},
        authorize_customer=authorize_customer,
    )

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)

    await adapter.create_subscription(
        belgie_client.db,
        plan="pro",
        customer_id=team.id,
        status="active",
    )

    with TestClient(app) as test_client:
        response = test_client.get(
            "/auth/subscription/list",
            params={"customer_id": str(team.id)},
        )

    assert response.status_code == 200
    assert response.json()[0]["customer_id"] == str(team.id)


@pytest.mark.asyncio
async def test_dependency_requires_router_initialization() -> None:
    plugin, _belgie, _belgie_client, _stripe_sdk, _adapter = _build_plugin()

    with pytest.raises(RuntimeError, match="router initialization"):
        await plugin(object(), object())


@pytest.mark.asyncio
async def test_after_sign_up_creates_customer_when_enabled() -> None:
    plugin, belgie, belgie_client, stripe_sdk, _adapter = _build_plugin(
        create_customer_on_sign_up=True,
    )

    await plugin.after_sign_up(
        belgie=belgie,
        client=belgie_client,
        request=None,
        individual=belgie_client.individual,
    )

    assert stripe_sdk.created_customers
    assert belgie_client.individual.stripe_customer_id == "cus_1"
