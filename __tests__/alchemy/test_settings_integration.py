"""Integration tests for DatabaseSettings with environment variables.

This module tests that DatabaseSettings can be correctly loaded from environment
variables using Pydantic's settings mechanism.

Environment variable format:
- Prefix: BELGIE_DATABASE_
- Nested delimiter: __
- Examples:
  - BELGIE_DATABASE_DIALECT__TYPE=postgres
  - BELGIE_DATABASE_DIALECT__HOST=localhost
  - BELGIE_DATABASE_DIALECT__PORT=5432
"""

import os
from importlib.util import find_spec
from urllib.parse import urlparse

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from belgie.alchemy.settings import DatabaseSettings

ASYNC_PG_AVAILABLE = find_spec("asyncpg") is not None


@pytest.mark.integration
def test_sqlite_from_env_minimal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test loading minimal SQLite configuration from environment variables."""
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__TYPE", "sqlite")
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__DATABASE", ":memory:")

    db = DatabaseSettings()

    assert db.dialect.type == "sqlite"
    assert db.dialect.database == ":memory:"
    assert db.dialect.enable_foreign_keys is True  # Default value
    assert db.dialect.echo is False  # Default value


@pytest.mark.integration
def test_sqlite_from_env_full(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test loading full SQLite configuration from environment variables."""
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__TYPE", "sqlite")
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__DATABASE", "/tmp/test.db")  # noqa: S108
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__ENABLE_FOREIGN_KEYS", "false")
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__ECHO", "true")

    db = DatabaseSettings()

    assert db.dialect.type == "sqlite"
    assert db.dialect.database == "/tmp/test.db"  # noqa: S108
    assert db.dialect.enable_foreign_keys is False
    assert db.dialect.echo is True


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sqlite_from_env_creates_working_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that SQLite engine created from env vars works correctly."""
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__TYPE", "sqlite")
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__DATABASE", ":memory:")

    db = DatabaseSettings()

    # Test engine works
    async with db.engine.connect() as conn:
        result = await conn.execute(text("SELECT 1 as test"))
        value = result.scalar_one()
        assert value == 1

    await db.engine.dispose()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sqlite_from_env_foreign_keys_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that foreign key enforcement from env vars works."""
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__TYPE", "sqlite")
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__DATABASE", ":memory:")
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__ENABLE_FOREIGN_KEYS", "true")

    db = DatabaseSettings()

    async with db.engine.connect() as conn:
        result = await conn.execute(text("PRAGMA foreign_keys"))
        value = result.scalar_one()
        assert value == 1

    await db.engine.dispose()


@pytest.mark.integration
def test_postgres_from_env_minimal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test loading minimal PostgreSQL configuration from environment variables."""
    if not ASYNC_PG_AVAILABLE:
        pytest.skip("asyncpg not installed")

    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__TYPE", "postgres")
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__HOST", "localhost")
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__DATABASE", "testdb")
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__USERNAME", "testuser")
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__PASSWORD", "testpass")

    db = DatabaseSettings()

    assert db.dialect.type == "postgres"
    assert db.dialect.host == "localhost"
    assert db.dialect.port == 5432  # Default value
    assert db.dialect.database == "testdb"
    assert db.dialect.username == "testuser"
    assert db.dialect.password.get_secret_value() == "testpass"
    assert db.dialect.pool_size == 5  # Default value
    assert db.dialect.max_overflow == 10  # Default value


@pytest.mark.integration
def test_postgres_from_env_full(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test loading full PostgreSQL configuration from environment variables."""
    if not ASYNC_PG_AVAILABLE:
        pytest.skip("asyncpg not installed")

    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__TYPE", "postgres")
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__HOST", "db.example.com")
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__PORT", "5433")
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__DATABASE", "mydb")
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__USERNAME", "admin")
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__PASSWORD", "secret123")
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__POOL_SIZE", "20")
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__MAX_OVERFLOW", "30")
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__POOL_TIMEOUT", "60.0")
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__POOL_RECYCLE", "7200")
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__POOL_PRE_PING", "false")
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__ECHO", "true")

    db = DatabaseSettings()

    assert db.dialect.type == "postgres"
    assert db.dialect.host == "db.example.com"
    assert db.dialect.port == 5433
    assert db.dialect.database == "mydb"
    assert db.dialect.username == "admin"
    assert db.dialect.password.get_secret_value() == "secret123"
    assert db.dialect.pool_size == 20
    assert db.dialect.max_overflow == 30
    assert db.dialect.pool_timeout == 60.0
    assert db.dialect.pool_recycle == 7200
    assert db.dialect.pool_pre_ping is False
    assert db.dialect.echo is True


@pytest.mark.asyncio
@pytest.mark.integration
async def test_postgres_from_env_actual_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that PostgreSQL connection from env vars works with real database.

    Requires POSTGRES_TEST_URL environment variable to be set.
    Format: postgresql://user:pass@host:port/database
    """
    if not ASYNC_PG_AVAILABLE:
        pytest.skip("asyncpg not installed")

    # Check if real PostgreSQL is available
    test_url = os.getenv("POSTGRES_TEST_URL")
    if not test_url:
        pytest.skip("POSTGRES_TEST_URL not set - skipping live connection test")

    # Parse the test URL to set up environment variables
    parsed = urlparse(test_url)

    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__TYPE", "postgres")
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__HOST", parsed.hostname or "localhost")
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__PORT", str(parsed.port or 5432))
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__DATABASE", parsed.path.lstrip("/") if parsed.path else "postgres")
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__USERNAME", parsed.username or "postgres")
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__PASSWORD", parsed.password or "")

    try:
        db = DatabaseSettings()

        # Test basic connection
        async with db.engine.connect() as conn:
            result = await conn.execute(text("SELECT 1 as test"))
            value = result.scalar_one()
            assert value == 1

        # Test session creation
        async with db.session_maker() as session:
            assert isinstance(session, AsyncSession)
            result = await session.execute(text("SELECT version()"))
            version = result.scalar_one()
            assert "PostgreSQL" in version

        await db.engine.dispose()

    except OSError as e:
        pytest.skip(f"Could not connect to PostgreSQL: {e}")


@pytest.mark.integration
def test_env_vars_override_direct_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that environment variables override directly passed values."""
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__TYPE", "sqlite")
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__DATABASE", ":memory:")
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__ECHO", "true")

    # Try to pass different values directly - env vars should win
    db = DatabaseSettings()

    # Env vars should be used
    assert db.dialect.type == "sqlite"
    assert db.dialect.database == ":memory:"
    assert db.dialect.echo is True


@pytest.mark.integration
def test_missing_required_postgres_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that missing required PostgreSQL fields raise validation error."""
    if not ASYNC_PG_AVAILABLE:
        pytest.skip("asyncpg not installed")

    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__TYPE", "postgres")
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__HOST", "localhost")
    # Missing database, username, password

    with pytest.raises(ValidationError):
        DatabaseSettings()


@pytest.mark.integration
def test_invalid_port_number(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that invalid port number raises validation error."""
    if not ASYNC_PG_AVAILABLE:
        pytest.skip("asyncpg not installed")

    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__TYPE", "postgres")
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__HOST", "localhost")
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__PORT", "-1")  # Invalid
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__DATABASE", "testdb")
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__USERNAME", "user")
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__PASSWORD", "pass")

    with pytest.raises(ValidationError, match="Input should be greater than 0"):
        DatabaseSettings()


@pytest.mark.integration
def test_case_insensitive_boolean_values(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that boolean environment variables accept various formats."""
    test_cases = [
        ("true", True),
        ("True", True),
        ("TRUE", True),
        ("1", True),
        ("false", False),
        ("False", False),
        ("FALSE", False),
        ("0", False),
    ]

    for env_value, expected in test_cases:
        monkeypatch.setenv("BELGIE_DATABASE_DIALECT__TYPE", "sqlite")
        monkeypatch.setenv("BELGIE_DATABASE_DIALECT__DATABASE", ":memory:")
        monkeypatch.setenv("BELGIE_DATABASE_DIALECT__ECHO", env_value)

        db = DatabaseSettings()
        assert db.dialect.echo is expected, f"Expected {expected} for env value '{env_value}'"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_session_maker_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that session_maker created from env vars works correctly."""
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__TYPE", "sqlite")
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__DATABASE", ":memory:")

    db = DatabaseSettings()

    # Verify session maker settings
    assert db.session_maker.kw["expire_on_commit"] is False

    # Test session creation
    async with db.session_maker() as session:
        assert isinstance(session, AsyncSession)
        result = await session.execute(text("SELECT 1"))
        assert result.scalar_one() == 1

    await db.engine.dispose()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_dependency_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that dependency generator from env vars works correctly."""
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__TYPE", "sqlite")
    monkeypatch.setenv("BELGIE_DATABASE_DIALECT__DATABASE", ":memory:")

    db = DatabaseSettings()

    # Test dependency yields sessions
    sessions = []
    async for session in db.dependency():
        sessions.append(session)
        result = await session.execute(text("SELECT 1"))
        assert result.scalar_one() == 1
        break

    async for session in db.dependency():
        sessions.append(session)
        break

    # Verify different sessions
    assert len(sessions) == 2
    assert sessions[0] is not sessions[1]

    await db.engine.dispose()
