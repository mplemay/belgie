from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from belgie.__test__.fixtures import Account, OAuthState, Session, User
from belgie.adapters.alchemy import AlchemyAdapter


@pytest.fixture
def adapter() -> AlchemyAdapter:
    return AlchemyAdapter(
        user=User,
        account=Account,
        session=Session,
        oauth_state=OAuthState,
    )


@pytest.mark.asyncio
async def test_create_user(adapter: AlchemyAdapter, db_session: AsyncSession) -> None:
    user = await adapter.create_user(
        db_session,
        email="test@example.com",
        name="Test User",
        email_verified=True,
    )

    assert user.email == "test@example.com"
    assert user.name == "Test User"
    assert user.email_verified is True
    assert user.id is not None
    assert user.created_at is not None


@pytest.mark.asyncio
async def test_get_user_by_id(adapter: AlchemyAdapter, db_session: AsyncSession) -> None:
    created_user = await adapter.create_user(
        db_session,
        email="test@example.com",
        name="Test User",
    )

    found_user = await adapter.get_user_by_id(db_session, created_user.id)

    assert found_user is not None
    assert found_user.id == created_user.id
    assert found_user.email == "test@example.com"


@pytest.mark.asyncio
async def test_get_user_by_id_not_found(adapter: AlchemyAdapter, db_session: AsyncSession) -> None:
    user = await adapter.get_user_by_id(db_session, uuid4())
    assert user is None


@pytest.mark.asyncio
async def test_get_user_by_email(adapter: AlchemyAdapter, db_session: AsyncSession) -> None:
    await adapter.create_user(
        db_session,
        email="test@example.com",
        name="Test User",
    )

    user = await adapter.get_user_by_email(db_session, "test@example.com")

    assert user is not None
    assert user.email == "test@example.com"


@pytest.mark.asyncio
async def test_get_user_by_email_not_found(adapter: AlchemyAdapter, db_session: AsyncSession) -> None:
    user = await adapter.get_user_by_email(db_session, "nonexistent@example.com")
    assert user is None


@pytest.mark.asyncio
async def test_update_user(adapter: AlchemyAdapter, db_session: AsyncSession) -> None:
    user = await adapter.create_user(
        db_session,
        email="test@example.com",
        name="Test User",
    )

    updated_user = await adapter.update_user(
        db_session,
        user.id,
        name="Updated Name",
        email_verified=True,
    )

    assert updated_user is not None
    assert updated_user.name == "Updated Name"
    assert updated_user.email_verified is True


@pytest.mark.asyncio
async def test_update_user_not_found(adapter: AlchemyAdapter, db_session: AsyncSession) -> None:
    updated_user = await adapter.update_user(
        db_session,
        uuid4(),
        name="Updated Name",
    )
    assert updated_user is None


@pytest.mark.asyncio
async def test_create_account(adapter: AlchemyAdapter, db_session: AsyncSession) -> None:
    user = await adapter.create_user(
        db_session,
        email="test@example.com",
    )

    account = await adapter.create_account(
        db_session,
        user_id=user.id,
        provider="google",
        provider_account_id="12345",
        access_token="token",  # noqa: S106
        refresh_token="refresh",  # noqa: S106
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        token_type="Bearer",  # noqa: S106
        scope="openid email",
        id_token="id_token",  # noqa: S106
    )

    assert account.user_id == user.id
    assert account.provider == "google"
    assert account.provider_account_id == "12345"
    assert account.access_token == "token"  # noqa: S105
    assert account.refresh_token == "refresh"  # noqa: S105
    assert account.token_type == "Bearer"  # noqa: S105


@pytest.mark.asyncio
async def test_get_account(adapter: AlchemyAdapter, db_session: AsyncSession) -> None:
    user = await adapter.create_user(
        db_session,
        email="test@example.com",
    )

    await adapter.create_account(
        db_session,
        user_id=user.id,
        provider="google",
        provider_account_id="12345",
    )

    account = await adapter.get_account(db_session, "google", "12345")

    assert account is not None
    assert account.provider == "google"
    assert account.provider_account_id == "12345"


@pytest.mark.asyncio
async def test_get_account_not_found(adapter: AlchemyAdapter, db_session: AsyncSession) -> None:
    account = await adapter.get_account(db_session, "google", "nonexistent")
    assert account is None


@pytest.mark.asyncio
async def test_create_session(adapter: AlchemyAdapter, db_session: AsyncSession) -> None:
    user = await adapter.create_user(
        db_session,
        email="test@example.com",
    )

    expires_at = datetime.now(UTC) + timedelta(days=7)
    session = await adapter.create_session(
        db_session,
        user_id=user.id,
        expires_at=expires_at,
        ip_address="127.0.0.1",
        user_agent="Test Agent",
    )

    assert session.user_id == user.id
    assert session.expires_at.replace(tzinfo=UTC) == expires_at
    assert session.ip_address == "127.0.0.1"
    assert session.user_agent == "Test Agent"


@pytest.mark.asyncio
async def test_get_session(adapter: AlchemyAdapter, db_session: AsyncSession) -> None:
    user = await adapter.create_user(
        db_session,
        email="test@example.com",
    )

    created_session = await adapter.create_session(
        db_session,
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )

    found_session = await adapter.get_session(db_session, created_session.id)

    assert found_session is not None
    assert found_session.id == created_session.id


@pytest.mark.asyncio
async def test_get_session_not_found(adapter: AlchemyAdapter, db_session: AsyncSession) -> None:
    session = await adapter.get_session(db_session, uuid4())
    assert session is None


@pytest.mark.asyncio
async def test_update_session(adapter: AlchemyAdapter, db_session: AsyncSession) -> None:
    user = await adapter.create_user(
        db_session,
        email="test@example.com",
    )

    session = await adapter.create_session(
        db_session,
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )

    new_expires = datetime.now(UTC) + timedelta(days=14)
    updated_session = await adapter.update_session(
        db_session,
        session.id,
        expires_at=new_expires,
        ip_address="192.168.1.1",
    )

    assert updated_session is not None
    assert updated_session.expires_at.replace(tzinfo=UTC) == new_expires
    assert updated_session.ip_address == "192.168.1.1"


@pytest.mark.asyncio
async def test_update_session_not_found(adapter: AlchemyAdapter, db_session: AsyncSession) -> None:
    updated_session = await adapter.update_session(
        db_session,
        uuid4(),
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )
    assert updated_session is None


@pytest.mark.asyncio
async def test_delete_session(adapter: AlchemyAdapter, db_session: AsyncSession) -> None:
    user = await adapter.create_user(
        db_session,
        email="test@example.com",
    )

    session = await adapter.create_session(
        db_session,
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )

    deleted = await adapter.delete_session(db_session, session.id)
    assert deleted is True

    found = await adapter.get_session(db_session, session.id)
    assert found is None


@pytest.mark.asyncio
async def test_delete_session_not_found(adapter: AlchemyAdapter, db_session: AsyncSession) -> None:
    deleted = await adapter.delete_session(db_session, uuid4())
    assert deleted is False


@pytest.mark.asyncio
async def test_delete_expired_sessions(adapter: AlchemyAdapter, db_session: AsyncSession) -> None:
    user = await adapter.create_user(
        db_session,
        email="test@example.com",
    )

    await adapter.create_session(
        db_session,
        user_id=user.id,
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )

    await adapter.create_session(
        db_session,
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(days=7),
    )

    count = await adapter.delete_expired_sessions(db_session)
    assert count == 1


@pytest.mark.asyncio
async def test_create_oauth_state(adapter: AlchemyAdapter, db_session: AsyncSession) -> None:
    expires_at = datetime.now(UTC) + timedelta(minutes=10)
    oauth_state = await adapter.create_oauth_state(
        db_session,
        state="random_state_123",
        expires_at=expires_at,
        code_verifier="verifier_abc",
        redirect_url="/dashboard",
    )

    assert oauth_state.state == "random_state_123"
    assert oauth_state.code_verifier == "verifier_abc"
    assert oauth_state.redirect_url == "/dashboard"
    assert oauth_state.expires_at.replace(tzinfo=UTC) == expires_at


@pytest.mark.asyncio
async def test_get_oauth_state(adapter: AlchemyAdapter, db_session: AsyncSession) -> None:
    await adapter.create_oauth_state(
        db_session,
        state="random_state_123",
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )

    oauth_state = await adapter.get_oauth_state(db_session, "random_state_123")

    assert oauth_state is not None
    assert oauth_state.state == "random_state_123"


@pytest.mark.asyncio
async def test_get_oauth_state_not_found(adapter: AlchemyAdapter, db_session: AsyncSession) -> None:
    oauth_state = await adapter.get_oauth_state(db_session, "nonexistent")
    assert oauth_state is None


@pytest.mark.asyncio
async def test_delete_oauth_state(adapter: AlchemyAdapter, db_session: AsyncSession) -> None:
    await adapter.create_oauth_state(
        db_session,
        state="random_state_123",
        expires_at=datetime.now(UTC) + timedelta(minutes=10),
    )

    deleted = await adapter.delete_oauth_state(db_session, "random_state_123")
    assert deleted is True

    found = await adapter.get_oauth_state(db_session, "random_state_123")
    assert found is None


@pytest.mark.asyncio
async def test_delete_oauth_state_not_found(adapter: AlchemyAdapter, db_session: AsyncSession) -> None:
    deleted = await adapter.delete_oauth_state(db_session, "nonexistent")
    assert deleted is False


@pytest.mark.asyncio
async def test_user_with_custom_fields(adapter: AlchemyAdapter, db_session: AsyncSession) -> None:
    user_data = User(
        id=uuid4(),
        email="custom@example.com",
        email_verified=True,
        name="Custom User",
        image=None,
        custom_field="custom value",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(user_data)
    await db_session.commit()

    found = await adapter.get_user_by_email(db_session, "custom@example.com")
    assert found is not None
    assert found.custom_field == "custom value"
