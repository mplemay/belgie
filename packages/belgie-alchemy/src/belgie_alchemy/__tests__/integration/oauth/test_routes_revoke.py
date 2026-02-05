import time

import httpx
import pytest
from belgie_oauth_server.models import OAuthClientInformationFull
from belgie_oauth_server.plugin import OAuthPlugin
from belgie_oauth_server.provider import AccessToken
from belgie_oauth_server.settings import OAuthSettings


@pytest.mark.asyncio
async def test_revoke_missing_token(
    async_client: httpx.AsyncClient,
    oauth_settings: OAuthSettings,
) -> None:
    response = await async_client.post(
        "/auth/oauth/revoke",
        data={
            "client_id": oauth_settings.client_id,
            "client_secret": oauth_settings.client_secret.get_secret_value(),
        },
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"


@pytest.mark.asyncio
async def test_revoke_missing_client_id(async_client: httpx.AsyncClient) -> None:
    response = await async_client.post(
        "/auth/oauth/revoke",
        data={
            "client_secret": "secret",
            "token": "token-123",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"


@pytest.mark.asyncio
async def test_revoke_missing_client_secret(
    async_client: httpx.AsyncClient,
    oauth_settings: OAuthSettings,
) -> None:
    response = await async_client.post(
        "/auth/oauth/revoke",
        data={
            "client_id": oauth_settings.client_id,
            "token": "token-123",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"


@pytest.mark.asyncio
async def test_revoke_invalid_client_id(async_client: httpx.AsyncClient) -> None:
    response = await async_client.post(
        "/auth/oauth/revoke",
        data={
            "client_id": "wrong",
            "client_secret": "bad",
            "token": "token-123",
        },
    )

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_client"


@pytest.mark.asyncio
async def test_revoke_invalid_client_secret(
    async_client: httpx.AsyncClient,
    oauth_settings: OAuthSettings,
) -> None:
    response = await async_client.post(
        "/auth/oauth/revoke",
        data={
            "client_id": oauth_settings.client_id,
            "client_secret": "wrong",
            "token": "token-123",
        },
    )

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_client"


@pytest.mark.asyncio
async def test_revoke_success_removes_token(
    async_client: httpx.AsyncClient,
    oauth_settings: OAuthSettings,
    oauth_plugin: OAuthPlugin,
) -> None:
    provider = oauth_plugin._provider
    provider.tokens["token-123"] = AccessToken(
        token="token-123",
        client_id=oauth_settings.client_id,
        scopes=[oauth_settings.default_scope],
        created_at=int(time.time()),
        expires_at=int(time.time()) + 3600,
        resource=None,
    )

    response = await async_client.post(
        "/auth/oauth/revoke",
        data={
            "client_id": oauth_settings.client_id,
            "client_secret": oauth_settings.client_secret.get_secret_value(),
            "token": "token-123",
        },
    )

    assert response.status_code == 200
    assert "token-123" not in provider.tokens


@pytest.mark.asyncio
async def test_revoke_unknown_token_returns_success(
    async_client: httpx.AsyncClient,
    oauth_settings: OAuthSettings,
) -> None:
    response = await async_client.post(
        "/auth/oauth/revoke",
        data={
            "client_id": oauth_settings.client_id,
            "client_secret": oauth_settings.client_secret.get_secret_value(),
            "token": "missing",
        },
    )

    assert response.status_code == 200
    assert response.json() == {}


@pytest.mark.asyncio
async def test_revoke_public_client_without_secret(
    async_client: httpx.AsyncClient,
    oauth_plugin: OAuthPlugin,
) -> None:
    provider = oauth_plugin._provider
    provider.clients["public-client"] = OAuthClientInformationFull(
        client_id="public-client",
        client_secret=None,
        redirect_uris=["http://testserver/callback"],
        scope="user",
        token_endpoint_auth_method="none",
    )

    response = await async_client.post(
        "/auth/oauth/revoke",
        data={
            "client_id": "public-client",
            "token": "missing",
        },
    )

    assert response.status_code == 200
