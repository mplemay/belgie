"""Integration tests for DatabaseSettings with environment variables.

This module tests that DatabaseSettings can be correctly loaded from environment
variables using Pydantic's settings mechanism with separate prefixes.

Environment variable format (NO double underscores!):
- Type selector: BELGIE_DATABASE_TYPE=postgres or sqlite
- SQLite vars: BELGIE_SQLITE_DATABASE, BELGIE_SQLITE_ENABLE_FOREIGN_KEYS, etc.
- Postgres vars: BELGIE_POSTGRES_HOST, BELGIE_POSTGRES_PORT, BELGIE_POSTGRES_DATABASE, etc.

Examples:
    # SQLite
    BELGIE_DATABASE_TYPE=sqlite
    BELGIE_SQLITE_DATABASE=:memory:
    BELGIE_SQLITE_ENABLE_FOREIGN_KEYS=true

    # PostgreSQL
    BELGIE_DATABASE_TYPE=postgres
    BELGIE_POSTGRES_HOST=localhost
    BELGIE_POSTGRES_PORT=5432
    BELGIE_POSTGRES_DATABASE=mydb
    BELGIE_POSTGRES_USERNAME=user
    BELGIE_POSTGRES_PASSWORD=pass
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


# ==================== SQLite Tests ====================


@pytest.mark.integration
def test_sqlite_from_env_minimal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test loading minimal SQLite configuration from environment variables."""
    monkeypatch.setenv("BELGIE_DATABASE_TYPE", "sqlite")
    monkeypatch.setenv("BELGIE_SQLITE_DATABASE", ":memory:")

    db = DatabaseSettings.from_env()

    assert db.dialect.type == "sqlite"
    assert db.dialect.database == ":memory:"
    assert db.dialect.enable_foreign_keys is True  # Default value
    assert db.dialect.echo is False  # Default value


@pytest.mark.integration
def test_sqlite_from_env_full(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test loading full SQLite configuration from environment variables."""
    monkeypatch.setenv("BELGIE_DATABASE_TYPE", "sqlite")
    monkeypatch.setenv("BELGIE_SQLITE_DATABASE", "/tmp/test.db")  # noqa: S108
    monkeypatch.setenv("BELGIE_SQLITE_ENABLE_FOREIGN_KEYS", "false")
    monkeypatch.setenv("BELGIE_SQLITE_ECHO", "true")

    db = DatabaseSettings.from_env()

    assert db.dialect.type == "sqlite"
    assert db.dialect.database == "/tmp/test.db"  # noqa: S108
    assert db.dialect.enable_foreign_keys is False
    assert db.dialect.echo is True


@pytest.mark.asyncio
@pytest.mark.integration
async def test_sqlite_from_env_creates_working_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that SQLite engine created from env vars works correctly."""
    monkeypatch.setenv("BELGIE_DATABASE_TYPE", "sqlite")
    monkeypatch.setenv("BELGIE_SQLITE_DATABASE", ":memory:")

    db = DatabaseSettings.from_env()

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
    monkeypatch.setenv("BELGIE_DATABASE_TYPE", "sqlite")
    monkeypatch.setenv("BELGIE_SQLITE_DATABASE", ":memory:")
    monkeypatch.setenv("BELGIE_SQLITE_ENABLE_FOREIGN_KEYS", "true")

    db = DatabaseSettings.from_env()

    async with db.engine.connect() as conn:
        result = await conn.execute(text("PRAGMA foreign_keys"))
        value = result.scalar_one()
        assert value == 1

    await db.engine.dispose()


@pytest.mark.integration
def test_sqlite_defaults_when_type_not_set(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that SQLite is used when BELGIE_DATABASE_TYPE is not set."""
    monkeypatch.setenv("BELGIE_SQLITE_DATABASE", ":memory:")

    db = DatabaseSettings.from_env()

    assert db.dialect.type == "sqlite"
    assert db.dialect.database == ":memory:"


# ==================== PostgreSQL Tests ====================


@pytest.mark.integration
def test_postgres_from_env_minimal(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test loading minimal PostgreSQL configuration from environment variables."""
    if not ASYNC_PG_AVAILABLE:
        pytest.skip("asyncpg not installed")

    monkeypatch.setenv("BELGIE_DATABASE_TYPE", "postgres")
    monkeypatch.setenv("BELGIE_POSTGRES_HOST", "localhost")
    monkeypatch.setenv("BELGIE_POSTGRES_DATABASE", "testdb")
    monkeypatch.setenv("BELGIE_POSTGRES_USERNAME", "testuser")
    monkeypatch.setenv("BELGIE_POSTGRES_PASSWORD", "testpass")

    db = DatabaseSettings.from_env()

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

    monkeypatch.setenv("BELGIE_DATABASE_TYPE", "postgres")
    monkeypatch.setenv("BELGIE_POSTGRES_HOST", "db.example.com")
    monkeypatch.setenv("BELGIE_POSTGRES_PORT", "5433")
    monkeypatch.setenv("BELGIE_POSTGRES_DATABASE", "mydb")
    monkeypatch.setenv("BELGIE_POSTGRES_USERNAME", "admin")
    monkeypatch.setenv("BELGIE_POSTGRES_PASSWORD", "secret123")
    monkeypatch.setenv("BELGIE_POSTGRES_POOL_SIZE", "20")
    monkeypatch.setenv("BELGIE_POSTGRES_MAX_OVERFLOW", "30")
    monkeypatch.setenv("BELGIE_POSTGRES_POOL_TIMEOUT", "60.0")
    monkeypatch.setenv("BELGIE_POSTGRES_POOL_RECYCLE", "7200")
    monkeypatch.setenv("BELGIE_POSTGRES_POOL_PRE_PING", "false")
    monkeypatch.setenv("BELGIE_POSTGRES_ECHO", "true")

    db = DatabaseSettings.from_env()

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

    monkeypatch.setenv("BELGIE_DATABASE_TYPE", "postgres")
    monkeypatch.setenv("BELGIE_POSTGRES_HOST", parsed.hostname or "localhost")
    monkeypatch.setenv("BELGIE_POSTGRES_PORT", str(parsed.port or 5432))
    monkeypatch.setenv("BELGIE_POSTGRES_DATABASE", parsed.path.lstrip("/") if parsed.path else "postgres")
    monkeypatch.setenv("BELGIE_POSTGRES_USERNAME", parsed.username or "postgres")
    monkeypatch.setenv("BELGIE_POSTGRES_PASSWORD", parsed.password or "")

    try:
        db = DatabaseSettings.from_env()

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


# ==================== Validation & Edge Cases ====================


@pytest.mark.integration
def test_missing_required_postgres_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that missing required PostgreSQL fields raise validation error."""
    if not ASYNC_PG_AVAILABLE:
        pytest.skip("asyncpg not installed")

    monkeypatch.setenv("BELGIE_DATABASE_TYPE", "postgres")
    monkeypatch.setenv("BELGIE_POSTGRES_HOST", "localhost")
    # Missing database, username, password

    with pytest.raises(ValidationError):
        DatabaseSettings.from_env()


@pytest.mark.integration
def test_invalid_port_number(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that invalid port number raises validation error."""
    if not ASYNC_PG_AVAILABLE:
        pytest.skip("asyncpg not installed")

    monkeypatch.setenv("BELGIE_DATABASE_TYPE", "postgres")
    monkeypatch.setenv("BELGIE_POSTGRES_HOST", "localhost")
    monkeypatch.setenv("BELGIE_POSTGRES_PORT", "-1")  # Invalid
    monkeypatch.setenv("BELGIE_POSTGRES_DATABASE", "testdb")
    monkeypatch.setenv("BELGIE_POSTGRES_USERNAME", "user")
    monkeypatch.setenv("BELGIE_POSTGRES_PASSWORD", "pass")

    with pytest.raises(ValidationError, match="Input should be greater than 0"):
        DatabaseSettings.from_env()


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
        monkeypatch.setenv("BELGIE_DATABASE_TYPE", "sqlite")
        monkeypatch.setenv("BELGIE_SQLITE_DATABASE", ":memory:")
        monkeypatch.setenv("BELGIE_SQLITE_ECHO", env_value)

        db = DatabaseSettings.from_env()
        assert db.dialect.echo is expected, f"Expected {expected} for env value '{env_value}'"


@pytest.mark.asyncio
@pytest.mark.integration
async def test_session_maker_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that session_maker created from env vars works correctly."""
    monkeypatch.setenv("BELGIE_DATABASE_TYPE", "sqlite")
    monkeypatch.setenv("BELGIE_SQLITE_DATABASE", ":memory:")

    db = DatabaseSettings.from_env()

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
    monkeypatch.setenv("BELGIE_DATABASE_TYPE", "sqlite")
    monkeypatch.setenv("BELGIE_SQLITE_DATABASE", ":memory:")

    db = DatabaseSettings.from_env()

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


# ==================== Mixed Configuration Tests ====================


@pytest.mark.integration
def test_can_override_with_direct_instantiation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that direct instantiation still works regardless of env vars."""
    # Set env vars that would load postgres
    monkeypatch.setenv("BELGIE_DATABASE_TYPE", "postgres")
    monkeypatch.setenv("BELGIE_POSTGRES_HOST", "localhost")
    monkeypatch.setenv("BELGIE_POSTGRES_DATABASE", "testdb")
    monkeypatch.setenv("BELGIE_POSTGRES_USERNAME", "user")
    monkeypatch.setenv("BELGIE_POSTGRES_PASSWORD", "pass")

    # But directly instantiate SQLite
    db = DatabaseSettings(dialect={"type": "sqlite", "database": ":memory:"})

    assert db.dialect.type == "sqlite"
    assert db.dialect.database == ":memory:"


@pytest.mark.integration
def test_from_env_vs_direct_instantiation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test the difference between from_env() and direct instantiation."""
    monkeypatch.setenv("BELGIE_DATABASE_TYPE", "sqlite")
    monkeypatch.setenv("BELGIE_SQLITE_DATABASE", "/tmp/from_env.db")  # noqa: S108
    monkeypatch.setenv("BELGIE_SQLITE_ECHO", "true")

    # from_env() reads environment variables
    db_from_env = DatabaseSettings.from_env()
    assert db_from_env.dialect.database == "/tmp/from_env.db"  # noqa: S108
    assert db_from_env.dialect.echo is True

    # Direct instantiation with explicit values overrides env vars
    db_direct = DatabaseSettings(dialect={"type": "sqlite", "database": ":memory:", "echo": False})
    assert db_direct.dialect.database == ":memory:"
    assert db_direct.dialect.echo is False


@pytest.mark.integration
def test_no_database_type_env_var_defaults_to_sqlite(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that missing BELGIE_DATABASE_TYPE defaults to SQLite."""
    # Don't set BELGIE_DATABASE_TYPE
    monkeypatch.setenv("BELGIE_SQLITE_DATABASE", ":memory:")

    db = DatabaseSettings.from_env()

    assert db.dialect.type == "sqlite"


@pytest.mark.integration
def test_postgres_connection_string_format(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that Postgres settings correctly build connection URL."""
    if not ASYNC_PG_AVAILABLE:
        pytest.skip("asyncpg not installed")

    monkeypatch.setenv("BELGIE_DATABASE_TYPE", "postgres")
    monkeypatch.setenv("BELGIE_POSTGRES_HOST", "testhost.example.com")
    monkeypatch.setenv("BELGIE_POSTGRES_PORT", "5433")
    monkeypatch.setenv("BELGIE_POSTGRES_DATABASE", "testdb")
    monkeypatch.setenv("BELGIE_POSTGRES_USERNAME", "testuser")
    monkeypatch.setenv("BELGIE_POSTGRES_PASSWORD", "testpass123")

    db = DatabaseSettings.from_env()

    # Verify URL components
    assert db.engine.url.get_backend_name() == "postgresql"
    assert db.engine.url.get_driver_name() == "asyncpg"
    assert db.engine.url.host == "testhost.example.com"
    assert db.engine.url.port == 5433
    assert db.engine.url.database == "testdb"
    assert db.engine.url.username == "testuser"


@pytest.mark.integration
def test_sqlite_missing_database_field(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test that SQLite requires database field."""
    monkeypatch.setenv("BELGIE_DATABASE_TYPE", "sqlite")
    # Missing BELGIE_SQLITE_DATABASE

    with pytest.raises(ValidationError):
        DatabaseSettings.from_env()
