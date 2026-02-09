"""Shared fixtures for integration tests that require SQLAlchemy."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest_asyncio
from belgie_alchemy.__tests__.fixtures.database import get_test_engine, get_test_session_factory

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker


@pytest_asyncio.fixture
async def db_engine(sqlite_database: str) -> AsyncGenerator[AsyncEngine, None]:
    engine = await get_test_engine(sqlite_database)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session_factory(db_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return await get_test_session_factory(db_engine)


@pytest_asyncio.fixture
async def db_session(
    db_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    async with db_session_factory() as session:
        yield session
