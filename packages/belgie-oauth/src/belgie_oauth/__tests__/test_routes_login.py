from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from belgie_core.core.belgie import Belgie
from belgie_oauth.settings import OAuthSettings
from belgie_oauth.utils import create_code_challenge
from sqlalchemy.ext.asyncio import AsyncSession


async def _authorize(async_client: httpx.AsyncClient, oauth_settings: OAuthSettings, state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": oauth_settings.client_id,
        "redirect_uri": str(oauth_settings.redirect_uris[0]),
        "code_challenge": create_code_challenge("verifier"),
        "state": state,
    }
    response = await async_client.get("/auth/oauth/authorize", params=params, follow_redirects=False)
    return response.headers["location"]


@pytest.mark.asyncio
async def test_login_page_requires_state(async_client: httpx.AsyncClient) -> None:
    response = await async_client.get("/auth/oauth/login")
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_login_page_renders_form(async_client: httpx.AsyncClient) -> None:
    response = await async_client.get("/auth/oauth/login", params={"state": "state-123"})
    assert response.status_code == 200
    assert "Belgie Demo Authentication" in response.text
    assert "state-123" in response.text


@pytest.mark.asyncio
async def test_login_callback_rejects_invalid_credentials(
    async_client: httpx.AsyncClient,
    oauth_settings: OAuthSettings,
) -> None:
    await _authorize(async_client, oauth_settings, state="state-bad")

    response = await async_client.post(
        "/auth/oauth/login/callback",
        data={"username": "wrong", "password": "bad", "state": "state-bad"},
        follow_redirects=False,
    )

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_login_callback_creates_user_and_session(
    async_client: httpx.AsyncClient,
    belgie_instance: Belgie,
    db_session: AsyncSession,
    oauth_settings: OAuthSettings,
    demo_username: str,
    demo_password: str,
) -> None:
    await _authorize(async_client, oauth_settings, state="state-good")

    response = await async_client.post(
        "/auth/oauth/login/callback",
        data={
            "username": demo_username,
            "password": demo_password,
            "state": "state-good",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert belgie_instance.settings.cookie.name in response.cookies

    location = response.headers["location"]
    query = parse_qs(urlparse(location).query)
    assert "code" in query

    user = await belgie_instance.adapter.get_user_by_email(db_session, demo_username)
    assert user is not None
