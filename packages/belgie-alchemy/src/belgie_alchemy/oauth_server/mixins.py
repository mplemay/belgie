from __future__ import annotations

# ruff: noqa: TC002, TC003
from datetime import datetime
from uuid import UUID

from belgie_proto.oauth_server.types import AuthorizationIntent
from brussels.types import DateTimeUTC, Json
from sqlalchemy import JSON, BigInteger, Boolean, Enum, ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, MappedAsDataclass, declarative_mixin, declared_attr, mapped_column

AuthorizationIntentEnum = Enum(
    "login",
    "create",
    "consent",
    "select_account",
    name="oauth_authorization_intent",
    native_enum=False,
)


def _string_list_column(
    *,
    nullable: bool,
    default_factory: object | None = None,
    default: object | None = None,
) -> object:
    list_type = JSON().with_variant(ARRAY(Text()), "postgresql")
    kwargs: dict[str, object] = {
        "nullable": nullable,
        "kw_only": True,
    }
    if default_factory is not None:
        kwargs["default_factory"] = default_factory
    if default is not None or nullable:
        kwargs["default"] = default
    return mapped_column(list_type, **kwargs)


@declarative_mixin
class OAuthClientMixin(MappedAsDataclass):
    __tablename__ = "oauth_client"

    @declared_attr
    def client_id(self) -> Mapped[str]:
        return mapped_column(Text, unique=True, index=True, kw_only=True)

    @declared_attr
    def client_secret_hash(self) -> Mapped[str | None]:
        return mapped_column(Text, default=None, kw_only=True)

    @declared_attr
    def redirect_uris(self) -> Mapped[list[str]]:
        return _string_list_column(nullable=False, default_factory=list)

    @declared_attr
    def post_logout_redirect_uris(self) -> Mapped[list[str] | None]:
        return _string_list_column(nullable=True, default=None)

    @declared_attr
    def token_endpoint_auth_method(self) -> Mapped[str]:
        return mapped_column(Text, kw_only=True)

    @declared_attr
    def grant_types(self) -> Mapped[list[str]]:
        return _string_list_column(nullable=False, default_factory=list)

    @declared_attr
    def response_types(self) -> Mapped[list[str]]:
        return _string_list_column(nullable=False, default_factory=list)

    @declared_attr
    def scope(self) -> Mapped[str | None]:
        return mapped_column(Text, default=None, kw_only=True)

    @declared_attr
    def client_name(self) -> Mapped[str | None]:
        return mapped_column(Text, default=None, kw_only=True)

    @declared_attr
    def client_uri(self) -> Mapped[str | None]:
        return mapped_column(Text, default=None, kw_only=True)

    @declared_attr
    def logo_uri(self) -> Mapped[str | None]:
        return mapped_column(Text, default=None, kw_only=True)

    @declared_attr
    def contacts(self) -> Mapped[list[str] | None]:
        return _string_list_column(nullable=True, default=None)

    @declared_attr
    def tos_uri(self) -> Mapped[str | None]:
        return mapped_column(Text, default=None, kw_only=True)

    @declared_attr
    def policy_uri(self) -> Mapped[str | None]:
        return mapped_column(Text, default=None, kw_only=True)

    @declared_attr
    def jwks_uri(self) -> Mapped[str | None]:
        return mapped_column(Text, default=None, kw_only=True)

    @declared_attr
    def jwks(self) -> Mapped[dict[str, str] | dict[str, object] | None]:
        return mapped_column(Json, default=None, kw_only=True)

    @declared_attr
    def software_id(self) -> Mapped[str | None]:
        return mapped_column(Text, default=None, kw_only=True)

    @declared_attr
    def software_version(self) -> Mapped[str | None]:
        return mapped_column(Text, default=None, kw_only=True)

    @declared_attr
    def software_statement(self) -> Mapped[str | None]:
        return mapped_column(Text, default=None, kw_only=True)

    @declared_attr
    def type(self) -> Mapped[str | None]:
        return mapped_column(Text, default=None, kw_only=True)

    @declared_attr
    def subject_type(self) -> Mapped[str | None]:
        return mapped_column(Text, default=None, kw_only=True)

    @declared_attr
    def require_pkce(self) -> Mapped[bool | None]:
        return mapped_column(Boolean, default=None, kw_only=True)

    @declared_attr
    def enable_end_session(self) -> Mapped[bool | None]:
        return mapped_column(Boolean, default=None, kw_only=True)

    @declared_attr
    def client_id_issued_at(self) -> Mapped[int | None]:
        return mapped_column(BigInteger, default=None, kw_only=True)

    @declared_attr
    def client_secret_expires_at(self) -> Mapped[int | None]:
        return mapped_column(BigInteger, default=None, kw_only=True)

    @declared_attr
    def individual_id(self) -> Mapped[UUID | None]:
        return mapped_column(
            ForeignKey("individual.id", ondelete="set null", onupdate="cascade"),
            default=None,
            nullable=True,
            kw_only=True,
        )


@declarative_mixin
class OAuthAuthorizationStateMixin(MappedAsDataclass):
    __tablename__ = "oauth_authorization_state"

    @declared_attr
    def state(self) -> Mapped[str]:
        return mapped_column(Text, unique=True, index=True, kw_only=True)

    @declared_attr
    def client_id(self) -> Mapped[str]:
        return mapped_column(Text, index=True, kw_only=True)

    @declared_attr
    def redirect_uri(self) -> Mapped[str]:
        return mapped_column(Text, kw_only=True)

    @declared_attr
    def redirect_uri_provided_explicitly(self) -> Mapped[bool]:
        return mapped_column(Boolean, kw_only=True)

    @declared_attr
    def code_challenge(self) -> Mapped[str | None]:
        return mapped_column(Text, default=None, kw_only=True)

    @declared_attr
    def resource(self) -> Mapped[str | None]:
        return mapped_column(Text, default=None, kw_only=True)

    @declared_attr
    def scopes(self) -> Mapped[list[str] | None]:
        return _string_list_column(nullable=True, default=None)

    @declared_attr
    def nonce(self) -> Mapped[str | None]:
        return mapped_column(Text, default=None, kw_only=True)

    @declared_attr
    def prompt(self) -> Mapped[str | None]:
        return mapped_column(Text, default=None, kw_only=True)

    @declared_attr
    def intent(self) -> Mapped[AuthorizationIntent]:
        return mapped_column(AuthorizationIntentEnum, kw_only=True)

    @declared_attr
    def individual_id(self) -> Mapped[UUID | None]:
        return mapped_column(
            ForeignKey("individual.id", ondelete="set null", onupdate="cascade"),
            default=None,
            nullable=True,
            kw_only=True,
        )

    @declared_attr
    def session_id(self) -> Mapped[UUID | None]:
        return mapped_column(
            ForeignKey("session.id", ondelete="set null", onupdate="cascade"),
            default=None,
            nullable=True,
            kw_only=True,
        )

    @declared_attr
    def expires_at(self) -> Mapped[datetime]:
        return mapped_column(DateTimeUTC, index=True, kw_only=True)


@declarative_mixin
class OAuthAuthorizationCodeMixin(MappedAsDataclass):
    __tablename__ = "oauth_authorization_code"

    @declared_attr
    def code_hash(self) -> Mapped[str]:
        return mapped_column(Text, unique=True, index=True, kw_only=True)

    @declared_attr
    def client_id(self) -> Mapped[str]:
        return mapped_column(Text, index=True, kw_only=True)

    @declared_attr
    def redirect_uri(self) -> Mapped[str]:
        return mapped_column(Text, kw_only=True)

    @declared_attr
    def redirect_uri_provided_explicitly(self) -> Mapped[bool]:
        return mapped_column(Boolean, kw_only=True)

    @declared_attr
    def code_challenge(self) -> Mapped[str | None]:
        return mapped_column(Text, default=None, kw_only=True)

    @declared_attr
    def scopes(self) -> Mapped[list[str]]:
        return _string_list_column(nullable=False, default_factory=list)

    @declared_attr
    def resource(self) -> Mapped[str | None]:
        return mapped_column(Text, default=None, kw_only=True)

    @declared_attr
    def nonce(self) -> Mapped[str | None]:
        return mapped_column(Text, default=None, kw_only=True)

    @declared_attr
    def individual_id(self) -> Mapped[UUID | None]:
        return mapped_column(
            ForeignKey("individual.id", ondelete="set null", onupdate="cascade"),
            default=None,
            nullable=True,
            kw_only=True,
        )

    @declared_attr
    def session_id(self) -> Mapped[UUID | None]:
        return mapped_column(
            ForeignKey("session.id", ondelete="set null", onupdate="cascade"),
            default=None,
            nullable=True,
            kw_only=True,
        )

    @declared_attr
    def expires_at(self) -> Mapped[datetime]:
        return mapped_column(DateTimeUTC, index=True, kw_only=True)


@declarative_mixin
class OAuthAccessTokenMixin(MappedAsDataclass):
    __tablename__ = "oauth_access_token"

    @declared_attr
    def token_hash(self) -> Mapped[str]:
        return mapped_column(Text, unique=True, index=True, kw_only=True)

    @declared_attr
    def client_id(self) -> Mapped[str]:
        return mapped_column(Text, index=True, kw_only=True)

    @declared_attr
    def scopes(self) -> Mapped[list[str]]:
        return _string_list_column(nullable=False, default_factory=list)

    @declared_attr
    def resource(self) -> Mapped[str | list[str] | None]:
        return mapped_column(Json, default=None, kw_only=True)

    @declared_attr
    def refresh_token_id(self) -> Mapped[UUID | None]:
        return mapped_column(
            ForeignKey("oauth_refresh_token.id", ondelete="set null", onupdate="cascade"),
            default=None,
            nullable=True,
            kw_only=True,
        )

    @declared_attr
    def individual_id(self) -> Mapped[UUID | None]:
        return mapped_column(
            ForeignKey("individual.id", ondelete="set null", onupdate="cascade"),
            default=None,
            nullable=True,
            kw_only=True,
        )

    @declared_attr
    def session_id(self) -> Mapped[UUID | None]:
        return mapped_column(
            ForeignKey("session.id", ondelete="set null", onupdate="cascade"),
            default=None,
            nullable=True,
            kw_only=True,
        )

    @declared_attr
    def expires_at(self) -> Mapped[datetime]:
        return mapped_column(DateTimeUTC, index=True, kw_only=True)

    @declared_attr.directive
    def __table_args__(self) -> tuple[Index, Index]:
        return (
            Index("ix_oauth_access_token_client_id_individual_id", self.client_id, self.individual_id),
            Index("ix_oauth_access_token_refresh_token_id", self.refresh_token_id),
        )


@declarative_mixin
class OAuthRefreshTokenMixin(MappedAsDataclass):
    __tablename__ = "oauth_refresh_token"

    @declared_attr
    def token_hash(self) -> Mapped[str]:
        return mapped_column(Text, unique=True, index=True, kw_only=True)

    @declared_attr
    def client_id(self) -> Mapped[str]:
        return mapped_column(Text, index=True, kw_only=True)

    @declared_attr
    def scopes(self) -> Mapped[list[str]]:
        return _string_list_column(nullable=False, default_factory=list)

    @declared_attr
    def resource(self) -> Mapped[str | None]:
        return mapped_column(Text, default=None, kw_only=True)

    @declared_attr
    def individual_id(self) -> Mapped[UUID | None]:
        return mapped_column(
            ForeignKey("individual.id", ondelete="set null", onupdate="cascade"),
            default=None,
            nullable=True,
            kw_only=True,
        )

    @declared_attr
    def session_id(self) -> Mapped[UUID | None]:
        return mapped_column(
            ForeignKey("session.id", ondelete="set null", onupdate="cascade"),
            default=None,
            nullable=True,
            kw_only=True,
        )

    @declared_attr
    def expires_at(self) -> Mapped[datetime]:
        return mapped_column(DateTimeUTC, index=True, kw_only=True)

    @declared_attr
    def revoked_at(self) -> Mapped[datetime | None]:
        return mapped_column(DateTimeUTC, default=None, kw_only=True)

    @declared_attr.directive
    def __table_args__(self) -> tuple[Index]:
        return (Index("ix_oauth_refresh_token_client_id_individual_id", self.client_id, self.individual_id),)


@declarative_mixin
class OAuthConsentMixin(MappedAsDataclass):
    __tablename__ = "oauth_consent"

    @declared_attr
    def client_id(self) -> Mapped[str]:
        return mapped_column(Text, index=True, kw_only=True)

    @declared_attr
    def individual_id(self) -> Mapped[UUID]:
        return mapped_column(
            ForeignKey("individual.id", ondelete="cascade", onupdate="cascade"),
            index=True,
            kw_only=True,
        )

    @declared_attr
    def scopes(self) -> Mapped[list[str]]:
        return _string_list_column(nullable=False, default_factory=list)

    @declared_attr.directive
    def __table_args__(self) -> tuple[UniqueConstraint]:
        return (
            UniqueConstraint(
                self.client_id,
                self.individual_id,
                name="uq_oauth_consent_client_id_individual_id",
            ),
        )


__all__ = [
    "OAuthAccessTokenMixin",
    "OAuthAuthorizationCodeMixin",
    "OAuthAuthorizationStateMixin",
    "OAuthClientMixin",
    "OAuthConsentMixin",
    "OAuthRefreshTokenMixin",
]
