from __future__ import annotations

import os
from functools import cached_property
from typing import TYPE_CHECKING, Annotated, Literal, cast

from pydantic import Field, NonNegativeFloat, NonNegativeInt, PositiveInt, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import event
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    import sqlite3
    from collections.abc import AsyncGenerator


class PostgresSettings(BaseSettings):
    """PostgreSQL database settings.

    Environment variables use the prefix: BELGIE_POSTGRES_
    Example: BELGIE_POSTGRES_HOST=localhost
    """

    model_config = SettingsConfigDict(env_prefix="BELGIE_POSTGRES_", extra="ignore")

    type: Literal["postgres"] = "postgres"
    host: str
    port: PositiveInt = 5432
    database: str
    username: str
    password: SecretStr
    pool_size: PositiveInt = 5
    max_overflow: NonNegativeInt = 10
    pool_timeout: NonNegativeFloat = 30.0
    pool_recycle: PositiveInt = 3600
    pool_pre_ping: bool = True
    echo: bool = False


class SqliteSettings(BaseSettings):
    """SQLite database settings.

    Environment variables use the prefix: BELGIE_SQLITE_
    Example: BELGIE_SQLITE_DATABASE=:memory:
    """

    model_config = SettingsConfigDict(env_prefix="BELGIE_SQLITE_", extra="ignore")

    type: Literal["sqlite"] = "sqlite"
    database: str
    enable_foreign_keys: bool = True
    echo: bool = False


class DatabaseSettings(BaseSettings):
    """Database settings with support for PostgreSQL and SQLite.

    Environment variables:
    - BELGIE_DATABASE_TYPE: "postgres" or "sqlite" (default: "sqlite")
    - For PostgreSQL: BELGIE_POSTGRES_HOST, BELGIE_POSTGRES_PORT, etc.
    - For SQLite: BELGIE_SQLITE_DATABASE, BELGIE_SQLITE_ENABLE_FOREIGN_KEYS, etc.

    Example usage:
        # From environment variables
        db = DatabaseSettings.from_env()

        # Direct instantiation
        db = DatabaseSettings(dialect={"type": "sqlite", "database": ":memory:"})
    """

    model_config = SettingsConfigDict(
        env_prefix="BELGIE_DATABASE_",
        extra="ignore",
    )

    dialect: Annotated[PostgresSettings | SqliteSettings, Field(discriminator="type")]

    @classmethod
    def from_env(cls) -> DatabaseSettings:
        """Load database settings from environment variables.

        Reads BELGIE_DATABASE_TYPE to determine which dialect to use,
        then loads the appropriate settings from BELGIE_POSTGRES_* or BELGIE_SQLITE_* vars.

        Returns:
            DatabaseSettings instance configured from environment variables.

        Example:
            # Set environment variables
            os.environ["BELGIE_DATABASE_TYPE"] = "postgres"
            os.environ["BELGIE_POSTGRES_HOST"] = "localhost"
            os.environ["BELGIE_POSTGRES_DATABASE"] = "mydb"
            # ... other postgres settings

            db = DatabaseSettings.from_env()
        """
        db_type = os.getenv("BELGIE_DATABASE_TYPE", "sqlite")

        if db_type == "postgres":
            return cls(dialect=PostgresSettings())  # type: ignore[call-arg]
        return cls(dialect=SqliteSettings())  # type: ignore[call-arg]

    @cached_property
    def engine(self) -> AsyncEngine:
        if self.dialect.type == "postgres":
            dialect = cast("PostgresSettings", self.dialect)
            url = URL.create(
                "postgresql+asyncpg",
                username=dialect.username,
                password=dialect.password.get_secret_value(),
                host=dialect.host,
                port=dialect.port,
                database=dialect.database,
            )
            return create_async_engine(
                url,
                echo=dialect.echo,
                pool_size=dialect.pool_size,
                max_overflow=dialect.max_overflow,
                pool_timeout=dialect.pool_timeout,
                pool_recycle=dialect.pool_recycle,
                pool_pre_ping=dialect.pool_pre_ping,
            )

        dialect = cast("SqliteSettings", self.dialect)
        url = URL.create("sqlite+aiosqlite", database=dialect.database)
        engine = create_async_engine(url, echo=dialect.echo)

        if dialect.enable_foreign_keys:

            @event.listens_for(engine.sync_engine, "connect")
            def _enable_foreign_keys(dbapi_conn: sqlite3.Connection, _conn_record: object) -> None:
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        return engine

    @cached_property
    def session_maker(self) -> async_sessionmaker[AsyncSession]:
        return async_sessionmaker(self.engine, class_=AsyncSession, expire_on_commit=False)

    async def dependency(self) -> AsyncGenerator[AsyncSession, None]:
        async with self.session_maker() as session:
            yield session
