from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from alchemy import AlchemyAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from __tests__.auth.fixtures.models import Account, OAuthState, Session, User
from belgie.auth.session.manager import SessionManager


@pytest.fixture
def adapter(db_session: AsyncSession) -> AlchemyAdapter:  # noqa: ARG001
    return AlchemyAdapter(
        user=User,
        account=Account,
        session=Session,
        oauth_state=OAuthState,
    )


@pytest.fixture
def session_manager(adapter: AlchemyAdapter) -> SessionManager:
    return SessionManager(
        adapter=adapter,
        max_age=3600,
        update_age=900,
    )


@pytest.mark.asyncio
async def test_create_session(session_manager: SessionManager, db_session: AsyncSession) -> None:
    user = await session_manager.adapter.create_user(
        db_session,
        email="test@example.com",
    )

    before_create = datetime.now(UTC)
    session = await session_manager.create_session(
        db_session,
        user_id=user.id,
        ip_address="127.0.0.1",
        user_agent="Test Agent",
    )
    after_create = datetime.now(UTC)

    assert session.user_id == user.id
    assert session.ip_address == "127.0.0.1"
    assert session.user_agent == "Test Agent"

    expected_min_expiry = before_create + timedelta(seconds=3600)
    expected_max_expiry = after_create + timedelta(seconds=3600)

    session_expiry = session.expires_at.replace(tzinfo=UTC)
    assert expected_min_expiry <= session_expiry <= expected_max_expiry


@pytest.mark.asyncio
async def test_get_session_valid(session_manager: SessionManager, db_session: AsyncSession) -> None:
    user = await session_manager.adapter.create_user(
        db_session,
        email="test@example.com",
    )

    created_session = await session_manager.create_session(
        db_session,
        user_id=user.id,
    )

    retrieved_session = await session_manager.get_session(db_session, created_session.id)

    assert retrieved_session is not None
    assert retrieved_session.id == created_session.id
    assert retrieved_session.user_id == user.id


@pytest.mark.asyncio
async def test_get_session_not_found(session_manager: SessionManager, db_session: AsyncSession) -> None:
    session = await session_manager.get_session(db_session, uuid4())
    assert session is None


@pytest.mark.asyncio
async def test_get_session_expired_deletes_session(
    session_manager: SessionManager,
    db_session: AsyncSession,
) -> None:
    user = await session_manager.adapter.create_user(
        db_session,
        email="test@example.com",
    )

    expired_session = await session_manager.adapter.create_session(
        db_session,
        user_id=user.id,
        expires_at=datetime.now(UTC) - timedelta(seconds=1),
    )

    retrieved_session = await session_manager.get_session(db_session, expired_session.id)

    assert retrieved_session is None

    db_session_check = await session_manager.adapter.get_session(db_session, expired_session.id)
    assert db_session_check is None


@pytest.mark.asyncio
async def test_get_session_sliding_window_refresh(
    session_manager: SessionManager,
    db_session: AsyncSession,
) -> None:
    user = await session_manager.adapter.create_user(
        db_session,
        email="test@example.com",
    )

    old_expiry = datetime.now(UTC) + timedelta(seconds=600)
    session = await session_manager.adapter.create_session(
        db_session,
        user_id=user.id,
        expires_at=old_expiry,
    )

    before_get = datetime.now(UTC)
    retrieved_session = await session_manager.get_session(db_session, session.id)
    after_get = datetime.now(UTC)

    assert retrieved_session is not None

    expected_min_expiry = before_get + timedelta(seconds=3600)
    expected_max_expiry = after_get + timedelta(seconds=3600)

    new_expiry = retrieved_session.expires_at.replace(tzinfo=UTC)
    assert expected_min_expiry <= new_expiry <= expected_max_expiry
    assert new_expiry > old_expiry.replace(tzinfo=UTC)


@pytest.mark.asyncio
async def test_get_session_no_refresh_if_far_from_expiry(
    session_manager: SessionManager,
    db_session: AsyncSession,
) -> None:
    user = await session_manager.adapter.create_user(
        db_session,
        email="test@example.com",
    )

    original_expiry = datetime.now(UTC) + timedelta(seconds=3600)
    session = await session_manager.adapter.create_session(
        db_session,
        user_id=user.id,
        expires_at=original_expiry,
    )

    retrieved_session = await session_manager.get_session(db_session, session.id)

    assert retrieved_session is not None
    assert retrieved_session.expires_at.replace(tzinfo=UTC) == original_expiry.replace(tzinfo=UTC)


@pytest.mark.asyncio
async def test_delete_session(session_manager: SessionManager, db_session: AsyncSession) -> None:
    user = await session_manager.adapter.create_user(
        db_session,
        email="test@example.com",
    )

    session = await session_manager.create_session(
        db_session,
        user_id=user.id,
    )

    deleted = await session_manager.delete_session(db_session, session.id)
    assert deleted is True

    retrieved = await session_manager.get_session(db_session, session.id)
    assert retrieved is None


@pytest.mark.asyncio
async def test_delete_session_not_found(session_manager: SessionManager, db_session: AsyncSession) -> None:
    deleted = await session_manager.delete_session(db_session, uuid4())
    assert deleted is False


@pytest.mark.asyncio
async def test_cleanup_expired_sessions(session_manager: SessionManager, db_session: AsyncSession) -> None:
    user = await session_manager.adapter.create_user(
        db_session,
        email="test@example.com",
    )

    await session_manager.adapter.create_session(
        db_session,
        user_id=user.id,
        expires_at=datetime.now(UTC) - timedelta(days=1),
    )
    await session_manager.adapter.create_session(
        db_session,
        user_id=user.id,
        expires_at=datetime.now(UTC) - timedelta(hours=1),
    )
    valid_session = await session_manager.adapter.create_session(
        db_session,
        user_id=user.id,
        expires_at=datetime.now(UTC) + timedelta(days=1),
    )

    count = await session_manager.cleanup_expired_sessions(db_session)
    assert count == 2

    retrieved = await session_manager.get_session(db_session, valid_session.id)
    assert retrieved is not None


@pytest.mark.asyncio
async def test_cleanup_no_expired_sessions(session_manager: SessionManager, db_session: AsyncSession) -> None:
    user = await session_manager.adapter.create_user(
        db_session,
        email="test@example.com",
    )

    await session_manager.create_session(
        db_session,
        user_id=user.id,
    )

    count = await session_manager.cleanup_expired_sessions(db_session)
    assert count == 0


@pytest.mark.asyncio
async def test_session_manager_with_custom_max_age(
    adapter: AlchemyAdapter,
    db_session: AsyncSession,
) -> None:
    custom_manager = SessionManager(
        adapter=adapter,
        max_age=7200,
        update_age=1800,
    )

    user = await adapter.create_user(
        db_session,
        email="test@example.com",
    )

    before_create = datetime.now(UTC)
    session = await custom_manager.create_session(
        db_session,
        user_id=user.id,
    )
    after_create = datetime.now(UTC)

    expected_min_expiry = before_create + timedelta(seconds=7200)
    expected_max_expiry = after_create + timedelta(seconds=7200)

    session_expiry = session.expires_at.replace(tzinfo=UTC)
    assert expected_min_expiry <= session_expiry <= expected_max_expiry


@pytest.mark.asyncio
async def test_session_manager_sliding_window_exact_boundary(
    adapter: AlchemyAdapter,
    db_session: AsyncSession,
) -> None:
    manager = SessionManager(
        adapter=adapter,
        max_age=3600,
        update_age=900,
    )

    user = await adapter.create_user(
        db_session,
        email="test@example.com",
    )

    expires_at = datetime.now(UTC) + timedelta(seconds=899)
    session = await adapter.create_session(
        db_session,
        user_id=user.id,
        expires_at=expires_at,
    )

    original_expiry = session.expires_at.replace(tzinfo=UTC)

    retrieved = await manager.get_session(db_session, session.id)

    assert retrieved is not None
    new_expiry = retrieved.expires_at.replace(tzinfo=UTC)
    assert new_expiry > original_expiry
