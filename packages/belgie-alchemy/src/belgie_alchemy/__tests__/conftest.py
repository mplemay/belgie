"""Pytest fixtures for alchemy tests."""

from __future__ import annotations

from importlib.util import find_spec
from tempfile import gettempdir
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest

SQLALCHEMY_AVAILABLE = find_spec("sqlalchemy") is not None


def pytest_ignore_collect(collection_path, config) -> bool:  # noqa: ARG001
    return not SQLALCHEMY_AVAILABLE


if SQLALCHEMY_AVAILABLE:
    import pytest_asyncio

    from belgie_alchemy.__tests__.fixtures.database import get_test_engine, get_test_session_factory

    if TYPE_CHECKING:
        from collections.abc import AsyncGenerator

        from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

    @pytest.fixture
    def sqlite_database() -> str:
        return f"{gettempdir()}/belgie_test_{uuid4().hex}.db"

    @pytest_asyncio.fixture
    async def alchemy_engine(sqlite_database: str) -> AsyncGenerator[AsyncEngine, None]:
        """Create an isolated in-memory SQLite engine for testing.

        Each test gets its own in-memory database, so Base.metadata.create_all
        is safe even when tests run in parallel - there's no shared state.
        """
        engine = await get_test_engine(sqlite_database)
        yield engine
        await engine.dispose()

    @pytest_asyncio.fixture
    async def alchemy_session_factory(alchemy_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
        return await get_test_session_factory(alchemy_engine)

    @pytest_asyncio.fixture
    async def alchemy_session(
        alchemy_session_factory: async_sessionmaker[AsyncSession],
    ) -> AsyncGenerator[AsyncSession, None]:
        async with alchemy_session_factory() as session:
            yield session
