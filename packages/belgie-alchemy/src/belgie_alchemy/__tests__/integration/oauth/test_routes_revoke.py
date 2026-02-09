from __future__ import annotations

import base64
import time

import pytest
from belgie_oauth_server.models import OAuthClientInformationFull
from belgie_oauth_server.provider import AccessToken, RefreshToken


def _basic_auth(client_id: str, client_secret: str) -> str:
    raw = f"{client_id}:{client_secret}".encode()
    return f"Basic {base64.b64encode(raw).decode('utf-8')}"


@pytest.mark.asyncio
async def test_revoke_requires_client_auth(async_client) -> None:
    response = await async_client.post("/auth/oauth/revoke", data={"token": "token-123"})
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_client"


@pytest.mark.asyncio
async def test_revoke_missing_token(
    async_client,
    oauth_settings,
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
async def test_revoke_invalid_client_id(async_client) -> None:
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
    async_client,
    oauth_settings,
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
async def test_revoke_success_removes_access_token(
    async_client,
    oauth_settings,
    oauth_plugin,
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
            "token_type_hint": "access_token",
        },
    )

    assert response.status_code == 200
    assert "token-123" not in provider.tokens


@pytest.mark.asyncio
async def test_revoke_success_removes_refresh_token(
    async_client,
    oauth_settings,
    oauth_plugin,
) -> None:
    provider = oauth_plugin._provider
    provider.refresh_tokens["refresh-123"] = RefreshToken(
        token="refresh-123",
        client_id=oauth_settings.client_id,
        scopes=[oauth_settings.default_scope, "offline_access"],
        created_at=int(time.time()),
        expires_at=int(time.time()) + 3600,
    )

    response = await async_client.post(
        "/auth/oauth/revoke",
        data={
            "client_id": oauth_settings.client_id,
            "client_secret": oauth_settings.client_secret.get_secret_value(),
            "token": "refresh-123",
            "token_type_hint": "refresh_token",
        },
    )

    assert response.status_code == 200
    assert "refresh-123" not in provider.refresh_tokens


@pytest.mark.asyncio
async def test_revoke_accepts_basic_auth(
    async_client,
    oauth_settings,
    oauth_plugin,
) -> None:
    provider = oauth_plugin._provider
    provider.tokens["token-basic"] = AccessToken(
        token="token-basic",
        client_id=oauth_settings.client_id,
        scopes=[oauth_settings.default_scope],
        created_at=int(time.time()),
        expires_at=int(time.time()) + 3600,
        resource=None,
    )

    response = await async_client.post(
        "/auth/oauth/revoke",
        data={"token": "token-basic"},
        headers={
            "authorization": _basic_auth(
                oauth_settings.client_id,
                oauth_settings.client_secret.get_secret_value(),
            ),
        },
    )

    assert response.status_code == 200
    assert "token-basic" not in provider.tokens


@pytest.mark.asyncio
async def test_revoke_unknown_token_returns_success(
    async_client,
    oauth_settings,
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
async def test_revoke_ignores_tokens_owned_by_another_client(
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
    provider.tokens["foreign-token"] = AccessToken(
        token="foreign-token",
        client_id="other-client",
        scopes=["user"],
        created_at=int(time.time()),
        expires_at=int(time.time()) + 3600,
        resource=None,
    )

    response = await async_client.post(
        "/auth/oauth/revoke",
        data={
            "client_id": oauth_settings.client_id,
            "client_secret": oauth_settings.client_secret.get_secret_value(),
            "token": "foreign-token",
        },
    )

    assert response.status_code == 200
    assert "foreign-token" in provider.tokens


@pytest.mark.asyncio
async def test_revoke_rejects_unsupported_token_type_hint(
    async_client,
    oauth_settings,
) -> None:
    response = await async_client.post(
        "/auth/oauth/revoke",
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
async def test_revoke_public_client_cannot_authenticate(
    async_client,
    oauth_plugin,
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

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_client"
