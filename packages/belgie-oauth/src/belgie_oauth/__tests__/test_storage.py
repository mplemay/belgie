from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from belgie_oauth.storage.memory import InMemoryOAuthStore


@pytest.mark.asyncio
async def test_in_memory_oauth_store_crud() -> None:
    store = InMemoryOAuthStore()

    created_client = await store.create_oauth_client(
        None,
        {
            "client_id": "client",
            "redirect_uris": ["https://example.com/callback"],
        },
    )
    assert created_client.client_id == "client"

    fetched = await store.get_oauth_client(None, "client")
    assert fetched is not None

    updated = await store.update_oauth_client(None, "client", {"name": "Test"})
    assert updated is not None
    assert updated.name == "Test"

    listed = await store.list_oauth_clients(None)
    assert len(listed) == 1

    deleted = await store.delete_oauth_client(None, "client")
    assert deleted is True


@pytest.mark.asyncio
async def test_in_memory_oauth_store_tokens() -> None:
    store = InMemoryOAuthStore()
    user_id = UUID("00000000-0000-0000-0000-000000000001")
    session_id = UUID("00000000-0000-0000-0000-000000000002")
    expires_at = datetime.now(UTC) + timedelta(minutes=5)

    await store.create_oauth_client(
        None,
        {
            "client_id": "client",
            "redirect_uris": ["https://example.com/callback"],
            "user_id": user_id,
        },
    )

    code = await store.create_oauth_authorization_code(
        None,
        {
            "code": "code",
            "client_id": "client",
            "redirect_uri": "https://example.com/callback",
            "redirect_uri_provided_explicitly": True,
            "code_challenge": "challenge",
            "scopes": ["openid"],
            "user_id": user_id,
            "session_id": session_id,
            "expires_at": expires_at,
        },
    )
    assert await store.get_oauth_authorization_code(None, code.code) is not None
    assert await store.delete_oauth_authorization_code(None, code.code) is True

    access = await store.create_oauth_access_token(
        None,
        {
            "token": "access",
            "client_id": "client",
            "session_id": session_id,
            "user_id": user_id,
            "scopes": ["openid"],
            "expires_at": expires_at,
        },
    )
    assert await store.get_oauth_access_token(None, access.token) is not None
    assert await store.delete_oauth_access_token(None, access.token) is True

    refresh = await store.create_oauth_refresh_token(
        None,
        {
            "token": "refresh",
            "client_id": "client",
            "session_id": session_id,
            "user_id": user_id,
            "scopes": ["openid"],
            "expires_at": expires_at,
        },
    )
    assert await store.get_oauth_refresh_token(None, refresh.token) is not None
    assert await store.revoke_oauth_refresh_token(None, refresh.id) is True
    deleted = await store.delete_oauth_refresh_tokens_for_user_client(
        None,
        user_id=user_id,
        client_id="client",
    )
    assert deleted == 1

    consent = await store.create_oauth_consent(
        None,
        {
            "client_id": "client",
            "user_id": user_id,
            "scopes": ["openid"],
        },
    )
    assert await store.get_oauth_consent(None, consent.id) is not None
    assert len(await store.list_oauth_consents(None, user_id=user_id)) == 1
    updated = await store.update_oauth_consent(None, consent.id, {"scopes": ["openid", "profile"]})
    assert updated is not None
    assert updated.scopes == ["openid", "profile"]
    assert await store.delete_oauth_consent(None, consent.id) is True
