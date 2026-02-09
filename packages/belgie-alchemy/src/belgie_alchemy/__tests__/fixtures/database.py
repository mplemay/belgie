from collections.abc import AsyncGenerator

from brussels.base import DataclassBase
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from belgie_alchemy.settings import SqliteSettings


async def get_test_engine(database: str = ":memory:") -> AsyncEngine:
    settings = SqliteSettings(database=database, echo=False, enable_foreign_keys=True)
    engine = settings.engine

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
