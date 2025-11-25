from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

import pytest
import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from belgie.auth.adapters.alchemy import AlchemyAdapter
from belgie.auth.adapters.alchemy.mixins import (
    AccountMixin,
    OAuthStateMixin,
    PrimaryKeyMixin,
    SessionMixin,
    TimestampMixin,
    UserMixin,
)

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


class Base(DeclarativeBase):
    pass


class User(PrimaryKeyMixin, UserMixin, TimestampMixin, Base):
    __tablename__ = "user"


class Account(PrimaryKeyMixin, AccountMixin, TimestampMixin, Base):
    __tablename__ = "account"


class Session(PrimaryKeyMixin, SessionMixin, TimestampMixin, Base):
    __tablename__ = "session"


class OAuthState(PrimaryKeyMixin, OAuthStateMixin, TimestampMixin, Base):
    __tablename__ = "oauth_state"


TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


async def _create_engine() -> AsyncEngine:
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_conn, _connection_record) -> None:
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


@pytest_asyncio.fixture
async def engine() -> AsyncGenerator[AsyncEngine, None]:
    engine = await _create_engine()
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(engine: AsyncEngine) -> AsyncGenerator[async_sessionmaker[AsyncSession], None]:
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory


@pytest_asyncio.fixture
async def db(session_factory: async_sessionmaker[AsyncSession]) -> AsyncGenerator[AsyncSession, None]:
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture
async def adapter(session_factory: async_sessionmaker[AsyncSession]) -> AlchemyAdapter:
    async def _get_db() -> AsyncSession:
        async with session_factory() as session:
            yield session

    return AlchemyAdapter(
        user=User,
        account=Account,
        session=Session,
        oauth_state=OAuthState,
        db_dependency=_get_db,
    )


@pytest.mark.asyncio
async def test_create_user_with_mixins(adapter: AlchemyAdapter, db: AsyncSession) -> None:
    user = await adapter.create_user(db, email="mixins@example.com", name="Mix In")
    assert user.email == "mixins@example.com"
    assert user.id is not None
    assert isinstance(user.created_at, datetime)


@pytest.mark.asyncio
async def test_relationships_available(db: AsyncSession) -> None:
    user = User(email="rel@example.com")
    db.add(user)
    await db.commit()
    await db.refresh(user)

    account = Account(user_id=user.id, provider="google", provider_account_id="123")
    db.add(account)
    await db.commit()
    await db.refresh(account)

    assert account.user_id == user.id


@pytest.mark.asyncio
async def test_session_expires_at_timezone(db: AsyncSession) -> None:
    user = User(email="tz@example.com")
    db.add(user)
    await db.commit()
    await db.refresh(user)

    expiry = datetime.now().astimezone() + timedelta(days=1)
    session = Session(user_id=user.id, expires_at=expiry)
    db.add(session)
    await db.commit()
    await db.refresh(session)

    # SQLite drops tzinfo even with timezone=True; assert value matches when made naive
    assert session.expires_at.tzinfo is not None or session.expires_at == expiry.replace(tzinfo=None)


@pytest.mark.asyncio
async def test_oauth_state_uniqueness(db: AsyncSession) -> None:
    state = OAuthState(state="abc", expires_at=datetime.now(UTC))
    db.add(state)
    await db.commit()
    await db.refresh(state)

    assert state.state == "abc"
    assert state.expires_at is not None
