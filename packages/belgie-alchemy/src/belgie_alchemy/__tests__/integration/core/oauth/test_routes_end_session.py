from __future__ import annotations

from urllib.parse import parse_qs, urlparse
from uuid import UUID

import pytest
from belgie_oauth_server.utils import create_code_challenge


async def _issue_id_token(
    async_client,
    oauth_settings,
    _oauth_plugin,
    belgie_instance,
    db_session,
    create_individual_session,
    update_static_client,
    *,
    email: str,
    enable_end_session: bool,
    post_logout_redirect_uris: list[str] | None = None,
) -> tuple[str, str]:
    session_id = await create_individual_session(belgie_instance, db_session, email)
    async_client.cookies.set(belgie_instance.settings.cookie.name, session_id)

    update_static_client(
        scope="openid profile email",
        enable_end_session=enable_end_session,
        post_logout_redirect_uris=post_logout_redirect_uris,
    )

    code_verifier = "end-session-verifier"
    authorize_response = await async_client.get(
        "/auth/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": oauth_settings.client_id,
            "redirect_uri": str(oauth_settings.redirect_uris[0]),
            "code_challenge": create_code_challenge(code_verifier),
            "code_challenge_method": "S256",
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
    create_individual_session,
    update_static_client,
) -> None:
    id_token, _session_id = await _issue_id_token(
        async_client,
        oauth_settings,
        oauth_plugin,
        belgie_instance,
        db_session,
        create_individual_session,
        update_static_client,
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
    create_individual_session,
    update_static_client,
) -> None:
    redirect_uri = "http://localhost/logout-complete"
    id_token, session_id = await _issue_id_token(
        async_client,
        oauth_settings,
        oauth_plugin,
        belgie_instance,
        db_session,
        create_individual_session,
        update_static_client,
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
    assert response.headers["location"] == "http://localhost/logout-complete?state=goodbye"
    deleted_session = await belgie_instance.session_manager.get_session(db_session, UUID(session_id))
    assert deleted_session is None


@pytest.mark.asyncio
async def test_end_session_returns_empty_object_for_invalid_redirect_uri(
    async_client,
    oauth_settings,
    oauth_plugin,
    belgie_instance,
    db_session,
    create_individual_session,
    update_static_client,
) -> None:
    id_token, session_id = await _issue_id_token(
        async_client,
        oauth_settings,
        oauth_plugin,
        belgie_instance,
        db_session,
        create_individual_session,
        update_static_client,
        email="end-session-invalid-redirect@test.com",
        enable_end_session=True,
        post_logout_redirect_uris=["http://localhost/logout-complete"],
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


@pytest.mark.asyncio
async def test_end_session_allows_public_client_when_id_token_hint_is_valid(
    async_client,
    belgie_instance,
    db_session,
    create_individual_session,
    seed_client,
) -> None:
    session_id = await create_individual_session(belgie_instance, db_session, "end-session-public@test.com")
    async_client.cookies.set(belgie_instance.settings.cookie.name, session_id)

    await seed_client(
        client_id="public-end-session",
        redirect_uris=["http://localhost/callback"],
        scope="openid profile email",
        token_endpoint_auth_method="none",
        enable_end_session=True,
        post_logout_redirect_uris=["http://localhost/logout-complete"],
    )

    code_verifier = "end-session-public-verifier"
    authorize_response = await async_client.get(
        "/auth/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": "public-end-session",
            "redirect_uri": "http://localhost/callback",
            "code_challenge": create_code_challenge(code_verifier),
            "code_challenge_method": "S256",
            "scope": "openid profile email",
            "state": "end-session-public-state",
        },
        follow_redirects=False,
    )
    code = parse_qs(urlparse(authorize_response.headers["location"]).query)["code"][0]

    token_response = await async_client.post(
        "/auth/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": "public-end-session",
            "code": code,
            "redirect_uri": "http://localhost/callback",
            "code_verifier": code_verifier,
        },
    )
    assert token_response.status_code == 200
    id_token = token_response.json().get("id_token")
    assert id_token is not None

    response = await async_client.get(
        "/auth/oauth/end-session",
        params={
            "id_token_hint": id_token,
            "post_logout_redirect_uri": "http://localhost/logout-complete",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert response.headers["location"] == "http://localhost/logout-complete"
    deleted_session = await belgie_instance.session_manager.get_session(db_session, UUID(session_id))
    assert deleted_session is None


@pytest.mark.asyncio
async def test_end_session_rejects_public_client_without_logout_permission(
    async_client,
    belgie_instance,
    db_session,
    create_individual_session,
    seed_client,
) -> None:
    session_id = await create_individual_session(belgie_instance, db_session, "end-session-public-disabled@test.com")
    async_client.cookies.set(belgie_instance.settings.cookie.name, session_id)

    await seed_client(
        client_id="public-end-session-disabled",
        redirect_uris=["http://localhost/callback"],
        scope="openid profile email",
        token_endpoint_auth_method="none",
        enable_end_session=False,
    )

    code_verifier = "end-session-public-disabled-verifier"
    authorize_response = await async_client.get(
        "/auth/oauth/authorize",
        params={
            "response_type": "code",
            "client_id": "public-end-session-disabled",
            "redirect_uri": "http://localhost/callback",
            "code_challenge": create_code_challenge(code_verifier),
            "code_challenge_method": "S256",
            "scope": "openid profile email",
            "state": "end-session-public-disabled-state",
        },
        follow_redirects=False,
    )
    code = parse_qs(urlparse(authorize_response.headers["location"]).query)["code"][0]

    token_response = await async_client.post(
        "/auth/oauth/token",
        data={
            "grant_type": "authorization_code",
            "client_id": "public-end-session-disabled",
            "code": code,
            "redirect_uri": "http://localhost/callback",
            "code_verifier": code_verifier,
        },
    )
    assert token_response.status_code == 200
    id_token = token_response.json().get("id_token")
    assert id_token is not None

    response = await async_client.get(
        "/auth/oauth/end-session",
        params={"id_token_hint": id_token},
    )

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_client"
    existing_session = await belgie_instance.session_manager.get_session(db_session, UUID(session_id))
    assert existing_session is not None
