from __future__ import annotations

import httpx
import pytest
from belgie_oauth_server.plugin import OAuthServerPlugin
from belgie_oauth_server.settings import OAuthServerSettings
from fastapi import FastAPI


@pytest.mark.asyncio
async def test_register_disabled_by_default(async_client: httpx.AsyncClient) -> None:
    response = await async_client.post(
        "/auth/oauth/register",
        json={
            "redirect_uris": ["http://testserver/callback"],
            "client_name": "Demo",
        },
    )

    assert response.status_code == 403
    payload = response.json()
    assert payload["error"] == "access_denied"


@pytest.mark.asyncio
async def test_register_enabled_requires_authentication(
    belgie_instance,
    oauth_settings: OAuthServerSettings,
) -> None:
    settings_payload = oauth_settings.model_dump(mode="python")
    settings_payload["allow_dynamic_client_registration"] = True
    settings = OAuthServerSettings(**settings_payload)
    belgie_instance.add_plugin(OAuthServerPlugin, settings)
    app = FastAPI()
    app.include_router(belgie_instance.router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/auth/oauth/register",
            json={
                "redirect_uris": ["http://testserver/callback"],
                "client_name": "Demo",
            },
        )

    assert response.status_code == 401
    payload = response.json()
    assert payload["error"] == "invalid_token"


@pytest.mark.asyncio
async def test_register_enabled_allows_authenticated_confidential_registration(
    belgie_instance,
    oauth_settings: OAuthServerSettings,
    db_session,
    create_user_session,
) -> None:
    settings_payload = oauth_settings.model_dump(mode="python")
    settings_payload["allow_dynamic_client_registration"] = True
    settings = OAuthServerSettings(**settings_payload)
    plugin = belgie_instance.add_plugin(OAuthServerPlugin, settings)
    app = FastAPI()
    app.include_router(belgie_instance.router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        session_id = await create_user_session(belgie_instance, db_session, "user@test.com")
        client.cookies.set(belgie_instance.settings.cookie.name, session_id)
        response = await client.post(
            "/auth/oauth/register",
            json={
                "redirect_uris": ["http://testserver/callback"],
                "client_name": "Demo",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["client_id"]
    assert payload["client_secret"]
    assert payload["client_id"] in plugin._provider.clients


@pytest.mark.asyncio
async def test_register_enabled_unauthenticated_allows_public_clients(
    belgie_instance,
    oauth_settings: OAuthServerSettings,
) -> None:
    settings_payload = oauth_settings.model_dump(mode="python")
    settings_payload["allow_dynamic_client_registration"] = True
    settings_payload["allow_unauthenticated_client_registration"] = True
    settings = OAuthServerSettings(**settings_payload)
    belgie_instance.add_plugin(OAuthServerPlugin, settings)
    app = FastAPI()
    app.include_router(belgie_instance.router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/auth/oauth/register",
            json={
                "redirect_uris": ["http://testserver/callback"],
                "token_endpoint_auth_method": "none",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["client_secret"] is None


@pytest.mark.asyncio
async def test_register_enabled_unauthenticated_rejects_confidential_clients(
    belgie_instance,
    oauth_settings: OAuthServerSettings,
) -> None:
    settings_payload = oauth_settings.model_dump(mode="python")
    settings_payload["allow_dynamic_client_registration"] = True
    settings_payload["allow_unauthenticated_client_registration"] = True
    settings = OAuthServerSettings(**settings_payload)
    belgie_instance.add_plugin(OAuthServerPlugin, settings)
    app = FastAPI()
    app.include_router(belgie_instance.router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        response = await client.post(
            "/auth/oauth/register",
            json={
                "redirect_uris": ["http://testserver/callback"],
            },
        )

    assert response.status_code == 401
    payload = response.json()
    assert payload["error"] == "invalid_request"


@pytest.mark.asyncio
async def test_register_rejects_unsupported_auth_method_when_enabled(
    belgie_instance,
    oauth_settings: OAuthServerSettings,
    db_session,
    create_user_session,
) -> None:
    settings_payload = oauth_settings.model_dump(mode="python")
    settings_payload["allow_dynamic_client_registration"] = True
    settings_payload["allow_unauthenticated_client_registration"] = True
    settings = OAuthServerSettings(**settings_payload)
    belgie_instance.add_plugin(OAuthServerPlugin, settings)
    app = FastAPI()
    app.include_router(belgie_instance.router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        session_id = await create_user_session(belgie_instance, db_session, "user@test.com")
        client.cookies.set(belgie_instance.settings.cookie.name, session_id)
        response = await client.post(
            "/auth/oauth/register",
            json={
                "redirect_uris": ["http://testserver/callback"],
                "token_endpoint_auth_method": "private_key_jwt",
            },
        )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error"] == "invalid_request"


@pytest.mark.asyncio
async def test_register_allows_post_logout_redirect_uris(
    belgie_instance,
    oauth_settings: OAuthServerSettings,
    db_session,
    create_user_session,
) -> None:
    settings_payload = oauth_settings.model_dump(mode="python")
    settings_payload["allow_dynamic_client_registration"] = True
    settings = OAuthServerSettings(**settings_payload)
    plugin = belgie_instance.add_plugin(OAuthServerPlugin, settings)
    app = FastAPI()
    app.include_router(belgie_instance.router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        session_id = await create_user_session(belgie_instance, db_session, "user@test.com")
        client.cookies.set(belgie_instance.settings.cookie.name, session_id)
        response = await client.post(
            "/auth/oauth/register",
            json={
                "redirect_uris": ["http://testserver/callback"],
                "post_logout_redirect_uris": ["http://testserver/logout-complete"],
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["post_logout_redirect_uris"] == ["http://testserver/logout-complete"]
    assert payload["client_id"] in plugin._provider.clients
    registered_client = plugin._provider.clients[payload["client_id"]]
    assert [str(uri) for uri in registered_client.post_logout_redirect_uris] == ["http://testserver/logout-complete"]


@pytest.mark.asyncio
async def test_register_ignores_enable_end_session_in_metadata(
    belgie_instance,
    oauth_settings: OAuthServerSettings,
    db_session,
    create_user_session,
) -> None:
    settings_payload = oauth_settings.model_dump(mode="python")
    settings_payload["allow_dynamic_client_registration"] = True
    settings = OAuthServerSettings(**settings_payload)
    plugin = belgie_instance.add_plugin(OAuthServerPlugin, settings)
    app = FastAPI()
    app.include_router(belgie_instance.router)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
        session_id = await create_user_session(belgie_instance, db_session, "user@test.com")
        client.cookies.set(belgie_instance.settings.cookie.name, session_id)
        response = await client.post(
            "/auth/oauth/register",
            json={
                "redirect_uris": ["http://testserver/callback"],
                "enable_end_session": True,
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["enable_end_session"] is None
    assert payload["client_id"] in plugin._provider.clients
    registered_client = plugin._provider.clients[payload["client_id"]]
    assert registered_client.enable_end_session is None
