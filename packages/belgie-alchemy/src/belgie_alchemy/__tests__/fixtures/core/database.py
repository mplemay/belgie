from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING, cast

from brussels.base import DataclassBase
from sqlalchemy import event
from sqlalchemy.engine import URL
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

if TYPE_CHECKING:
    from typing import Protocol

    class DBAPICursor(Protocol):
        def execute(self, operation: str) -> object: ...
        def close(self) -> None: ...

    class DBAPIConnection(Protocol):
        def cursor(self) -> DBAPICursor: ...


def _sqlite_url(database: str) -> URL:
    if database.startswith("file:"):
        return URL.create("sqlite+aiosqlite", database=database, query={"uri": "true"})
    return URL.create("sqlite+aiosqlite", database=database)


async def get_test_engine(database: str = ":memory:") -> AsyncEngine:
    engine = create_async_engine(_sqlite_url(database), echo=False)

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_conn: object, _connection_record: object) -> None:
        cursor = cast("DBAPIConnection", dbapi_conn).cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(DataclassBase.metadata.create_all)
    return engine


async def get_test_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


async def get_test_db(session_factory: async_sessionmaker[AsyncSession]) -> AsyncGenerator[AsyncSession, None]:
    async with session_factory() as session:
        yield session
