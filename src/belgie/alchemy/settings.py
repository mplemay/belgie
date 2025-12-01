from __future__ import annotations

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
    model_config = SettingsConfigDict(extra="ignore")

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
    model_config = SettingsConfigDict(extra="ignore")

    type: Literal["sqlite"] = "sqlite"
    database: str
    enable_foreign_keys: bool = True
    echo: bool = False


class DatabaseSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BELGIE_DATABASE_",
        env_nested_delimiter="__",
        extra="ignore",
    )

    dialect: Annotated[PostgresSettings | SqliteSettings, Field(discriminator="type")]

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
