from __future__ import annotations

from datetime import datetime  # noqa: TC003
from uuid import UUID  # noqa: TC003

from sqlalchemy import JSON, Boolean, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from belgie_alchemy import Base, DateTimeUTC, PrimaryKeyMixin


class OAuthClient(Base, PrimaryKeyMixin):
    __tablename__ = "oauth_clients"

    client_id: Mapped[str] = mapped_column(Text, unique=True, index=True)
    redirect_uris: Mapped[list[str]] = mapped_column(JSON)

    client_secret: Mapped[str | None] = mapped_column(Text, default=None)
    disabled: Mapped[bool] = mapped_column(Boolean, default=False)
    skip_consent: Mapped[bool | None] = mapped_column(Boolean, default=None)
    enable_end_session: Mapped[bool | None] = mapped_column(Boolean, default=None)
    scopes: Mapped[list[str] | None] = mapped_column(JSON, default=None)

    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="set null", onupdate="cascade"),
        nullable=True,
        default=None,
    )

    created_at: Mapped[datetime] = mapped_column(DateTimeUTC, default=func.now(), init=False)
    updated_at: Mapped[datetime] = mapped_column(DateTimeUTC, default=func.now(), onupdate=func.now(), init=False)

    name: Mapped[str | None] = mapped_column(Text, default=None)
    uri: Mapped[str | None] = mapped_column(Text, default=None)
    icon: Mapped[str | None] = mapped_column(Text, default=None)
    contacts: Mapped[list[str] | None] = mapped_column(JSON, default=None)
    tos: Mapped[str | None] = mapped_column(Text, default=None)
    policy: Mapped[str | None] = mapped_column(Text, default=None)

    software_id: Mapped[str | None] = mapped_column(Text, default=None)
    software_version: Mapped[str | None] = mapped_column(Text, default=None)
    software_statement: Mapped[str | None] = mapped_column(Text, default=None)

    post_logout_redirect_uris: Mapped[list[str] | None] = mapped_column(JSON, default=None)
    token_endpoint_auth_method: Mapped[str | None] = mapped_column(Text, default=None)
    grant_types: Mapped[list[str] | None] = mapped_column(JSON, default=None)
    response_types: Mapped[list[str] | None] = mapped_column(JSON, default=None)

    public: Mapped[bool | None] = mapped_column(Boolean, default=None)
    type: Mapped[str | None] = mapped_column(Text, default=None)

    reference_id: Mapped[str | None] = mapped_column(Text, default=None)
    metadata_payload: Mapped[dict[str, object] | None] = mapped_column("metadata", JSON, default=None)


class OAuthAuthorizationCode(Base, PrimaryKeyMixin):
    __tablename__ = "oauth_authorization_codes"

    code: Mapped[str] = mapped_column(Text, unique=True, index=True)
    client_id: Mapped[str] = mapped_column(
        ForeignKey("oauth_clients.client_id", ondelete="cascade", onupdate="cascade"),
        index=True,
    )
    redirect_uri: Mapped[str] = mapped_column(Text)
    redirect_uri_provided_explicitly: Mapped[bool] = mapped_column(Boolean)
    code_challenge: Mapped[str] = mapped_column(Text)
    scopes: Mapped[list[str]] = mapped_column(JSON)

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="cascade", onupdate="cascade"),
        index=True,
    )
    expires_at: Mapped[datetime] = mapped_column(DateTimeUTC)

    code_challenge_method: Mapped[str | None] = mapped_column(Text, default=None)
    session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="set null", onupdate="cascade"),
        nullable=True,
        default=None,
    )
    reference_id: Mapped[str | None] = mapped_column(Text, default=None)

    created_at: Mapped[datetime] = mapped_column(DateTimeUTC, default=func.now(), init=False)


class OAuthRefreshToken(Base, PrimaryKeyMixin):
    __tablename__ = "oauth_refresh_tokens"

    token: Mapped[str] = mapped_column(Text, unique=True, index=True)
    client_id: Mapped[str] = mapped_column(
        ForeignKey("oauth_clients.client_id", ondelete="cascade", onupdate="cascade"),
        index=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="cascade", onupdate="cascade"),
        index=True,
    )
    scopes: Mapped[list[str]] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTimeUTC)

    session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="set null", onupdate="cascade"),
        nullable=True,
        default=None,
    )
    reference_id: Mapped[str | None] = mapped_column(Text, default=None)
    revoked: Mapped[datetime | None] = mapped_column(DateTimeUTC, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTimeUTC, default=func.now(), init=False)


class OAuthAccessToken(Base, PrimaryKeyMixin):
    __tablename__ = "oauth_access_tokens"

    token: Mapped[str] = mapped_column(Text, unique=True, index=True)
    client_id: Mapped[str] = mapped_column(
        ForeignKey("oauth_clients.client_id", ondelete="cascade", onupdate="cascade"),
        index=True,
    )
    scopes: Mapped[list[str]] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(DateTimeUTC)

    session_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("sessions.id", ondelete="set null", onupdate="cascade"),
        nullable=True,
        default=None,
    )
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="set null", onupdate="cascade"),
        nullable=True,
        default=None,
    )
    reference_id: Mapped[str | None] = mapped_column(Text, default=None)
    refresh_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("oauth_refresh_tokens.id", ondelete="set null", onupdate="cascade"),
        nullable=True,
        default=None,
    )

    created_at: Mapped[datetime] = mapped_column(DateTimeUTC, default=func.now(), init=False)


class OAuthConsent(Base, PrimaryKeyMixin):
    __tablename__ = "oauth_consents"

    client_id: Mapped[str] = mapped_column(
        ForeignKey("oauth_clients.client_id", ondelete="cascade", onupdate="cascade"),
        index=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="cascade", onupdate="cascade"),
        index=True,
    )
    scopes: Mapped[list[str]] = mapped_column(JSON)

    reference_id: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = mapped_column(DateTimeUTC, default=func.now(), init=False)
    updated_at: Mapped[datetime] = mapped_column(DateTimeUTC, default=func.now(), onupdate=func.now(), init=False)
