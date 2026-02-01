import os
from importlib.util import find_spec
from urllib.parse import urlparse

import pytest
from alchemy.settings import DatabaseSettings
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

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
        with pytest.raises(IntegrityError):  # noqa: PT012
            await session.execute(text("INSERT INTO test_children (id, parent_id, name) VALUES (1, 999, 'orphan')"))
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


# ==================== PostgreSQL Integration Tests ====================


@pytest.mark.asyncio
@pytest.mark.integration
async def test_postgres_engine_connection() -> None:
    """Test actual PostgreSQL connection and session creation.

    This test requires a PostgreSQL instance to be available.
    Set POSTGRES_TEST_URL environment variable or skip.
    """
    if not ASYNC_PG_AVAILABLE:
        pytest.skip("asyncpg not installed")

    # Allow configuring test database via environment
    test_url = os.getenv("POSTGRES_TEST_URL")
    if not test_url:
        pytest.skip("POSTGRES_TEST_URL not set - skipping integration test")

    # Parse URL components (format: postgresql://user:pass@host:port/db)
    try:
        parsed = urlparse(test_url)
        db = DatabaseSettings(
            dialect={
                "type": "postgres",
                "host": parsed.hostname or "localhost",
                "port": parsed.port or 5432,
                "database": parsed.path.lstrip("/") if parsed.path else "postgres",
                "username": parsed.username or "postgres",
                "password": parsed.password or "",
            },
        )

        # Test basic connection
        async with db.engine.connect() as conn:
            result = await conn.execute(text("SELECT 1 as test"))
            value = result.scalar_one()
            assert value == 1

        await db.engine.dispose()

    except (OSError, IntegrityError) as e:
        pytest.skip(f"Could not connect to PostgreSQL: {e}")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_postgres_session_creation() -> None:
    """Test that PostgreSQL session factory works correctly."""
    if not ASYNC_PG_AVAILABLE:
        pytest.skip("asyncpg not installed")

    test_url = os.getenv("POSTGRES_TEST_URL")
    if not test_url:
        pytest.skip("POSTGRES_TEST_URL not set - skipping integration test")

    try:
        parsed = urlparse(test_url)
        db = DatabaseSettings(
            dialect={
                "type": "postgres",
                "host": parsed.hostname or "localhost",
                "port": parsed.port or 5432,
                "database": parsed.path.lstrip("/") if parsed.path else "postgres",
                "username": parsed.username or "postgres",
                "password": parsed.password or "",
            },
        )

        # Test session creation
        async with db.session_maker() as session:
            assert isinstance(session, AsyncSession)
            result = await session.execute(text("SELECT version()"))
            version = result.scalar_one()
            assert "PostgreSQL" in version

        await db.engine.dispose()

    except (OSError, IntegrityError) as e:
        pytest.skip(f"Could not connect to PostgreSQL: {e}")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_postgres_dependency_yields_sessions() -> None:
    """Test that PostgreSQL dependency generator works correctly."""
    if not ASYNC_PG_AVAILABLE:
        pytest.skip("asyncpg not installed")

    test_url = os.getenv("POSTGRES_TEST_URL")
    if not test_url:
        pytest.skip("POSTGRES_TEST_URL not set - skipping integration test")

    try:
        parsed = urlparse(test_url)
        db = DatabaseSettings(
            dialect={
                "type": "postgres",
                "host": parsed.hostname or "localhost",
                "port": parsed.port or 5432,
                "database": parsed.path.lstrip("/") if parsed.path else "postgres",
                "username": parsed.username or "postgres",
                "password": parsed.password or "",
            },
        )

        # Test dependency yields working sessions
        sessions = []
        async for session in db.dependency():
            sessions.append(session)
            # Verify session works
            result = await session.execute(text("SELECT 1"))
            assert result.scalar_one() == 1
            break

        async for session in db.dependency():
            sessions.append(session)
            break

        # Verify different session instances
        assert len(sessions) == 2
        assert sessions[0] is not sessions[1]

        await db.engine.dispose()

    except (OSError, IntegrityError) as e:
        pytest.skip(f"Could not connect to PostgreSQL: {e}")


@pytest.mark.asyncio
@pytest.mark.integration
async def test_postgres_connection_pooling() -> None:
    """Test that PostgreSQL connection pooling is configured correctly."""
    if not ASYNC_PG_AVAILABLE:
        pytest.skip("asyncpg not installed")

    test_url = os.getenv("POSTGRES_TEST_URL")
    if not test_url:
        pytest.skip("POSTGRES_TEST_URL not set - skipping integration test")

    try:
        parsed = urlparse(test_url)
        db = DatabaseSettings(
            dialect={
                "type": "postgres",
                "host": parsed.hostname or "localhost",
                "port": parsed.port or 5432,
                "database": parsed.path.lstrip("/") if parsed.path else "postgres",
                "username": parsed.username or "postgres",
                "password": parsed.password or "",
                "pool_size": 5,
                "max_overflow": 10,
            },
        )

        # Verify pool settings
        assert db.dialect.pool_size == 5
        assert db.dialect.max_overflow == 10

        # Create multiple sessions to test pooling
        sessions = []
        for _ in range(3):
            async with db.session_maker() as session:
                sessions.append(session)
                result = await session.execute(text("SELECT 1"))
                assert result.scalar_one() == 1

        await db.engine.dispose()

    except (OSError, IntegrityError) as e:
        pytest.skip(f"Could not connect to PostgreSQL: {e}")
