from __future__ import annotations

import pytest


async def _create_user(belgie_instance, db_session, email: str):
    return await belgie_instance.adapter.create_user(
        db_session,
        email=email,
        name="Jane Doe",
        image="https://example.com/avatar.png",
        email_verified=True,
    )


@pytest.mark.asyncio
async def test_userinfo_requires_bearer_token(async_client) -> None:
    response = await async_client.get("/auth/oauth/userinfo")

    assert response.status_code == 401
    assert response.json()["error"] == "invalid_token"


@pytest.mark.asyncio
async def test_userinfo_rejects_token_without_openid_scope(
    async_client,
    oauth_plugin,
    oauth_settings,
    belgie_instance,
    db_session,
) -> None:
    user = await _create_user(belgie_instance, db_session, "userinfo-no-openid@test.com")
    access_token = oauth_plugin._provider._issue_access_token(
        client_id=oauth_settings.client_id,
        scopes=[oauth_settings.default_scope],
        user_id=str(user.id),
    )

    response = await async_client.get(
        "/auth/oauth/userinfo",
        headers={"authorization": f"Bearer {access_token.token}"},
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_scope"


@pytest.mark.asyncio
async def test_userinfo_rejects_token_without_user_binding(
    async_client,
    oauth_plugin,
    oauth_settings,
) -> None:
    access_token = oauth_plugin._provider._issue_access_token(
        client_id=oauth_settings.client_id,
        scopes=["openid"],
    )

    response = await async_client.get(
        "/auth/oauth/userinfo",
        headers={"authorization": f"Bearer {access_token.token}"},
    )

    assert response.status_code == 400
    assert response.json()["error"] == "invalid_request"


@pytest.mark.asyncio
async def test_userinfo_filters_claims_by_scope(
    async_client,
    oauth_plugin,
    oauth_settings,
    belgie_instance,
    db_session,
) -> None:
    user = await _create_user(belgie_instance, db_session, "userinfo-claims@test.com")

    profile_token = oauth_plugin._provider._issue_access_token(
        client_id=oauth_settings.client_id,
        scopes=["openid", "profile"],
        user_id=str(user.id),
    )
    profile_response = await async_client.get(
        "/auth/oauth/userinfo",
        headers={"authorization": f"Bearer {profile_token.token}"},
    )

    assert profile_response.status_code == 200
    profile_payload = profile_response.json()
    assert profile_payload["sub"] == str(user.id)
    assert profile_payload["name"] == "Jane Doe"
    assert profile_payload["picture"] == "https://example.com/avatar.png"
    assert profile_payload["given_name"] == "Jane"
    assert profile_payload["family_name"] == "Doe"
    assert "email" not in profile_payload

    email_token = oauth_plugin._provider._issue_access_token(
        client_id=oauth_settings.client_id,
        scopes=["openid", "email"],
        user_id=str(user.id),
    )
    email_response = await async_client.get(
        "/auth/oauth/userinfo",
        headers={"authorization": f"Bearer {email_token.token}"},
    )

    assert email_response.status_code == 200
    email_payload = email_response.json()
    assert email_payload["sub"] == str(user.id)
    assert email_payload["email"] == "userinfo-claims@test.com"
    assert email_payload["email_verified"] is True
    assert "name" not in email_payload
