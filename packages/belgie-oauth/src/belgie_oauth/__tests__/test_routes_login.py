from urllib.parse import parse_qs, urlparse

import httpx
import pytest


@pytest.mark.asyncio
async def test_login_missing_state_returns_400(async_client: httpx.AsyncClient) -> None:
    response = await async_client.get("/auth/oauth/login")

    assert response.status_code == 400
    assert response.json()["detail"] == "missing state"


@pytest.mark.asyncio
async def test_login_redirects_to_configured_login_url(async_client: httpx.AsyncClient) -> None:
    response = await async_client.get(
        "/auth/oauth/login",
        params={"state": "state-123"},
        follow_redirects=False,
    )

    assert response.status_code == 302
    location = response.headers["location"]
    parsed = urlparse(location)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "http"
    assert parsed.netloc == "testserver"
    assert parsed.path == "/auth/provider/google/signin"
    assert query["return_to"][0] == "http://testserver/auth/oauth/login/callback?state=state-123"


@pytest.mark.asyncio
async def test_login_callback_requires_session(async_client: httpx.AsyncClient) -> None:
    response = await async_client.get(
        "/auth/oauth/login/callback",
        params={"state": "state-123"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "login_required"
