from collections.abc import AsyncGenerator, Awaitable, Callable
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tests.fixtures.database import get_test_engine, get_test_session_factory
from tests.fixtures.models import Session, User


@pytest_asyncio.fixture
async def db_engine() -> AsyncGenerator[AsyncEngine, None]:
    engine = await get_test_engine()
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session_factory(db_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return await get_test_session_factory(db_engine)


@pytest_asyncio.fixture
async def db_session(db_session_factory: async_sessionmaker[AsyncSession]) -> AsyncGenerator[AsyncSession, None]:
    async with db_session_factory() as session:
        yield session


@pytest.fixture
def test_user_factory(db_session: AsyncSession) -> Callable[..., Awaitable[User]]:
    async def _create_user(
        email: str | None = None,
        *,
        email_verified: bool = True,
        name: str | None = "Test User",
        image: str | None = None,
        custom_field: str | None = None,
    ) -> User:
        user = User(
            id=uuid4(),
            email=email or f"test-{uuid4()}@example.com",
            email_verified=email_verified,
            name=name,
            image=image,
            custom_field=custom_field,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db_session.add(user)
        await db_session.commit()
        await db_session.refresh(user)
        return user

    return _create_user


@pytest.fixture
def test_session_factory(db_session: AsyncSession) -> Callable[..., Awaitable[Session]]:
    async def _create_session(
        user_id: str | None = None,
        expires_at: datetime | None = None,
        ip_address: str | None = "127.0.0.1",
        user_agent: str | None = "Test Agent",
    ) -> Session:
        session = Session(
            id=uuid4(),
            user_id=user_id or uuid4(),
            expires_at=expires_at or datetime.now(UTC) + timedelta(days=7),
            ip_address=ip_address,
            user_agent=user_agent,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db_session.add(session)
        await db_session.commit()
        await db_session.refresh(session)
        return session

    return _create_session
