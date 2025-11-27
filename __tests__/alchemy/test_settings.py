from importlib.util import find_spec

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from belgie.alchemy.settings import DatabaseSettings

ASYNC_PG_AVAILABLE = find_spec("asyncpg") is not None


@pytest.mark.asyncio
async def test_sqlite_engine_fk_enabled() -> None:
    db = DatabaseSettings(dialect={"type": "sqlite", "database": ":memory:", "enable_foreign_keys": True})

    async with db.engine.connect() as conn:
        result = await conn.execute(text("PRAGMA foreign_keys"))
        value = result.scalar_one()

    assert value == 1
    await db.engine.dispose()


@pytest.mark.asyncio
async def test_session_maker_expire_disabled() -> None:
    db = DatabaseSettings(dialect={"type": "sqlite", "database": ":memory:"})

    session_factory = db.session_maker
    assert session_factory.kw["expire_on_commit"] is False

    async with session_factory() as session:
        assert isinstance(session, AsyncSession)

    await db.engine.dispose()


def test_postgres_url_creation() -> None:
    if not ASYNC_PG_AVAILABLE:
        pytest.skip("asyncpg not installed; skip postgres engine test")

    db = DatabaseSettings(
        dialect={
            "type": "postgres",
            "host": "localhost",
            "port": 5432,
            "database": "belgie",
            "username": "user",
            "password": "secret",
        },
    )

    assert db.engine.url.get_backend_name() == "postgresql"
    assert db.engine.url.get_driver_name() == "asyncpg"
    assert db.engine.url.username == "user"
    assert db.engine.url.host == "localhost"
    assert db.engine.url.database == "belgie"
    assert db.engine.url.port == 5432
