from __future__ import annotations

import pytest
from belgie_core.core.settings import BelgieSettings
from belgie_organization.plugin import OrganizationPlugin
from belgie_organization.settings import Organization
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient

from belgie_stripe import Stripe, StripeClient, StripeOrganization, StripePlan, StripePlugin, StripeSubscription
from belgie_stripe.__tests__.fakes import (
    DummyBelgie,
    FakeBelgieClient,
    FakeOrganizationAdapter,
    FakeStripeSDK,
    InMemoryStripeAdapter,
    make_session,
    make_user,
)


def _build_plugin(
    *,
    stripe_sdk: FakeStripeSDK | None = None,
    adapter: InMemoryStripeAdapter | None = None,
    create_customer_on_sign_up: bool = False,
    organization: StripeOrganization | None = None,
) -> tuple[StripePlugin, DummyBelgie, FakeBelgieClient, FakeStripeSDK, InMemoryStripeAdapter]:
    settings = BelgieSettings(secret="test-secret", base_url="http://localhost:8000")
    user = make_user()
    belgie_client = FakeBelgieClient(user=user, session=make_session(user_id=user.id))
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
            ),
            organization=organization,
        ),
    )
    belgie = DummyBelgie(belgie_client, plugins=[] if organization is None else [plugin])
    return plugin, belgie, belgie_client, stripe_sdk, adapter


def test_plugin_injects_stripe_client() -> None:
    plugin, belgie, belgie_client, _stripe_sdk, _adapter = _build_plugin()

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)

    @app.get("/stripe-client")
    async def stripe_client_route(stripe: StripeClient = Depends(plugin)) -> dict[str, str]:
        return {"user_id": str(stripe.current_user.id)}

    response = TestClient(app).get("/stripe-client")

    assert response.status_code == 200
    assert response.json() == {"user_id": str(belgie_client.user.id)}


def test_upgrade_route_redirects_by_default() -> None:
    plugin, belgie, _belgie_client, stripe_sdk, _adapter = _build_plugin()

    app = FastAPI()
    auth_router = APIRouter(prefix="/auth")
    auth_router.include_router(plugin.router(belgie))
    app.include_router(auth_router)

    response = TestClient(app).post(
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

    response = TestClient(app).post(
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


def test_plugin_requires_organization_plugin_when_enabled() -> None:
    plugin, belgie, _belgie_client, _stripe_sdk, _adapter = _build_plugin(
        organization=StripeOrganization(enabled=True),
    )

    with pytest.raises(RuntimeError, match="requires organization plugin"):
        plugin.router(belgie)


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
        user=belgie_client.user,
    )

    assert stripe_sdk.created_customers
    assert belgie_client.user.stripe_customer_id == "cus_1"


def test_plugin_uses_registered_organization_adapter() -> None:
    settings = BelgieSettings(secret="test-secret", base_url="http://localhost:8000")
    user = make_user()
    belgie_client = FakeBelgieClient(user=user, session=make_session(user_id=user.id))
    stripe_sdk = FakeStripeSDK()
    stripe_adapter = InMemoryStripeAdapter()
    organization_adapter = FakeOrganizationAdapter()
    organization_plugin = OrganizationPlugin(settings, Organization(adapter=organization_adapter))
    stripe_plugin = StripePlugin(
        settings,
        Stripe(
            stripe=stripe_sdk,
            stripe_webhook_secret="whsec_test",
            subscription=StripeSubscription(
                adapter=stripe_adapter,
                plans=[StripePlan(name="pro", price_id="price_pro", annual_price_id="price_pro_year")],
            ),
            organization=StripeOrganization(enabled=True),
        ),
    )
    belgie = DummyBelgie(
        belgie_client,
        plugins=[organization_plugin, stripe_plugin],
    )

    router = stripe_plugin.router(belgie)

    assert router is not None
    assert stripe_plugin._organization_adapter is organization_adapter
