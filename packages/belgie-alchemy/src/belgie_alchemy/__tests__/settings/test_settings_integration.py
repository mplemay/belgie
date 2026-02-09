from __future__ import annotations

import os
from importlib.util import find_spec
from urllib.parse import urlparse

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from belgie_alchemy.settings import PostgresSettings, SqliteSettings

ASYNC_PG_AVAILABLE = find_spec("asyncpg") is not None


def test_sqlite_from_env_minimal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BELGIE_SQLITE_DATABASE", ":memory:")

    settings = SqliteSettings()

    assert settings.type == "sqlite"
    assert settings.database == ":memory:"
    assert settings.enable_foreign_keys is True


def test_sqlite_from_env_full(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BELGIE_SQLITE_DATABASE", "/tmp/test.db")  # noqa: S108
    monkeypatch.setenv("BELGIE_SQLITE_ENABLE_FOREIGN_KEYS", "false")
    monkeypatch.setenv("BELGIE_SQLITE_ECHO", "true")

    settings = SqliteSettings()

    assert settings.database == "/tmp/test.db"  # noqa: S108
    assert settings.enable_foreign_keys is False
    assert settings.echo is True


@pytest.mark.asyncio
async def test_sqlite_from_env_creates_working_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BELGIE_SQLITE_DATABASE", ":memory:")

    settings = SqliteSettings()

    async with settings.engine.connect() as conn:
        result = await conn.execute(text("SELECT 42 as answer"))
        value = result.scalar_one()
        assert value == 42

    await settings.engine.dispose()


@pytest.mark.asyncio
async def test_sqlite_from_env_foreign_keys_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BELGIE_SQLITE_DATABASE", ":memory:")
    monkeypatch.setenv("BELGIE_SQLITE_ENABLE_FOREIGN_KEYS", "true")

    settings = SqliteSettings()

    async with settings.engine.connect() as conn:
        result = await conn.execute(text("PRAGMA foreign_keys"))
        value = result.scalar_one()
        assert value == 1

    await settings.engine.dispose()


def test_postgres_from_env_minimal(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BELGIE_POSTGRES_HOST", "localhost")
    monkeypatch.setenv("BELGIE_POSTGRES_DATABASE", "testdb")
    monkeypatch.setenv("BELGIE_POSTGRES_USERNAME", "testuser")
    monkeypatch.setenv("BELGIE_POSTGRES_PASSWORD", "testpass")

    settings = PostgresSettings()

    assert settings.type == "postgres"
    assert settings.host == "localhost"
    assert settings.database == "testdb"
    assert settings.username == "testuser"
    assert settings.password.get_secret_value() == "testpass"


def test_postgres_from_env_full(monkeypatch: pytest.MonkeyPatch) -> None:
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

    settings = PostgresSettings()

    assert settings.host == "db.example.com"
    assert settings.port == 5433
    assert settings.database == "mydb"
    assert settings.username == "admin"
    assert settings.pool_size == 20
    assert settings.max_overflow == 30
    assert settings.pool_timeout == 60.0
    assert settings.pool_recycle == 7200
    assert settings.pool_pre_ping is False
    assert settings.echo is True


@pytest.mark.asyncio
@pytest.mark.integration
async def test_postgres_from_env_actual_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    if not ASYNC_PG_AVAILABLE:
        pytest.skip("asyncpg not installed")

    test_url = os.getenv("POSTGRES_TEST_URL")
    if not test_url:
        pytest.skip("POSTGRES_TEST_URL not set - skipping integration test")

    parsed = urlparse(test_url)
    monkeypatch.setenv("BELGIE_POSTGRES_HOST", parsed.hostname or "localhost")
    monkeypatch.setenv("BELGIE_POSTGRES_PORT", str(parsed.port or 5432))
    monkeypatch.setenv("BELGIE_POSTGRES_DATABASE", parsed.path.lstrip("/") if parsed.path else "postgres")
    monkeypatch.setenv("BELGIE_POSTGRES_USERNAME", parsed.username or "postgres")
    monkeypatch.setenv("BELGIE_POSTGRES_PASSWORD", parsed.password or "")

    settings = PostgresSettings()

    async with settings.engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        assert result.scalar_one() == 1

    await settings.engine.dispose()


def test_missing_required_postgres_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BELGIE_POSTGRES_HOST", "localhost")

    with pytest.raises(ValidationError):
        PostgresSettings()


def test_invalid_postgres_values(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BELGIE_POSTGRES_HOST", "localhost")
    monkeypatch.setenv("BELGIE_POSTGRES_PORT", "-1")
    monkeypatch.setenv("BELGIE_POSTGRES_DATABASE", "testdb")
    monkeypatch.setenv("BELGIE_POSTGRES_USERNAME", "user")
    monkeypatch.setenv("BELGIE_POSTGRES_PASSWORD", "pass")

    with pytest.raises(ValidationError):
        PostgresSettings()


@pytest.mark.asyncio
async def test_session_maker_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BELGIE_SQLITE_DATABASE", ":memory:")

    settings = SqliteSettings()

    async with settings.session_maker() as session:
        assert isinstance(session, AsyncSession)

    await settings.engine.dispose()


@pytest.mark.asyncio
async def test_dependency_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BELGIE_SQLITE_DATABASE", ":memory:")

    settings = SqliteSettings()

    async for session in settings.dependency():
        assert isinstance(session, AsyncSession)
        break

    await settings.engine.dispose()


def test_direct_instantiation_takes_priority_over_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BELGIE_SQLITE_DATABASE", "/tmp/from_env.db")  # noqa: S108
    monkeypatch.setenv("BELGIE_SQLITE_ECHO", "true")

    settings = SqliteSettings(database=":memory:", echo=False)

    assert settings.database == ":memory:"
    assert settings.echo is False
