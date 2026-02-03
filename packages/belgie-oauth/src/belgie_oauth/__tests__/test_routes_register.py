import httpx
import pytest
from belgie_oauth.plugin import OAuthPlugin


@pytest.mark.asyncio
async def test_register_success(async_client: httpx.AsyncClient, oauth_plugin: OAuthPlugin) -> None:
    response = await async_client.post(
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
    assert payload["client_name"] == "Demo"
    assert payload["redirect_uris"] == ["http://testserver/callback"]
    assert payload["client_id"] in oauth_plugin._provider.clients


@pytest.mark.asyncio
async def test_register_token_endpoint_auth_method_none(async_client: httpx.AsyncClient) -> None:
    response = await async_client.post(
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
async def test_register_missing_redirect_uris(async_client: httpx.AsyncClient) -> None:
    response = await async_client.post("/auth/oauth/register", json={})

    assert response.status_code == 400
    payload = response.json()
    assert payload["error"] == "invalid_request"
    assert "redirect_uris" in payload["error_description"]


@pytest.mark.asyncio
async def test_register_rejects_unsupported_auth_method(async_client: httpx.AsyncClient) -> None:
    response = await async_client.post(
        "/auth/oauth/register",
        json={
            "redirect_uris": ["http://testserver/callback"],
            "token_endpoint_auth_method": "private_key_jwt",
        },
    )

    assert response.status_code == 400
    payload = response.json()
    assert payload["error"] == "invalid_request"
    assert "token_endpoint_auth_method" in payload["error_description"]
