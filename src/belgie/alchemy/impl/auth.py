from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import ARRAY, ForeignKey, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from belgie.alchemy.base import Base
from belgie.alchemy.mixins import PrimaryKeyMixin, TimestampMixin
from belgie.alchemy.types import DateTimeUTC

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID


class AUser(Base, PrimaryKeyMixin, TimestampMixin):
    __abstract__ = True

    email: Mapped[str] = mapped_column(unique=True, index=True)
    email_verified: Mapped[bool] = mapped_column(default=False)
    name: Mapped[str | None] = mapped_column(nullable=True, default=None)
    image: Mapped[str | None] = mapped_column(nullable=True, default=None)
    scopes: Mapped[list[str] | None] = mapped_column(ARRAY(Text), nullable=True, default=None)


class Account(Base, PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "accounts"

    user_id: Mapped[UUID] = mapped_column(ForeignKey(AUser.id, ondelete="CASCADE"), index=True)
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    provider_account_id: Mapped[str] = mapped_column(Text, nullable=False)
    access_token: Mapped[str | None] = mapped_column(nullable=True, default=None)
    refresh_token: Mapped[str | None] = mapped_column(nullable=True, default=None)
    expires_at: Mapped[datetime | None] = mapped_column(DateTimeUTC, nullable=True, default=None)
    token_type: Mapped[str | None] = mapped_column(nullable=True, default=None)
    scope: Mapped[str | None] = mapped_column(nullable=True, default=None)
    id_token: Mapped[str | None] = mapped_column(nullable=True, default=None)

    user: Mapped[AUser] = relationship(backref="accounts", lazy="selectin", init=False)

    __table_args__ = (
        UniqueConstraint("provider", "provider_account_id", name="uq_accounts_provider_provider_account_id"),
    )


class Session(Base, PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "sessions"

    user_id: Mapped[UUID] = mapped_column(ForeignKey(AUser.id, ondelete="CASCADE"), index=True)

    expires_at: Mapped[datetime] = mapped_column(DateTimeUTC)
    ip_address: Mapped[str | None] = mapped_column(nullable=True, default=None)
    user_agent: Mapped[str | None] = mapped_column(nullable=True, default=None)

    user: Mapped[AUser] = relationship(backref="sessions", lazy="selectin", init=False)


class OAuthState(Base, PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "oauth_states"

    state: Mapped[str] = mapped_column(unique=True, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTimeUTC)
    code_verifier: Mapped[str | None] = mapped_column(nullable=True, default=None)
    redirect_url: Mapped[str | None] = mapped_column(nullable=True, default=None)

    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        default=None,
    )

    user: Mapped[AUser] = relationship(backref="oauth_states", lazy="selectin", init=False)
