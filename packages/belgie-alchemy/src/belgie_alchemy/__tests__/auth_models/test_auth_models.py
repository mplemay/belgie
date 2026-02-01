from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from belgie_alchemy.__tests__.conftest import Account, OAuthState, Session, User


def test_user_model_structure() -> None:
    """Verify User model demonstrates proper structure."""
    assert User.__tablename__ == "users"
    assert not getattr(User, "__abstract__", False)
    assert hasattr(User, "email")
    assert hasattr(User, "scopes")


def test_user_has_scopes_field() -> None:
    """Verify User has scopes field that accepts list of strings."""
    user = User(email="test@example.com")
    user.scopes = ["read", "write"]
    assert user.scopes == ["read", "write"]


def test_user_relationships_defined() -> None:
    """Verify User has bidirectional relationships defined."""
    assert hasattr(User, "accounts")
    assert hasattr(User, "sessions")
    assert hasattr(User, "oauth_states")


@pytest.mark.asyncio
async def test_account_unique_constraint(alchemy_session: AsyncSession) -> None:
    user = User(email="auth@example.com")
    alchemy_session.add(user)
    await alchemy_session.commit()

    account = Account(
        user_id=user.id,
        provider="google",
        provider_account_id="abc",
    )
    alchemy_session.add(account)
    await alchemy_session.commit()

    duplicate = Account(
        user_id=user.id,
        provider="google",
        provider_account_id="abc",
    )
    alchemy_session.add(duplicate)
    with pytest.raises(IntegrityError):
        await alchemy_session.commit()
    await alchemy_session.rollback()


@pytest.mark.asyncio
async def test_session_relationship(alchemy_session: AsyncSession) -> None:
    user = User(email="session@example.com")
    alchemy_session.add(user)
    await alchemy_session.commit()

    session = Session(
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )
    alchemy_session.add(session)
    await alchemy_session.commit()

    refreshed = await alchemy_session.get(User, user.id)
    assert refreshed is not None
    await alchemy_session.refresh(refreshed, attribute_names=["sessions"])
    assert len(refreshed.sessions) == 1


@pytest.mark.asyncio
async def test_oauth_state_optional_user(alchemy_session: AsyncSession) -> None:
    state = OAuthState(
        state="abc",
        code_verifier=None,
        redirect_url=None,
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        user_id=None,
    )
    alchemy_session.add(state)
    await alchemy_session.commit()

    rows = await alchemy_session.execute(select(OAuthState))
    stored = rows.scalar_one()
    assert stored.user is None
