from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from belgie_core.core.belgie import Belgie
from belgie_oauth_server.settings import OAuthServerSettings
from belgie_oauth_server.utils import create_code_challenge
from sqlalchemy.ext.asyncio import AsyncSession


async def _create_user_session(belgie: Belgie, db_session: AsyncSession, email: str) -> str:
    user = await belgie.adapter.create_user(db_session, email=email)
    session = await belgie.session_manager.create_session(db_session, user_id=user.id)
    return str(session.id)


@pytest.mark.asyncio
async def test_full_oauth_flow(
    async_client: httpx.AsyncClient,
    belgie_instance: Belgie,
    db_session: AsyncSession,
    oauth_settings: OAuthServerSettings,
) -> None:
    session_id = await _create_user_session(belgie_instance, db_session, "user@test.com")
    async_client.cookies.set(belgie_instance.settings.cookie.name, session_id)

    code_verifier = "verifier"
    code_challenge = create_code_challenge(code_verifier)

    authorize_response = await async_client.get(
        "/auth/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": oauth_settings.client_id,
            "redirect_uri": str(oauth_settings.redirect_uris[0]),
            "code_challenge": code_challenge,
            "state": "flow-state",
        },
        follow_redirects=False,
    )

    assert authorize_response.status_code == 302
    redirect_location = authorize_response.headers["location"]
    code = parse_qs(urlparse(redirect_location).query)["code"][0]

    token_response = await async_client.post(
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

    assert token_response.status_code == 200
    token_payload = token_response.json()
    access_token = token_payload["access_token"]

    introspect_response = await async_client.post(
        "/auth/oauth/introspect",
        data={
            "client_id": oauth_settings.client_id,
            "client_secret": oauth_settings.client_secret.get_secret_value(),
            "token": access_token,
        },
    )

    assert introspect_response.status_code == 200
    assert introspect_response.json()["active"] is True
