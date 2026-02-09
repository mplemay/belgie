import time

import httpx
import pytest
from belgie_oauth_server.plugin import OAuthServerPlugin
from belgie_oauth_server.provider import AccessToken

BEARER = "Bearer"


@pytest.mark.asyncio
async def test_introspect_missing_token(async_client: httpx.AsyncClient) -> None:
    response = await async_client.post("/auth/oauth/introspect", data={})
    assert response.status_code == 400
    assert response.json()["active"] is False


@pytest.mark.asyncio
async def test_introspect_unknown_token(async_client: httpx.AsyncClient) -> None:
    response = await async_client.post("/auth/oauth/introspect", data={"token": "missing"})
    assert response.status_code == 200
    assert response.json()["active"] is False


@pytest.mark.asyncio
async def test_introspect_active_token(async_client: httpx.AsyncClient, oauth_plugin: OAuthServerPlugin) -> None:
    provider = oauth_plugin._provider
    created_at = int(time.time()) - 5
    provider.tokens["token-123"] = AccessToken(
        token="token-123",
        client_id="test-client",
        scopes=["user"],
        created_at=created_at,
        expires_at=int(time.time()) + 3600,
        resource="http://example.com/resource",
    )

    response = await async_client.post("/auth/oauth/introspect", data={"token": "token-123"})
    payload = response.json()

    assert payload["active"] is True
    assert payload["client_id"] == "test-client"
    assert payload["scope"] == "user"
    assert payload["iat"] == created_at
    assert payload["token_type"] == BEARER
    assert payload["aud"] == "http://example.com/resource"


@pytest.mark.asyncio
async def test_introspect_active_token_without_client_auth(
    async_client: httpx.AsyncClient,
    oauth_plugin: OAuthServerPlugin,
) -> None:
    provider = oauth_plugin._provider
    provider.tokens["token-no-auth"] = AccessToken(
        token="token-no-auth",
        client_id="test-client",
        scopes=["user"],
        created_at=int(time.time()) - 1,
        expires_at=int(time.time()) + 3600,
        resource=None,
    )

    response = await async_client.post("/auth/oauth/introspect", data={"token": "token-no-auth"})
    payload = response.json()

    assert payload["active"] is True
