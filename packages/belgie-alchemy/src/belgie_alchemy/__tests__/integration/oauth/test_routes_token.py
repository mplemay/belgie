from __future__ import annotations

import base64
from urllib.parse import parse_qs, urlparse

import pytest
from belgie_oauth_server.models import OAuthClientInformationFull
from belgie_oauth_server.provider import AuthorizationParams
from belgie_oauth_server.utils import create_code_challenge

BEARER = "Bearer"


def _basic_auth(client_id: str, client_secret: str) -> str:
    raw = f"{client_id}:{client_secret}".encode()
    return f"Basic {base64.b64encode(raw).decode('utf-8')}"


async def _create_authorization_code(
    oauth_plugin,
    oauth_settings,
    code_verifier: str,
    *,
    scopes: list[str] | None = None,
) -> str:
    provider = oauth_plugin._provider
    oauth_client = await provider.get_client(oauth_settings.client_id)
    params = AuthorizationParams(
        state="state-token",
        scopes=scopes or [oauth_settings.default_scope],
        code_challenge=create_code_challenge(code_verifier),
        redirect_uri=oauth_settings.redirect_uris[0],
        redirect_uri_provided_explicitly=True,
        resource=None,
    )
    await provider.authorize(oauth_client, params)
    redirect_url = await provider.issue_authorization_code("state-token")
    return parse_qs(urlparse(redirect_url).query)["code"][0]


async def _create_refresh_token(
    async_client,
    oauth_settings,
    oauth_plugin,
) -> str:
    oauth_plugin._provider.clients[oauth_settings.client_id].scope = f"{oauth_settings.default_scope} offline_access"
    code_verifier = "refresh-verifier"
    code = await _create_authorization_code(
        oauth_plugin,
        oauth_settings,
        code_verifier,
        scopes=[oauth_settings.default_scope, "offline_access"],
    )
    response = await async_client.post(
        "/auth/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": oauth_settings.client_id,
            "client_secret": oauth_settings.client_secret.get_secret_value(),
            "code": code,
            "redirect_uri": str(oauth_settings.redirect_uris[0]),
            "code_verifier": code_verifier,
        },
    )
    assert response.status_code == 200
    return response.json()["refresh_token"]


@pytest.mark.asyncio
async def test_token_missing_grant_type(async_client) -> None:
    response = await async_client.post("/auth/oauth/token", data={})
    assert response.status_code == 400
    assert response.json()["error"] == "unsupported_grant_type"


@pytest.mark.asyncio
async def test_token_unsupported_grant_type(async_client) -> None:
    response = await async_client.post("/auth/oauth/token", data={"grant_type": "urn:custom"})
    assert response.status_code == 400
    assert response.json()["error"] == "unsupported_grant_type"


@pytest.mark.asyncio
async def test_token_authorization_code_missing_code(
    async_client,
    oauth_settings,
) -> None:
    response = await async_client.post(
        "/auth/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": oauth_settings.client_id,
            "client_secret": oauth_settings.client_secret.get_secret_value(),
        },
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"


@pytest.mark.asyncio
async def test_token_authorization_code_invalid_client(async_client) -> None:
    response = await async_client.post(
        "/auth/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": "wrong",
            "client_secret": "bad",
            "code": "nope",
            "code_verifier": "verifier",
        },
    )
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_client"


@pytest.mark.asyncio
async def test_token_authorization_code_invalid_client_secret(
    async_client,
    oauth_settings,
    oauth_plugin,
) -> None:
    code = await _create_authorization_code(oauth_plugin, oauth_settings, "verifier")
    response = await async_client.post(
        "/auth/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": oauth_settings.client_id,
            "client_secret": "wrong",
            "code": code,
            "code_verifier": "verifier",
        },
    )
    assert response.status_code == 401
    assert response.json()["error"] == "invalid_client"


@pytest.mark.asyncio
async def test_token_authorization_code_success_no_offline_access(
    async_client,
    oauth_settings,
    oauth_plugin,
) -> None:
    code_verifier = "verifier"
    code = await _create_authorization_code(oauth_plugin, oauth_settings, code_verifier)

    response = await async_client.post(
        "/auth/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": oauth_settings.client_id,
            "client_secret": oauth_settings.client_secret.get_secret_value(),
            "code": code,
            "redirect_uri": str(oauth_settings.redirect_uris[0]),
            "code_verifier": code_verifier,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["token_type"] == BEARER
    assert payload["scope"] == oauth_settings.default_scope
    assert payload.get("refresh_token") is None


@pytest.mark.asyncio
async def test_token_authorization_code_success_with_offline_access_issues_refresh(
    async_client,
    oauth_settings,
    oauth_plugin,
) -> None:
    code_verifier = "offline-verifier"
    code = await _create_authorization_code(
        oauth_plugin,
        oauth_settings,
        code_verifier,
        scopes=[oauth_settings.default_scope, "offline_access"],
    )

    response = await async_client.post(
        "/auth/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": oauth_settings.client_id,
            "client_secret": oauth_settings.client_secret.get_secret_value(),
            "code": code,
            "redirect_uri": str(oauth_settings.redirect_uris[0]),
            "code_verifier": code_verifier,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["refresh_token"] is not None
    assert payload["scope"] == f"{oauth_settings.default_scope} offline_access"


@pytest.mark.asyncio
async def test_token_authorization_code_accepts_basic_auth(
    async_client,
    oauth_settings,
    oauth_plugin,
) -> None:
    code_verifier = "basic-verifier"
    code = await _create_authorization_code(oauth_plugin, oauth_settings, code_verifier)
    auth_header = _basic_auth(oauth_settings.client_id, oauth_settings.client_secret.get_secret_value())

    response = await async_client.post(
        "/auth/oauth/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": str(oauth_settings.redirect_uris[0]),
            "code_verifier": code_verifier,
        },
        headers={"authorization": auth_header},
    )

    assert response.status_code == 200
    assert response.json()["token_type"] == BEARER


@pytest.mark.asyncio
async def test_token_refresh_token_success_rotates_and_narrows_scope(
    async_client,
    oauth_settings,
    oauth_plugin,
) -> None:
    old_refresh_token = await _create_refresh_token(async_client, oauth_settings, oauth_plugin)

    response = await async_client.post(
        "/auth/oauth/token",
        data={
            "grant_type": "refresh_token",
            "client_id": oauth_settings.client_id,
            "client_secret": oauth_settings.client_secret.get_secret_value(),
            "refresh_token": old_refresh_token,
            "scope": oauth_settings.default_scope,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["scope"] == oauth_settings.default_scope
    assert payload["refresh_token"] is not None
    assert payload["refresh_token"] != old_refresh_token

    old_refresh_response = await async_client.post(
        "/auth/oauth/token",
        data={
            "grant_type": "refresh_token",
            "client_id": oauth_settings.client_id,
            "client_secret": oauth_settings.client_secret.get_secret_value(),
            "refresh_token": old_refresh_token,
        },
    )
    assert old_refresh_response.status_code == 400
    assert old_refresh_response.json()["error"] == "invalid_grant"


@pytest.mark.asyncio
async def test_token_refresh_token_rejects_scope_escalation(
    async_client,
    oauth_settings,
    oauth_plugin,
) -> None:
    refresh_token = await _create_refresh_token(async_client, oauth_settings, oauth_plugin)
    response = await async_client.post(
        "/auth/oauth/token",
        data={
            "grant_type": "refresh_token",
            "client_id": oauth_settings.client_id,
            "client_secret": oauth_settings.client_secret.get_secret_value(),
            "refresh_token": refresh_token,
            "scope": "admin",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_scope"


@pytest.mark.asyncio
async def test_token_client_credentials_success_post_auth(
    async_client,
    oauth_settings,
) -> None:
    response = await async_client.post(
        "/auth/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": oauth_settings.client_id,
            "client_secret": oauth_settings.client_secret.get_secret_value(),
            "scope": oauth_settings.default_scope,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["token_type"] == BEARER
    assert payload["scope"] == oauth_settings.default_scope
    assert payload.get("refresh_token") is None


@pytest.mark.asyncio
async def test_token_client_credentials_success_basic_auth(
    async_client,
    oauth_settings,
) -> None:
    auth_header = _basic_auth(oauth_settings.client_id, oauth_settings.client_secret.get_secret_value())

    response = await async_client.post(
        "/auth/oauth/token",
        data={
            "grant_type": "client_credentials",
            "scope": oauth_settings.default_scope,
        },
        headers={"authorization": auth_header},
    )

    assert response.status_code == 200
    assert response.json()["token_type"] == BEARER


@pytest.mark.asyncio
async def test_token_client_credentials_rejects_unknown_scope(
    async_client,
    oauth_settings,
) -> None:
    response = await async_client.post(
        "/auth/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": oauth_settings.client_id,
            "client_secret": oauth_settings.client_secret.get_secret_value(),
            "scope": "admin",
        },
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_scope"


@pytest.mark.asyncio
async def test_token_client_credentials_rejects_public_client(
    async_client,
    oauth_plugin,
) -> None:
    oauth_plugin._provider.clients["public-client"] = OAuthClientInformationFull(
        client_id="public-client",
        client_secret=None,
        redirect_uris=["http://testserver/callback"],
        scope="user",
        token_endpoint_auth_method="none",
    )

    response = await async_client.post(
        "/auth/oauth/token",
        data={
            "grant_type": "client_credentials",
            "client_id": "public-client",
        },
    )

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_client"
