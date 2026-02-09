from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from typing import TYPE_CHECKING, Literal, Self, cast

from pydantic import NonNegativeFloat, NonNegativeInt, PositiveInt, SecretStr  # noqa: TC002
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import event
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator, Callable
    from typing import Protocol

    from belgie_proto import DBConnection

    class DBAPICursor(Protocol):
        def execute(self, operation: str) -> object: ...
        def close(self) -> None: ...

    class DBAPIConnection(Protocol):
        def cursor(self) -> DBAPICursor: ...


@dataclass(slots=True, kw_only=True, frozen=True)
class SQLAlchemyRuntime:
    engine: AsyncEngine
    session_maker: async_sessionmaker[AsyncSession]

    async def dependency(self) -> AsyncGenerator[AsyncSession, None]:
        async with self.session_maker() as session:
            yield session


class PostgresSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BELGIE_POSTGRES_",
        env_file=".env",
        extra="ignore",
    )

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

    @cached_property
    def _runtime(self) -> SQLAlchemyRuntime:
        engine = create_async_engine(
            URL.create(
                "postgresql+asyncpg",
                username=self.username,
                password=self.password.get_secret_value(),
                host=self.host,
                port=self.port,
                database=self.database,
            ),
            echo=self.echo,
            pool_size=self.pool_size,
            max_overflow=self.max_overflow,
            pool_timeout=self.pool_timeout,
            pool_recycle=self.pool_recycle,
            pool_pre_ping=self.pool_pre_ping,
        )

        return SQLAlchemyRuntime(
            engine=engine,
            session_maker=async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False),
        )

    def __call__(self) -> SQLAlchemyRuntime:
        return self._runtime

    @property
    def engine(self) -> AsyncEngine:
        return self._runtime.engine

    @property
    def session_maker(self) -> async_sessionmaker[AsyncSession]:
        return self._runtime.session_maker

    @property
    def dependency(self) -> Callable[[], DBConnection | AsyncGenerator[DBConnection, None]]:
        return self._runtime.dependency

    @property
    def dialect(self) -> Self:
        return self


class SqliteSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="BELGIE_SQLITE_",
        env_file=".env",
        extra="ignore",
    )

    type: Literal["sqlite"] = "sqlite"
    database: str
    enable_foreign_keys: bool = True
    echo: bool = False

    @cached_property
    def _runtime(self) -> SQLAlchemyRuntime:
        connect_args = {"uri": True} if self.database.startswith("file:") else {}
        engine = create_async_engine(
            URL.create("sqlite+aiosqlite", database=self.database),
            echo=self.echo,
            connect_args=connect_args,
        )

        if self.enable_foreign_keys:

            @event.listens_for(engine.sync_engine, "connect")
            def _enable_foreign_keys(dbapi_conn: object, _connection_record: object) -> None:
                cursor = cast("DBAPIConnection", dbapi_conn).cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        return SQLAlchemyRuntime(
            engine=engine,
            session_maker=async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False),
        )

    def __call__(self) -> SQLAlchemyRuntime:
        return self._runtime

    @property
    def engine(self) -> AsyncEngine:
        return self._runtime.engine

    @property
    def session_maker(self) -> async_sessionmaker[AsyncSession]:
        return self._runtime.session_maker

    @property
    def dependency(self) -> Callable[[], DBConnection | AsyncGenerator[DBConnection, None]]:
        return self._runtime.dependency

    @property
    def dialect(self) -> Self:
        return self


type DatabaseBackendSettings = PostgresSettings | SqliteSettings
