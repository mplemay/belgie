from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from belgie_oauth_server.models import OAuthClientInformationFull
from belgie_oauth_server.plugin import OAuthServerPlugin
from belgie_oauth_server.provider import AuthorizationParams
from belgie_oauth_server.settings import OAuthServerSettings
from belgie_oauth_server.utils import create_code_challenge

BEARER = "Bearer"


async def _create_authorization_code(
    oauth_plugin: OAuthServerPlugin,
    oauth_settings: OAuthServerSettings,
    code_verifier: str,
) -> str:
    provider = oauth_plugin._provider
    oauth_client = await provider.get_client(oauth_settings.client_id)
    params = AuthorizationParams(
        state="state-token",
        scopes=[oauth_settings.default_scope],
        code_challenge=create_code_challenge(code_verifier),
        redirect_uri=oauth_settings.redirect_uris[0],
        redirect_uri_provided_explicitly=True,
        resource=None,
    )
    await provider.authorize(oauth_client, params)
    redirect_url = await provider.issue_authorization_code("state-token")
    return parse_qs(urlparse(redirect_url).query)["code"][0]


@pytest.mark.asyncio
async def test_token_missing_grant_type(async_client: httpx.AsyncClient) -> None:
    response = await async_client.post("/auth/oauth/token", data={})
    assert response.status_code == 400
    assert response.json()["error"] == "unsupported_grant_type"


@pytest.mark.asyncio
async def test_token_missing_code(async_client: httpx.AsyncClient, oauth_settings: OAuthServerSettings) -> None:
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
async def test_token_invalid_client(async_client: httpx.AsyncClient) -> None:
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
async def test_token_client_id_mismatch(
    async_client: httpx.AsyncClient,
    oauth_settings: OAuthServerSettings,
    oauth_plugin: OAuthServerPlugin,
) -> None:
    oauth_plugin._provider.clients["other-client"] = OAuthClientInformationFull(
        client_id="other-client",
        client_secret=oauth_settings.client_secret.get_secret_value(),
        redirect_uris=oauth_settings.redirect_uris,
        scope=oauth_settings.default_scope,
    )
    code = await _create_authorization_code(oauth_plugin, oauth_settings, "verifier")
    response = await async_client.post(
        "/auth/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": "other-client",
            "client_secret": oauth_settings.client_secret.get_secret_value(),
            "code": code,
            "redirect_uri": str(oauth_settings.redirect_uris[0]),
            "code_verifier": "verifier",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


@pytest.mark.asyncio
async def test_token_invalid_client_secret(
    async_client: httpx.AsyncClient,
    oauth_settings: OAuthServerSettings,
    oauth_plugin: OAuthServerPlugin,
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
async def test_token_requires_redirect_uri_when_explicit(
    async_client: httpx.AsyncClient,
    oauth_settings: OAuthServerSettings,
    oauth_plugin: OAuthServerPlugin,
) -> None:
    code = await _create_authorization_code(oauth_plugin, oauth_settings, "verifier")
    response = await async_client.post(
        "/auth/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": oauth_settings.client_id,
            "client_secret": oauth_settings.client_secret.get_secret_value(),
            "code": code,
            "code_verifier": "verifier",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"


@pytest.mark.asyncio
async def test_token_missing_code_verifier(
    async_client: httpx.AsyncClient,
    oauth_settings: OAuthServerSettings,
    oauth_plugin: OAuthServerPlugin,
) -> None:
    code = await _create_authorization_code(oauth_plugin, oauth_settings, "verifier")
    response = await async_client.post(
        "/auth/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": oauth_settings.client_id,
            "client_secret": oauth_settings.client_secret.get_secret_value(),
            "code": code,
        },
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"


@pytest.mark.asyncio
async def test_token_invalid_code_verifier(
    async_client: httpx.AsyncClient,
    oauth_settings: OAuthServerSettings,
    oauth_plugin: OAuthServerPlugin,
) -> None:
    code = await _create_authorization_code(oauth_plugin, oauth_settings, "verifier")
    response = await async_client.post(
        "/auth/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": oauth_settings.client_id,
            "client_secret": oauth_settings.client_secret.get_secret_value(),
            "code": code,
            "redirect_uri": str(oauth_settings.redirect_uris[0]),
            "code_verifier": "wrong",
        },
    )
    assert response.status_code == 400
    assert response.json()["error"] == "invalid_grant"


@pytest.mark.asyncio
async def test_token_success(
    async_client: httpx.AsyncClient,
    oauth_settings: OAuthServerSettings,
    oauth_plugin: OAuthServerPlugin,
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
    assert "access_token" in payload
    assert payload["token_type"] == BEARER
    assert payload["scope"] == oauth_settings.default_scope
