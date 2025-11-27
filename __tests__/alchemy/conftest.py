"""Test fixtures for belgie.alchemy tests.

Defines concrete auth models for testing. These mirror the examples in
examples/alchemy/auth_models.py and demonstrate how users would define
their own models.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003
from typing import TYPE_CHECKING
from uuid import UUID  # noqa: TC003

import pytest_asyncio
from sqlalchemy import ForeignKey, Text, UniqueConstraint, event
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Mapped, mapped_column, relationship

from belgie.alchemy import Base, DateTimeUTC, PrimaryKeyMixin, Scopes, TimestampMixin

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


class User(Base, PrimaryKeyMixin, TimestampMixin):
    """Test User model."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(unique=True, index=True)
    email_verified: Mapped[bool] = mapped_column(default=False)
    name: Mapped[str | None] = mapped_column(default=None)
    image: Mapped[str | None] = mapped_column(default=None)
    scopes: Mapped[list[str] | None] = mapped_column(Scopes, default=None)

    accounts: Mapped[list[Account]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        init=False,
    )
    sessions: Mapped[list[Session]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        init=False,
    )
    oauth_states: Mapped[list[OAuthState]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        init=False,
    )


class Account(Base, PrimaryKeyMixin, TimestampMixin):
    """Test Account model."""

    __tablename__ = "accounts"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="cascade", onupdate="cascade"),
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(Text)
    provider_account_id: Mapped[str] = mapped_column(Text)
    access_token: Mapped[str | None] = mapped_column(default=None)
    refresh_token: Mapped[str | None] = mapped_column(default=None)
    expires_at: Mapped[datetime | None] = mapped_column(DateTimeUTC, default=None)
    token_type: Mapped[str | None] = mapped_column(default=None)
    scope: Mapped[str | None] = mapped_column(default=None)
    id_token: Mapped[str | None] = mapped_column(default=None)

    user: Mapped[User] = relationship(
        back_populates="accounts",
        lazy="selectin",
        init=False,
    )

    __table_args__ = (
        UniqueConstraint(
            "provider",
            "provider_account_id",
            name="uq_accounts_provider_provider_account_id",
        ),
    )


class Session(Base, PrimaryKeyMixin, TimestampMixin):
    """Test Session model."""

    __tablename__ = "sessions"

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="cascade", onupdate="cascade"),
        nullable=False,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTimeUTC)
    ip_address: Mapped[str | None] = mapped_column(default=None)
    user_agent: Mapped[str | None] = mapped_column(default=None)

    user: Mapped[User] = relationship(
        back_populates="sessions",
        lazy="selectin",
        init=False,
    )


class OAuthState(Base, PrimaryKeyMixin, TimestampMixin):
    """Test OAuthState model."""

    __tablename__ = "oauth_states"

    state: Mapped[str] = mapped_column(unique=True, index=True)
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="set null", onupdate="cascade"),
        nullable=True,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTimeUTC)
    code_verifier: Mapped[str | None] = mapped_column(default=None)
    redirect_url: Mapped[str | None] = mapped_column(default=None)

    user: Mapped[User] | None = relationship(
        back_populates="oauth_states",
        lazy="selectin",
        init=False,
    )


@pytest_asyncio.fixture
async def alchemy_engine() -> AsyncGenerator[AsyncEngine, None]:
    """Create an isolated in-memory SQLite engine for testing.

    Each test gets its own in-memory database, so Base.metadata.create_all
    is safe even when tests run in parallel - there's no shared state.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)

    @event.listens_for(engine.sync_engine, "connect")
    def _enable_fk(dbapi_conn, _connection_record) -> None:
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def alchemy_session_factory(alchemy_engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(alchemy_engine, class_=AsyncSession, expire_on_commit=False)


@pytest_asyncio.fixture
async def alchemy_session(
    alchemy_session_factory: async_sessionmaker[AsyncSession],
) -> AsyncGenerator[AsyncSession, None]:
    async with alchemy_session_factory() as session:
        yield session


__all__ = ["Account", "OAuthState", "Session", "User", "alchemy_engine", "alchemy_session", "alchemy_session_factory"]
