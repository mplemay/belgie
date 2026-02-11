from __future__ import annotations

import time

import pytest
from belgie_oauth_server.models import OAuthClientInformationFull
from belgie_oauth_server.provider import AccessToken, RefreshToken

BEARER = "Bearer"


@pytest.mark.asyncio
async def test_introspect_requires_client_auth(async_client) -> None:
    response = await async_client.post("/auth/oauth/introspect", data={"token": "missing"})
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_client"


@pytest.mark.asyncio
async def test_introspect_missing_token(
    async_client,
    oauth_settings,
) -> None:
    response = await async_client.post(
        "/auth/oauth/introspect",
        data={
            "client_id": oauth_settings.client_id,
            "client_secret": oauth_settings.client_secret.get_secret_value(),
        },
    )
    assert response.status_code == 400
    assert response.json()["active"] is False


@pytest.mark.asyncio
async def test_introspect_unknown_token(
    async_client,
    oauth_settings,
) -> None:
    response = await async_client.post(
        "/auth/oauth/introspect",
        data={
            "client_id": oauth_settings.client_id,
            "client_secret": oauth_settings.client_secret.get_secret_value(),
            "token": "missing",
        },
    )
    assert response.status_code == 200
    assert response.json()["active"] is False


@pytest.mark.asyncio
async def test_introspect_active_access_token(
    async_client,
    oauth_settings,
    oauth_plugin,
) -> None:
    provider = oauth_plugin._provider
    created_at = int(time.time()) - 5
    provider.tokens["token-123"] = AccessToken(
        token="token-123",
        client_id=oauth_settings.client_id,
        scopes=["user"],
        created_at=created_at,
        expires_at=int(time.time()) + 3600,
        resource="http://example.com/resource",
    )

    response = await async_client.post(
        "/auth/oauth/introspect",
        data={
            "client_id": oauth_settings.client_id,
            "client_secret": oauth_settings.client_secret.get_secret_value(),
            "token": "token-123",
        },
    )
    payload = response.json()

    assert payload["active"] is True
    assert payload["client_id"] == oauth_settings.client_id
    assert payload["scope"] == "user"
    assert payload["iat"] == created_at
    assert payload["token_type"] == BEARER
    assert payload["aud"] == "http://example.com/resource"


@pytest.mark.asyncio
async def test_introspect_active_access_token_with_list_audience(
    async_client,
    oauth_settings,
    oauth_plugin,
) -> None:
    provider = oauth_plugin._provider
    created_at = int(time.time()) - 5
    provider.tokens["token-aud-list"] = AccessToken(
        token="token-aud-list",
        client_id=oauth_settings.client_id,
        scopes=["openid", "profile"],
        created_at=created_at,
        expires_at=int(time.time()) + 3600,
        resource=["http://testserver/mcp", "http://testserver/auth/oauth/userinfo"],
    )

    response = await async_client.post(
        "/auth/oauth/introspect",
        data={
            "client_id": oauth_settings.client_id,
            "client_secret": oauth_settings.client_secret.get_secret_value(),
            "token": "token-aud-list",
        },
    )
    payload = response.json()

    assert payload["active"] is True
    assert payload["aud"] == ["http://testserver/mcp", "http://testserver/auth/oauth/userinfo"]


@pytest.mark.asyncio
async def test_introspect_accepts_basic_auth(
    async_client,
    oauth_settings,
    oauth_plugin,
    basic_auth_header,
) -> None:
    provider = oauth_plugin._provider
    provider.tokens["token-basic"] = AccessToken(
        token="token-basic",
        client_id=oauth_settings.client_id,
        scopes=["user"],
        created_at=int(time.time()) - 1,
        expires_at=int(time.time()) + 3600,
        resource=None,
    )

    response = await async_client.post(
        "/auth/oauth/introspect",
        data={"token": "token-basic"},
        headers={
            "authorization": basic_auth_header(
                oauth_settings.client_id,
                oauth_settings.client_secret.get_secret_value(),
            ),
        },
    )
    assert response.status_code == 200
    assert response.json()["active"] is True


@pytest.mark.asyncio
async def test_introspect_refresh_token_with_hint(
    async_client,
    oauth_settings,
    oauth_plugin,
) -> None:
    provider = oauth_plugin._provider
    created_at = int(time.time()) - 2
    provider.refresh_tokens["refresh-123"] = RefreshToken(
        token="refresh-123",
        client_id=oauth_settings.client_id,
        scopes=["user", "offline_access"],
        created_at=created_at,
        expires_at=int(time.time()) + 3600,
        resource="http://example.com/resource",
    )

    response = await async_client.post(
        "/auth/oauth/introspect",
        data={
            "client_id": oauth_settings.client_id,
            "client_secret": oauth_settings.client_secret.get_secret_value(),
            "token": "refresh-123",
            "token_type_hint": "refresh_token",
        },
    )
    payload = response.json()

    assert payload["active"] is True
    assert payload["client_id"] == oauth_settings.client_id
    assert payload["scope"] == "user offline_access"
    assert payload["token_type"] == "refresh_token"  # noqa: S105
    assert payload["iat"] == created_at
    assert payload["aud"] == "http://example.com/resource"


@pytest.mark.asyncio
async def test_introspect_token_type_hint_access_token_does_not_match_refresh(
    async_client,
    oauth_settings,
    oauth_plugin,
) -> None:
    provider = oauth_plugin._provider
    provider.refresh_tokens["refresh-only"] = RefreshToken(
        token="refresh-only",
        client_id=oauth_settings.client_id,
        scopes=["user"],
        created_at=int(time.time()) - 1,
        expires_at=int(time.time()) + 3600,
    )

    response = await async_client.post(
        "/auth/oauth/introspect",
        data={
            "client_id": oauth_settings.client_id,
            "client_secret": oauth_settings.client_secret.get_secret_value(),
            "token": "refresh-only",
            "token_type_hint": "access_token",
        },
    )
    assert response.status_code == 200
    assert response.json()["active"] is False


@pytest.mark.asyncio
async def test_introspect_rejects_unsupported_token_type_hint(
    async_client,
    oauth_settings,
) -> None:
    response = await async_client.post(
        "/auth/oauth/introspect",
        data={
            "client_id": oauth_settings.client_id,
            "client_secret": oauth_settings.client_secret.get_secret_value(),
            "token": "token-123",
            "token_type_hint": "id_token",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"


@pytest.mark.asyncio
async def test_introspect_inactive_for_mismatched_client(
    async_client,
    oauth_settings,
    oauth_plugin,
) -> None:
    provider = oauth_plugin._provider
    provider.clients["other-client"] = OAuthClientInformationFull(
        client_id="other-client",
        client_secret="other-secret",
        redirect_uris=oauth_settings.redirect_uris,
        scope=oauth_settings.default_scope,
    )
    provider.tokens["token-mismatch"] = AccessToken(
        token="token-mismatch",
        client_id=oauth_settings.client_id,
        scopes=["user"],
        created_at=int(time.time()) - 1,
        expires_at=int(time.time()) + 3600,
        resource=None,
    )

    response = await async_client.post(
        "/auth/oauth/introspect",
        data={
            "client_id": "other-client",
            "client_secret": "other-secret",
            "token": "token-mismatch",
        },
    )
    assert response.status_code == 200
    assert response.json()["active"] is False
