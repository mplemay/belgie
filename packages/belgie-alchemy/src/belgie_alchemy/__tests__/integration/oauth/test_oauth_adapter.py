from datetime import UTC, datetime, timedelta

import pytest
from belgie_alchemy.__tests__.fixtures.models import Session, User
from belgie_alchemy.oauth_adapter import AlchemyOAuthAdapter
from belgie_alchemy.oauth_models import (
    OAuthAccessToken,
    OAuthAuthorizationCode,
    OAuthClient,
    OAuthConsent,
    OAuthRefreshToken,
)
from sqlalchemy.ext.asyncio import AsyncSession


@pytest.fixture
def oauth_adapter() -> AlchemyOAuthAdapter:
    return AlchemyOAuthAdapter(
        client=OAuthClient,
        authorization_code=OAuthAuthorizationCode,
        access_token=OAuthAccessToken,
        refresh_token=OAuthRefreshToken,
        consent=OAuthConsent,
    )


async def _create_user(alchemy_session: AsyncSession) -> User:
    user = User(email="oauth-adapter@example.com")
    alchemy_session.add(user)
    await alchemy_session.commit()
    await alchemy_session.refresh(user)
    return user


async def _create_session(alchemy_session: AsyncSession, user: User) -> Session:
    session = Session(
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    alchemy_session.add(session)
    await alchemy_session.commit()
    await alchemy_session.refresh(session)
    return session


@pytest.mark.asyncio
async def test_client_crud(oauth_adapter: AlchemyOAuthAdapter, alchemy_session: AsyncSession) -> None:
    user = await _create_user(alchemy_session)

    created = await oauth_adapter.create_oauth_client(
        alchemy_session,
        {
            "client_id": "client-1",
            "redirect_uris": ["https://app.local/callback"],
            "user_id": user.id,
        },
    )
    fetched = await oauth_adapter.get_oauth_client(alchemy_session, "client-1")
    assert fetched is not None
    assert fetched.client_id == created.client_id

    updated = await oauth_adapter.update_oauth_client(
        alchemy_session,
        "client-1",
        {"name": "Test Client"},
    )
    assert updated is not None
    assert updated.name == "Test Client"

    clients = await oauth_adapter.list_oauth_clients(alchemy_session, user_id=user.id)
    assert len(clients) == 1

    deleted = await oauth_adapter.delete_oauth_client(alchemy_session, "client-1")
    assert deleted is True


@pytest.mark.asyncio
async def test_authorization_code_crud(
    oauth_adapter: AlchemyOAuthAdapter,
    alchemy_session: AsyncSession,
) -> None:
    user = await _create_user(alchemy_session)
    session = await _create_session(alchemy_session, user)

    await oauth_adapter.create_oauth_client(
        alchemy_session,
        {
            "client_id": "client-code",
            "redirect_uris": ["https://app.local/callback"],
            "user_id": user.id,
        },
    )

    created = await oauth_adapter.create_oauth_authorization_code(
        alchemy_session,
        {
            "code": "auth-code",
            "client_id": "client-code",
            "redirect_uri": "https://app.local/callback",
            "redirect_uri_provided_explicitly": True,
            "code_challenge": "challenge",
            "code_challenge_method": "S256",
            "scopes": ["openid"],
            "user_id": user.id,
            "session_id": session.id,
            "expires_at": datetime.now(UTC) + timedelta(minutes=10),
        },
    )
    fetched = await oauth_adapter.get_oauth_authorization_code(alchemy_session, created.code)
    assert fetched is not None

    deleted = await oauth_adapter.delete_oauth_authorization_code(alchemy_session, created.code)
    assert deleted is True


@pytest.mark.asyncio
async def test_access_token_crud(
    oauth_adapter: AlchemyOAuthAdapter,
    alchemy_session: AsyncSession,
) -> None:
    user = await _create_user(alchemy_session)
    session = await _create_session(alchemy_session, user)

    await oauth_adapter.create_oauth_client(
        alchemy_session,
        {
            "client_id": "client-access",
            "redirect_uris": ["https://app.local/callback"],
            "user_id": user.id,
        },
    )

    created = await oauth_adapter.create_oauth_access_token(
        alchemy_session,
        {
            "token": "access-token",
            "client_id": "client-access",
            "session_id": session.id,
            "user_id": user.id,
            "scopes": ["openid"],
            "expires_at": datetime.now(UTC) + timedelta(hours=1),
        },
    )
    fetched = await oauth_adapter.get_oauth_access_token(alchemy_session, created.token)
    assert fetched is not None

    deleted = await oauth_adapter.delete_oauth_access_token(alchemy_session, created.token)
    assert deleted is True


@pytest.mark.asyncio
async def test_refresh_token_revoke_and_delete(
    oauth_adapter: AlchemyOAuthAdapter,
    alchemy_session: AsyncSession,
) -> None:
    user = await _create_user(alchemy_session)
    session = await _create_session(alchemy_session, user)

    await oauth_adapter.create_oauth_client(
        alchemy_session,
        {
            "client_id": "client-refresh",
            "redirect_uris": ["https://app.local/callback"],
            "user_id": user.id,
        },
    )

    refresh = await oauth_adapter.create_oauth_refresh_token(
        alchemy_session,
        {
            "token": "refresh-token",
            "client_id": "client-refresh",
            "session_id": session.id,
            "user_id": user.id,
            "scopes": ["openid"],
            "expires_at": datetime.now(UTC) + timedelta(days=30),
        },
    )

    fetched = await oauth_adapter.get_oauth_refresh_token(alchemy_session, refresh.token)
    assert fetched is not None

    revoked = await oauth_adapter.revoke_oauth_refresh_token(alchemy_session, refresh.id)
    assert revoked is True

    deleted_count = await oauth_adapter.delete_oauth_refresh_tokens_for_user_client(
        alchemy_session,
        user_id=user.id,
        client_id="client-refresh",
    )
    assert deleted_count == 1


@pytest.mark.asyncio
async def test_consent_crud(
    oauth_adapter: AlchemyOAuthAdapter,
    alchemy_session: AsyncSession,
) -> None:
    user = await _create_user(alchemy_session)

    await oauth_adapter.create_oauth_client(
        alchemy_session,
        {
            "client_id": "client-consent",
            "redirect_uris": ["https://app.local/callback"],
            "user_id": user.id,
        },
    )

    consent = await oauth_adapter.create_oauth_consent(
        alchemy_session,
        {
            "client_id": "client-consent",
            "user_id": user.id,
            "scopes": ["openid"],
        },
    )

    fetched = await oauth_adapter.get_oauth_consent(alchemy_session, consent.id)
    assert fetched is not None

    consents = await oauth_adapter.list_oauth_consents(alchemy_session, user_id=user.id)
    assert len(consents) == 1

    updated = await oauth_adapter.update_oauth_consent(
        alchemy_session,
        consent.id,
        {"scopes": ["openid", "profile"]},
    )
    assert updated is not None
    assert updated.scopes == ["openid", "profile"]

    deleted = await oauth_adapter.delete_oauth_consent(alchemy_session, consent.id)
    assert deleted is True
