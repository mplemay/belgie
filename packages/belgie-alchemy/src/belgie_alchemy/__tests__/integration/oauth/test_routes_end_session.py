from __future__ import annotations

from urllib.parse import parse_qs, urlparse
from uuid import UUID

import pytest
from belgie_oauth_server.utils import create_code_challenge


async def _create_user_session(belgie_instance, db_session, email: str) -> str:
    user = await belgie_instance.adapter.create_user(db_session, email=email)
    session = await belgie_instance.session_manager.create_session(db_session, user_id=user.id)
    return str(session.id)


async def _issue_id_token(
    async_client,
    oauth_settings,
    oauth_plugin,
    belgie_instance,
    db_session,
    *,
    email: str,
    enable_end_session: bool,
    post_logout_redirect_uris: list[str] | None = None,
) -> tuple[str, str]:
    session_id = await _create_user_session(belgie_instance, db_session, email)
    async_client.cookies.set(belgie_instance.settings.cookie.name, session_id)

    oauth_client = oauth_plugin._provider.clients[oauth_settings.client_id]
    oauth_client.scope = "openid profile email"
    oauth_client.enable_end_session = enable_end_session
    oauth_client.post_logout_redirect_uris = post_logout_redirect_uris

    code_verifier = "end-session-verifier"
    authorize_response = await async_client.get(
        "/auth/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": oauth_settings.client_id,
            "redirect_uri": str(oauth_settings.redirect_uris[0]),
            "code_challenge": create_code_challenge(code_verifier),
            "scope": "openid profile email",
            "state": "end-session-state",
        },
        follow_redirects=False,
    )
    code = parse_qs(urlparse(authorize_response.headers["location"]).query)["code"][0]

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
    id_token = token_response.json().get("id_token")
    assert id_token is not None
    return id_token, session_id


@pytest.mark.asyncio
async def test_end_session_rejects_invalid_id_token(async_client) -> None:
    response = await async_client.get(
        "/auth/oauth/end-session",
        params={"id_token_hint": "not-a-jwt"},
    )

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_token"


@pytest.mark.asyncio
async def test_end_session_rejects_clients_without_permission(
    async_client,
    oauth_settings,
    oauth_plugin,
    belgie_instance,
    db_session,
) -> None:
    id_token, _session_id = await _issue_id_token(
        async_client,
        oauth_settings,
        oauth_plugin,
        belgie_instance,
        db_session,
        email="end-session-disabled@test.com",
        enable_end_session=False,
    )

    response = await async_client.get(
        "/auth/oauth/end-session",
        params={"id_token_hint": id_token},
    )

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_client"


@pytest.mark.asyncio
async def test_end_session_signs_out_session_and_redirects(
    async_client,
    oauth_settings,
    oauth_plugin,
    belgie_instance,
    db_session,
) -> None:
    redirect_uri = "http://testserver/logout-complete"
    id_token, session_id = await _issue_id_token(
        async_client,
        oauth_settings,
        oauth_plugin,
        belgie_instance,
        db_session,
        email="end-session-success@test.com",
        enable_end_session=True,
        post_logout_redirect_uris=[redirect_uri],
    )

    response = await async_client.get(
        "/auth/oauth/end-session",
        params={
            "id_token_hint": id_token,
            "post_logout_redirect_uri": redirect_uri,
            "state": "goodbye",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "http://testserver/logout-complete?state=goodbye"
    deleted_session = await belgie_instance.session_manager.get_session(db_session, UUID(session_id))
    assert deleted_session is None


@pytest.mark.asyncio
async def test_end_session_returns_empty_object_for_invalid_redirect_uri(
    async_client,
    oauth_settings,
    oauth_plugin,
    belgie_instance,
    db_session,
) -> None:
    id_token, session_id = await _issue_id_token(
        async_client,
        oauth_settings,
        oauth_plugin,
        belgie_instance,
        db_session,
        email="end-session-invalid-redirect@test.com",
        enable_end_session=True,
        post_logout_redirect_uris=["http://testserver/logout-complete"],
    )

    response = await async_client.get(
        "/auth/oauth/end-session",
        params={
            "id_token_hint": id_token,
            "post_logout_redirect_uri": "http://testserver/not-allowed",
        },
        follow_redirects=False,
    )

    assert response.status_code == 200
    assert response.json() == {}
    deleted_session = await belgie_instance.session_manager.get_session(db_session, UUID(session_id))
    assert deleted_session is None
