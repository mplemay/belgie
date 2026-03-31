from uuid import UUID

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from belgie_alchemy.__tests__.fixtures.core.models import Individual


def test_primary_key_mixin_defaults() -> None:
    # Brussels 0.5+: PrimaryKeyMixin uses client-side UUIDs only (no DB server_default).
    id_column = Individual.__table__.c.id  # type: ignore[attr-defined]
    assert id_column.primary_key
    assert id_column.server_default is None


def test_primary_key_client_side_generation() -> None:
    """Test that UUID is generated client-side via default_factory."""
    user1 = Individual(email="user1@example.com")
    user2 = Individual(email="user2@example.com")

    # UUIDs should be generated automatically
    assert isinstance(user1.id, UUID)
    assert isinstance(user2.id, UUID)

    # UUIDs should be unique
    assert user1.id != user2.id


@pytest.mark.asyncio
async def test_primary_key_persists_client_generated_uuid(alchemy_session: AsyncSession) -> None:
    """Test that client-generated UUIDs are persisted correctly."""
    user = Individual(email="persist@example.com")
    original_id = user.id

    alchemy_session.add(user)
    await alchemy_session.commit()

    # Refresh from database
    await alchemy_session.refresh(user)

    # UUID should be unchanged
    assert user.id == original_id
    assert isinstance(user.id, UUID)


@pytest.mark.asyncio
async def test_primary_key_unique_constraint(alchemy_session: AsyncSession) -> None:
    """Test that duplicate UUIDs are rejected by unique constraint."""
    user1 = Individual(email="user1@example.com")
    alchemy_session.add(user1)
    await alchemy_session.commit()

    # Save the ID and expunge user1 to avoid identity conflicts
    user1_id = user1.id
    alchemy_session.expunge(user1)

    # Try to create another user with the same ID
    user2 = Individual(email="user2@example.com")
    user2.id = user1_id  # Force same ID

    alchemy_session.add(user2)
    with pytest.raises(IntegrityError):
        await alchemy_session.commit()

    await alchemy_session.rollback()


def test_timestamp_mixin_defaults() -> None:
    user = Individual(email="defaults@example.com")
    assert user.created_at is not None
    assert user.updated_at is not None
    assert user.deleted_at is None


def test_mark_deleted_sets_timestamp() -> None:
    user = Individual(email="x@example.com")
    assert user.deleted_at is None
    user.mark_deleted()
    assert user.deleted_at is not None
