from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from belgie_alchemy.__tests__.fixtures.models import Session, User
from belgie_alchemy.oauth_models import (
    OAuthAccessToken,
    OAuthAuthorizationCode,
    OAuthClient,
    OAuthConsent,
    OAuthRefreshToken,
)


def _create_client() -> OAuthClient:
    return OAuthClient(
        client_id="client-123",
        redirect_uris=["https://app.local/callback"],
    )


@pytest.mark.asyncio
async def test_oauth_client_unique_client_id(alchemy_session: AsyncSession) -> None:
    client = _create_client()
    alchemy_session.add(client)
    await alchemy_session.commit()

    duplicate = _create_client()
    alchemy_session.add(duplicate)
    with pytest.raises(IntegrityError):
        await alchemy_session.commit()
    await alchemy_session.rollback()


@pytest.mark.asyncio
async def test_oauth_token_relationships(alchemy_session: AsyncSession) -> None:
    user = User(email="oauth-token@example.com")
    alchemy_session.add(user)
    await alchemy_session.commit()

    session = Session(
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    alchemy_session.add(session)
    await alchemy_session.commit()

    client = OAuthClient(
        client_id="client-token",
        redirect_uris=["https://app.local/callback"],
        user_id=user.id,
    )
    alchemy_session.add(client)
    await alchemy_session.commit()

    refresh = OAuthRefreshToken(
        token="refresh-token",
        client_id=client.client_id,
        session_id=session.id,
        user_id=user.id,
        scopes=["openid"],
        expires_at=datetime.now(UTC) + timedelta(days=30),
    )
    alchemy_session.add(refresh)
    await alchemy_session.commit()

    access = OAuthAccessToken(
        token="access-token",
        client_id=client.client_id,
        session_id=session.id,
        user_id=user.id,
        refresh_id=refresh.id,
        scopes=["openid"],
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    alchemy_session.add(access)
    await alchemy_session.commit()

    code = OAuthAuthorizationCode(
        code="auth-code",
        client_id=client.client_id,
        redirect_uri="https://app.local/callback",
        redirect_uri_provided_explicitly=True,
        code_challenge="challenge",
        code_challenge_method="S256",
        scopes=["openid"],
        user_id=user.id,
        session_id=session.id,
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )
    alchemy_session.add(code)
    await alchemy_session.commit()

    consent = OAuthConsent(
        client_id=client.client_id,
        user_id=user.id,
        scopes=["openid"],
    )
    alchemy_session.add(consent)
    await alchemy_session.commit()

    assert access.id is not None
    assert refresh.id is not None
    assert code.id is not None
    assert consent.id is not None
