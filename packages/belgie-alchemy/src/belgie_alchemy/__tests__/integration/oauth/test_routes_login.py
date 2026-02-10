from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from belgie_core.core.belgie import Belgie
from sqlalchemy.ext.asyncio import AsyncSession


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
    assert parsed.path == "/login/google"
    assert query["return_to"][0] == "http://testserver/auth/oauth/login/callback?state=state-123"


@pytest.mark.asyncio
async def test_login_callback_requires_session(async_client: httpx.AsyncClient) -> None:
    response = await async_client.get(
        "/auth/oauth/login/callback",
        params={"state": "state-123"},
    )

    assert response.status_code == 401
    assert response.json()["detail"] == "login_required"


@pytest.mark.asyncio
async def test_login_callback_rejects_invalid_state(
    async_client: httpx.AsyncClient,
    belgie_instance: Belgie,
    db_session: AsyncSession,
    create_user_session,
) -> None:
    session_id = await create_user_session(belgie_instance, db_session, "user@test.com")
    async_client.cookies.set(belgie_instance.settings.cookie.name, session_id)

    response = await async_client.get(
        "/auth/oauth/login/callback",
        params={"state": "bad-state"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Invalid state parameter"
