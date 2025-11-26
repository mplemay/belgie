from __future__ import annotations

from datetime import datetime  # noqa: TC003
from uuid import UUID  # noqa: TC003

from sqlalchemy import Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from belgie.alchemy.base import Base
from belgie.alchemy.mixins import PrimaryKeyMixin, TimestampMixin
from belgie.alchemy.types import DateTimeUTC
from belgie.alchemy.utils import mapped_foreign_key


class AUser(Base, PrimaryKeyMixin, TimestampMixin):
    __abstract__ = True

    email: Mapped[str] = mapped_column(unique=True, index=True)
    email_verified: Mapped[bool] = mapped_column(default=False)
    name: Mapped[str | None] = mapped_column(nullable=True, default=None)
    image: Mapped[str | None] = mapped_column(nullable=True, default=None)
    # scopes intentionally omitted; platform-dependent


class Account(Base, PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "accounts"

    user_id: Mapped[UUID] = mapped_foreign_key(
        "users.id",
        ondelete="cascade",
        onupdate="cascade",
        primary_key=False,
        nullable=False,
    )
    provider: Mapped[str] = mapped_column(Text, nullable=False)
    provider_account_id: Mapped[str] = mapped_column(Text, nullable=False)
    access_token: Mapped[str | None] = mapped_column(nullable=True, default=None)
    refresh_token: Mapped[str | None] = mapped_column(nullable=True, default=None)
    expires_at: Mapped[datetime | None] = mapped_column(DateTimeUTC, nullable=True, default=None)
    token_type: Mapped[str | None] = mapped_column(nullable=True, default=None)
    scope: Mapped[str | None] = mapped_column(nullable=True, default=None)
    id_token: Mapped[str | None] = mapped_column(nullable=True, default=None)

    user: Mapped[AUser] = relationship("User", backref="accounts", lazy="selectin", init=False)

    __table_args__ = (
        UniqueConstraint("provider", "provider_account_id", name="uq_accounts_provider_provider_account_id"),
    )


class Session(Base, PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "sessions"

    user_id: Mapped[UUID] = mapped_foreign_key(
        "users.id",
        ondelete="cascade",
        onupdate="cascade",
        primary_key=False,
        nullable=False,
    )

    expires_at: Mapped[datetime] = mapped_column(DateTimeUTC)
    ip_address: Mapped[str | None] = mapped_column(nullable=True, default=None)
    user_agent: Mapped[str | None] = mapped_column(nullable=True, default=None)

    user: Mapped[AUser] = relationship("User", backref="sessions", lazy="selectin", init=False)


class OAuthState(Base, PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "oauth_states"

    state: Mapped[str] = mapped_column(unique=True, index=True)
    user_id: Mapped[UUID | None] = mapped_foreign_key(
        "users.id",
        ondelete="set null",
        onupdate="cascade",
        primary_key=False,
        nullable=True,
        unique=None,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTimeUTC)
    code_verifier: Mapped[str | None] = mapped_column(nullable=True, default=None)
    redirect_url: Mapped[str | None] = mapped_column(nullable=True, default=None)

    user: Mapped[AUser] = relationship("User", backref="oauth_states", lazy="selectin", init=False)
