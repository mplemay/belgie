from collections.abc import AsyncGenerator

import pytest_asyncio
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from belgie.alchemy.base import Base
from belgie.alchemy.impl.auth import Account, OAuthState, Session, User


@pytest_asyncio.fixture
async def alchemy_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Create an isolated in-memory SQLite engine for testing.

    Each test gets its own in-memory database, so Base.metadata.create_all
    is safe even when tests run in parallel - there's no shared state.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_fk(dbapi_conn, _connection_record) -> None:
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def alchemy_session_factory(alchemy_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(alchemy_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def alchemy_session(
    alchemy_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    async with alchemy_session_factory() as session:
        yield session


__all__ = ["Account", "OAuthState", "Session", "User", "alchemy_engine", "alchemy_session", "alchemy_session_factory"]
