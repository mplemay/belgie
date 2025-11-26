"""Reference implementation of authentication models.

USAGE: Copy these models to your project and customize as needed.

These models demonstrate how to structure authentication with belgie.alchemy:
- User model with email, verification, and optional scopes
- Account model for OAuth provider linkage
- Session model for user sessions
- OAuthState model for OAuth flow state management

You can:
- Add custom fields to any model
- Change the scopes column type (e.g., use PostgreSQL ENUM arrays)
- Modify relationships or constraints
- Use different table names

These are templates, not meant to be imported directly from belgie.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from belgie.alchemy import Base, DateTimeUTC, PrimaryKeyMixin, Scopes, TimestampMixin

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


# Example: Define your application-specific scopes
class AppScope(StrEnum):
    """Example scope enum - customize for your application."""

    READ = "resource:read"
    WRITE = "resource:write"
    ADMIN = "admin"


class User(Base, PrimaryKeyMixin, TimestampMixin):
    """User model for authentication.

    Customize this model for your application:
    - Add custom fields (role, department, etc.)
    - Change scopes implementation (see Scopes Field Options below)
    - Add relationships to your domain models

    Scopes Field Options:

    Option 1 (current): Simple string array (works with all databases):
        scopes: Mapped[list[str] | None] = mapped_column(Scopes, default=None)

    Option 2: PostgreSQL native ENUM array (type-safe, PostgreSQL only):
        from sqlalchemy import ARRAY
        from sqlalchemy.dialects.postgresql import ENUM

        scopes: Mapped[list[AppScope] | None] = mapped_column(
            ARRAY(ENUM(AppScope, name="app_scope", create_type=True)),
            default=None,
        )

    Option 3: Same as Option 1, explicitly using JSON for non-PostgreSQL:
        scopes: Mapped[list[str] | None] = mapped_column(Scopes, default=None)
    """

    __tablename__ = "users"

    email: Mapped[str] = mapped_column(unique=True, index=True)
    email_verified: Mapped[bool] = mapped_column(default=False)
    name: Mapped[str | None] = mapped_column(default=None)
    image: Mapped[str | None] = mapped_column(default=None)
    scopes: Mapped[list[str] | None] = mapped_column(Scopes, default=None)

    # Bidirectional relationships
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
    """OAuth account linkage for users.

    Links a user to their OAuth provider accounts (Google, GitHub, etc.).
    """

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
    """User session storage.

    Tracks active user sessions with expiration and metadata.
    """

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
    """OAuth flow state management.

    Stores PKCE verifiers and state parameters for OAuth flows.
    """

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


__all__ = ["Account", "AppScope", "OAuthState", "Session", "User"]
