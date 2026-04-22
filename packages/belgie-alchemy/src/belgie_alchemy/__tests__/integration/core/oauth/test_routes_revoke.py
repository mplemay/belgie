from __future__ import annotations

import time

import pytest


@pytest.mark.asyncio
async def test_revoke_requires_client_auth(async_client) -> None:
    response = await async_client.post("/auth/oauth2/revoke", data={"token": "token-123"})
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_client"


@pytest.mark.asyncio
async def test_revoke_missing_token(
    async_client,
    oauth_settings,
) -> None:
    response = await async_client.post(
        "/auth/oauth2/revoke",
        data={
            "client_id": "test-client",
            "client_secret": "test-secret",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"


@pytest.mark.asyncio
async def test_revoke_invalid_client_id(async_client) -> None:
    response = await async_client.post(
        "/auth/oauth2/revoke",
        data={
            "client_id": "wrong",
            "client_secret": "bad",
            "token": "token-123",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_client"


@pytest.mark.asyncio
async def test_revoke_invalid_client_secret(
    async_client,
    oauth_settings,
) -> None:
    response = await async_client.post(
        "/auth/oauth2/revoke",
        data={
            "client_id": "test-client",
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
    seed_access_token,
) -> None:
    await seed_access_token(
        token="token-123",
        client_id="test-client",
        scopes=list(oauth_settings.default_scopes),
        created_at=int(time.time()),
        expires_at=int(time.time()) + 3600,
        resource=None,
    )

    response = await async_client.post(
        "/auth/oauth2/revoke",
        data={
            "client_id": "test-client",
            "client_secret": "test-secret",
            "token": "token-123",
            "token_type_hint": "access_token",
        },
    )

    assert response.status_code == 200
    assert await oauth_plugin._provider.load_access_token("token-123") is None


@pytest.mark.asyncio
async def test_revoke_success_removes_refresh_token(
    async_client,
    oauth_settings,
    oauth_plugin,
    seed_refresh_token,
) -> None:
    await seed_refresh_token(
        token="refresh-123",
        client_id="test-client",
        scopes=[*oauth_settings.default_scopes, "offline_access"],
        created_at=int(time.time()),
        expires_at=int(time.time()) + 3600,
    )

    response = await async_client.post(
        "/auth/oauth2/revoke",
        data={
            "client_id": "test-client",
            "client_secret": "test-secret",
            "token": "refresh-123",
            "token_type_hint": "refresh_token",
        },
    )

    assert response.status_code == 200
    assert await oauth_plugin._provider.load_refresh_token("refresh-123") is None


@pytest.mark.asyncio
async def test_revoke_accepts_basic_auth(
    async_client,
    oauth_settings,
    oauth_plugin,
    seed_access_token,
    basic_auth_header,
) -> None:
    await seed_access_token(
        token="token-basic",
        client_id="test-client",
        scopes=list(oauth_settings.default_scopes),
        created_at=int(time.time()),
        expires_at=int(time.time()) + 3600,
        resource=None,
    )

    response = await async_client.post(
        "/auth/oauth2/revoke",
        data={"token": "token-basic"},
        headers={
            "authorization": basic_auth_header(
                "test-client",
                "test-secret",
            ),
        },
    )

    assert response.status_code == 200
    assert await oauth_plugin._provider.load_access_token("token-basic") is None


@pytest.mark.asyncio
async def test_revoke_unknown_token_returns_success(
    async_client,
    oauth_settings,
) -> None:
    response = await async_client.post(
        "/auth/oauth2/revoke",
        data={
            "client_id": "test-client",
            "client_secret": "test-secret",
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
    seed_access_token,
    seed_client,
) -> None:
    await seed_client(
        client_id="other-client",
        redirect_uris=["http://localhost/callback"],
        scope=" ".join(oauth_settings.default_scopes),
        client_secret_hash=oauth_plugin._provider._hash_value("other-secret"),
    )
    await seed_access_token(
        token="foreign-token",
        client_id="other-client",
        scopes=["user"],
        created_at=int(time.time()),
        expires_at=int(time.time()) + 3600,
        resource=None,
    )

    response = await async_client.post(
        "/auth/oauth2/revoke",
        data={
            "client_id": "test-client",
            "client_secret": "test-secret",
            "token": "foreign-token",
        },
    )

    assert response.status_code == 200
    assert await oauth_plugin._provider.load_access_token("foreign-token") is not None


@pytest.mark.asyncio
async def test_revoke_rejects_unsupported_token_type_hint(
    async_client,
    oauth_settings,
) -> None:
    response = await async_client.post(
        "/auth/oauth2/revoke",
        data={
            "client_id": "test-client",
            "client_secret": "test-secret",
            "token": "token-123",
            "token_type_hint": "id_token",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"


@pytest.mark.asyncio
async def test_revoke_public_client_cannot_authenticate(
    async_client,
    seed_client,
) -> None:
    await seed_client(
        client_id="public-client",
        redirect_uris=["http://localhost/callback"],
        scope="user",
        token_endpoint_auth_method="none",
    )

    response = await async_client.post(
        "/auth/oauth2/revoke",
        data={
            "client_id": "public-client",
            "token": "missing",
        },
    )

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_client"
