from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from belgie_core.core.belgie import Belgie
from belgie_oauth.settings import OAuthSettings
from belgie_oauth.utils import create_code_challenge
from sqlalchemy.ext.asyncio import AsyncSession


async def _create_user_session(belgie: Belgie, db_session: AsyncSession, email: str) -> str:
    user = await belgie.adapter.create_user(db_session, email=email)
    session = await belgie.session_manager.create_session(db_session, user_id=user.id)
    return str(session.id)


def _authorize_params(oauth_settings: OAuthSettings, code_challenge: str, state: str | None = None) -> dict[str, str]:
    return {
        "response_type": "code",
        "client_id": oauth_settings.client_id,
        "redirect_uri": str(oauth_settings.redirect_uris[0]),
        "code_challenge": code_challenge,
        "state": state or "state-123",
    }


@pytest.mark.asyncio
async def test_authorize_redirects_to_login_when_unauthenticated(
    async_client: httpx.AsyncClient,
    oauth_settings: OAuthSettings,
) -> None:
    verifier = "verifier"
    params = _authorize_params(oauth_settings, create_code_challenge(verifier))
    response = await async_client.get("/auth/oauth/authorize", params=params, follow_redirects=False)

    assert response.status_code == 302
    location = response.headers["location"]
    assert location.startswith("http://testserver/auth/oauth/login")
    assert "state=" in location


@pytest.mark.asyncio
async def test_authorize_issues_code_when_authenticated(
    async_client: httpx.AsyncClient,
    belgie_instance: Belgie,
    db_session: AsyncSession,
    oauth_settings: OAuthSettings,
) -> None:
    session_id = await _create_user_session(belgie_instance, db_session, "user@test.com")
    async_client.cookies.set(belgie_instance.settings.cookie.name, session_id)

    params = _authorize_params(oauth_settings, create_code_challenge("verifier"), state="state-auth")
    response = await async_client.get("/auth/oauth/authorize", params=params, follow_redirects=False)

    assert response.status_code == 302
    location = response.headers["location"]
    parsed = urlparse(location)
    query = parse_qs(parsed.query)
    assert parsed.scheme == "http"
    assert parsed.netloc == "testserver"
    assert query["state"][0] == "state-auth"
    assert "code" in query
