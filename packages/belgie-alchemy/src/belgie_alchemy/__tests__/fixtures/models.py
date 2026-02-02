"""Test models for alchemy tests.

Defines concrete auth models for testing. These mirror the examples in
examples/alchemy/auth_models.py and demonstrate how users would define
their own models.
"""

from __future__ import annotations

from datetime import datetime  # noqa: TC003
from uuid import UUID  # noqa: TC003

from sqlalchemy import JSON, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from belgie_alchemy import Base, DateTimeUTC, PrimaryKeyMixin, TimestampMixin


class User(Base, PrimaryKeyMixin, TimestampMixin):
    """Test User model."""

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(unique=True, index=True)
    email_verified: Mapped[bool] = mapped_column(default=False)
    name: Mapped[str | None] = mapped_column(default=None)
    image: Mapped[str | None] = mapped_column(default=None)
    scopes: Mapped[list[str] | None] = mapped_column(JSON, default=None)
    custom_field: Mapped[str | None] = mapped_column(default=None)

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
