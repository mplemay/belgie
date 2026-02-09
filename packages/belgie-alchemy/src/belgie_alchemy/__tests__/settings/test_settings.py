import os
from importlib.util import find_spec
from urllib.parse import urlparse

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from belgie_alchemy.settings import PostgresSettings, SQLAlchemyRuntime, SqliteSettings

ASYNC_PG_AVAILABLE = find_spec("asyncpg") is not None


@pytest.mark.asyncio
async def test_sqlite_engine_fk_enabled() -> None:
    settings = SqliteSettings(database=":memory:", enable_foreign_keys=True)

    async with settings.engine.connect() as conn:
        result = await conn.execute(text("PRAGMA foreign_keys"))
        value = result.scalar_one()

    assert value == 1
    await settings.engine.dispose()


@pytest.mark.asyncio
async def test_session_maker_expire_disabled() -> None:
    settings = SqliteSettings(database=":memory:")

    session_factory = settings.session_maker
    assert session_factory.kw["expire_on_commit"] is False

    async with session_factory() as session:
        assert isinstance(session, AsyncSession)

    await settings.engine.dispose()


@pytest.mark.asyncio
async def test_sqlite_fk_violations_raise_error() -> None:
    settings = SqliteSettings(database=":memory:", enable_foreign_keys=True)

    async with settings.engine.begin() as conn:
        await conn.execute(text("CREATE TABLE test_parents (id INTEGER PRIMARY KEY, name TEXT)"))
        await conn.execute(
            text(
                "CREATE TABLE test_children "
                "(id INTEGER PRIMARY KEY, parent_id INTEGER NOT NULL REFERENCES test_parents(id), name TEXT)",
            ),
        )

    async with settings.session_maker() as session:
        with pytest.raises(IntegrityError):  # noqa: PT012
            await session.execute(text("INSERT INTO test_children (id, parent_id, name) VALUES (1, 999, 'orphan')"))
            await session.commit()

    await settings.engine.dispose()


@pytest.mark.asyncio
async def test_dependency_yields_different_sessions() -> None:
    settings = SqliteSettings(database=":memory:")

    sessions = []
    async for session1 in settings.dependency():
        sessions.append(session1)
        break

    async for session2 in settings.dependency():
        sessions.append(session2)
        break

    assert len(sessions) == 2
    assert sessions[0] is not sessions[1]
    await settings.engine.dispose()


@pytest.mark.asyncio
async def test_dependency_handles_exceptions() -> None:
    settings = SqliteSettings(database=":memory:")
    message = "Simulated error"

    try:
        async for _session in settings.dependency():
            raise ValueError(message)  # noqa: TRY301
    except ValueError:
        pass

    async for session in settings.dependency():
        assert isinstance(session, AsyncSession)
        break

    await settings.engine.dispose()


def test_postgres_url_creation() -> None:
    if not ASYNC_PG_AVAILABLE:
        pytest.skip("asyncpg not installed; skip postgres engine test")

    settings = PostgresSettings(
        host="localhost",
        port=5432,
        database="belgie",
        username="user",
        password="secret",
    )

    assert settings.engine.url.get_backend_name() == "postgresql"
    assert settings.engine.url.get_driver_name() == "asyncpg"
    assert settings.engine.url.username == "user"
    assert settings.engine.url.host == "localhost"
    assert settings.engine.url.database == "belgie"
    assert settings.engine.url.port == 5432


def test_postgres_settings_validation() -> None:
    settings = PostgresSettings(
        host="db.example.com",
        port=5433,
        database="testdb",
        username="testuser",
        password="testpass",
        pool_size=10,
        max_overflow=20,
    )

    assert settings.type == "postgres"
    assert settings.host == "db.example.com"
    assert settings.port == 5433
    assert settings.database == "testdb"
    assert settings.username == "testuser"
    assert settings.password.get_secret_value() == "testpass"
    assert settings.pool_size == 10
    assert settings.max_overflow == 20


def test_sqlite_settings_validation() -> None:
    settings = SqliteSettings(
        database="/tmp/test.db",  # noqa: S108
        enable_foreign_keys=False,
        echo=True,
    )

    assert settings.type == "sqlite"
    assert settings.database == "/tmp/test.db"  # noqa: S108
    assert settings.enable_foreign_keys is False
    assert settings.echo is True


def test_runtime_is_cached_per_settings_instance() -> None:
    settings = SqliteSettings(database=":memory:")

    runtime = settings()
    assert isinstance(runtime, SQLAlchemyRuntime)
    assert runtime is settings()
    assert runtime.engine is settings.engine
    assert runtime.session_maker is settings.session_maker


@pytest.mark.asyncio
async def test_sqlite_file_uri_works() -> None:
    settings = SqliteSettings(database="file:belgie_test?mode=memory&cache=shared")

    async with settings.engine.connect() as conn:
        result = await conn.execute(text("SELECT 1"))
        assert result.scalar_one() == 1
    await settings.engine.dispose()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_postgres_engine_connection() -> None:
    if not ASYNC_PG_AVAILABLE:
        pytest.skip("asyncpg not installed")

    test_url = os.getenv("POSTGRES_TEST_URL")
    if not test_url:
        pytest.skip("POSTGRES_TEST_URL not set - skipping integration test")

    parsed = urlparse(test_url)
    settings = PostgresSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 5432,
        database=parsed.path.lstrip("/") if parsed.path else "postgres",
        username=parsed.username or "postgres",
        password=parsed.password or "",
    )

    async with settings.engine.connect() as conn:
        result = await conn.execute(text("SELECT 1 as test"))
        value = result.scalar_one()
        assert value == 1

    await settings.engine.dispose()


def test_postgres_requires_required_fields() -> None:
    with pytest.raises(ValidationError):
        PostgresSettings(host="localhost")  # type: ignore[call-arg]
