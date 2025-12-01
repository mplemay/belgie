from importlib.util import find_spec

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
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


@pytest.mark.asyncio
async def test_sqlite_fk_violations_raise_error() -> None:
    """Test that foreign key constraints are enforced when enabled."""
    db = DatabaseSettings(dialect={"type": "sqlite", "database": ":memory:", "enable_foreign_keys": True})

    # Try to insert a child record with invalid FK - should raise IntegrityError
    async with db.engine.begin() as conn:
        # Create simple test tables
        await conn.execute(text("CREATE TABLE test_parents (id INTEGER PRIMARY KEY, name TEXT)"))
        await conn.execute(
            text(
                "CREATE TABLE test_children "
                "(id INTEGER PRIMARY KEY, parent_id INTEGER NOT NULL REFERENCES test_parents(id), name TEXT)",
            ),
        )

    async with db.session_maker() as session:
        # Try to insert child without parent - should raise IntegrityError
        await session.execute(text("INSERT INTO test_children (id, parent_id, name) VALUES (1, 999, 'orphan')"))
        with pytest.raises(IntegrityError):
            await session.commit()

    await db.engine.dispose()


@pytest.mark.asyncio
async def test_dependency_yields_different_sessions() -> None:
    """Test that dependency yields different session instances."""
    db = DatabaseSettings(dialect={"type": "sqlite", "database": ":memory:"})

    sessions = []
    async for session1 in db.dependency():
        sessions.append(session1)
        break

    async for session2 in db.dependency():
        sessions.append(session2)
        break

    assert len(sessions) == 2
    assert sessions[0] is not sessions[1]
    await db.engine.dispose()


@pytest.mark.asyncio
async def test_dependency_handles_exceptions() -> None:
    """Test that dependency properly handles exceptions."""
    db = DatabaseSettings(dialect={"type": "sqlite", "database": ":memory:"})

    # Simulate exception during request handling
    simulated_error = "Simulated error"
    try:
        async for _session in db.dependency():
            # Force an error
            raise ValueError(simulated_error)  # noqa: TRY301
    except ValueError:
        pass  # Expected

    # Verify we can still get new sessions
    async for session in db.dependency():
        assert isinstance(session, AsyncSession)
        break

    await db.engine.dispose()


def test_postgres_settings_validation() -> None:
    """Test that PostgreSQL settings validates all required fields."""
    # Test with valid data
    db = DatabaseSettings(
        dialect={
            "type": "postgres",
            "host": "db.example.com",
            "port": 5433,
            "database": "testdb",
            "username": "testuser",
            "password": "testpass",
            "pool_size": 10,
            "max_overflow": 20,
        },
    )

    assert db.dialect.type == "postgres"
    assert db.dialect.host == "db.example.com"
    assert db.dialect.port == 5433
    assert db.dialect.database == "testdb"
    assert db.dialect.username == "testuser"
    assert db.dialect.password.get_secret_value() == "testpass"
    assert db.dialect.pool_size == 10
    assert db.dialect.max_overflow == 20


def test_sqlite_settings_validation() -> None:
    """Test that SQLite settings validates correctly."""
    db = DatabaseSettings(
        dialect={
            "type": "sqlite",
            "database": "/tmp/test.db",  # noqa: S108
            "enable_foreign_keys": False,
            "echo": True,
        },
    )

    assert db.dialect.type == "sqlite"
    assert db.dialect.database == "/tmp/test.db"  # noqa: S108
    assert db.dialect.enable_foreign_keys is False
    assert db.dialect.echo is True
