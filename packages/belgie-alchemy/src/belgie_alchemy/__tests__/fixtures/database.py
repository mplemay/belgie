from collections.abc import AsyncGenerator

from brussels.base import DataclassBase
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


def _build_test_database_url(database: str) -> str:
    if database == ":memory:":
        return TEST_DATABASE_URL
    if database.startswith("file:"):
        return f"sqlite+aiosqlite:///{database}&uri=true"
    return f"sqlite+aiosqlite:///{database}"


async def get_test_engine(database: str = ":memory:") -> AsyncEngine:
    engine = create_async_engine(
        _build_test_database_url(database),
        echo=False,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_foreign_keys(dbapi_conn, _connection_record) -> None:
        cursor = dbapi_conn.cursor()
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
