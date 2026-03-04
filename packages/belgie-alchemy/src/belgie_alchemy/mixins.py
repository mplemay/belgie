from __future__ import annotations

from datetime import datetime  # noqa: TC003
from uuid import UUID  # noqa: TC003

from brussels.mixins import PrimaryKeyMixin, TimestampMixin
from brussels.types import DateTimeUTC, Json
from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, declared_attr, mapped_column, relationship


class UserMixin(PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "user"

    @declared_attr
    def email(self) -> Mapped[str]:
        email_type = String().with_variant(CITEXT(), "postgresql")
        return mapped_column(email_type, unique=True, index=True, kw_only=True)

    @declared_attr
    def email_verified(self) -> Mapped[bool]:
        return mapped_column(default=False, kw_only=True)

    @declared_attr
    def name(self) -> Mapped[str | None]:
        return mapped_column(default=None, kw_only=True)

    @declared_attr
    def image(self) -> Mapped[str | None]:
        return mapped_column(default=None, kw_only=True)

    @declared_attr
    def scopes(self) -> Mapped[list[str] | None]:
        return mapped_column(Json, default=None, kw_only=True)

    @declared_attr
    def accounts(self) -> Mapped[list[object]]:
        return relationship(
            "Account",
            back_populates="user",
            cascade="all, delete-orphan",
            init=False,
        )

    @declared_attr
    def sessions(self) -> Mapped[list[object]]:
        return relationship(
            "Session",
            back_populates="user",
            cascade="all, delete-orphan",
            init=False,
        )

    @declared_attr
    def oauth_states(self) -> Mapped[list[object]]:
        return relationship(
            "OAuthState",
            back_populates="user",
            cascade="all, delete-orphan",
            init=False,
        )


class AccountMixin(PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "account"

    @declared_attr
    def user_id(self) -> Mapped[UUID]:
        return mapped_column(
            ForeignKey("user.id", ondelete="cascade", onupdate="cascade"),
            nullable=False,
            kw_only=True,
        )

    @declared_attr
    def provider(self) -> Mapped[str]:
        provider_type = Text().with_variant(CITEXT(), "postgresql")
        return mapped_column(provider_type, kw_only=True)

    @declared_attr
    def provider_account_id(self) -> Mapped[str]:
        provider_account_id_type = Text().with_variant(CITEXT(), "postgresql")
        return mapped_column(provider_account_id_type, kw_only=True)

    @declared_attr
    def access_token(self) -> Mapped[str | None]:
        return mapped_column(default=None, kw_only=True)

    @declared_attr
    def refresh_token(self) -> Mapped[str | None]:
        return mapped_column(default=None, kw_only=True)

    @declared_attr
    def expires_at(self) -> Mapped[datetime | None]:
        return mapped_column(DateTimeUTC, default=None, kw_only=True)

    @declared_attr
    def token_type(self) -> Mapped[str | None]:
        return mapped_column(default=None, kw_only=True)

    @declared_attr
    def scope(self) -> Mapped[str | None]:
        return mapped_column(default=None, kw_only=True)

    @declared_attr
    def id_token(self) -> Mapped[str | None]:
        return mapped_column(default=None, kw_only=True)

    @declared_attr
    def user(self) -> Mapped[object]:
        return relationship(
            "User",
            back_populates="accounts",
            lazy="selectin",
            init=False,
        )

    @declared_attr.directive
    def __table_args__(self) -> tuple[UniqueConstraint]:
        return (
            UniqueConstraint(
                "provider",
                "provider_account_id",
                name="uq_accounts_provider_provider_account_id",
            ),
        )


class SessionMixin(PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "session"

    @declared_attr
    def user_id(self) -> Mapped[UUID]:
        return mapped_column(
            ForeignKey("user.id", ondelete="cascade", onupdate="cascade"),
            nullable=False,
            kw_only=True,
        )

    @declared_attr
    def expires_at(self) -> Mapped[datetime]:
        return mapped_column(DateTimeUTC, kw_only=True)

    @declared_attr
    def ip_address(self) -> Mapped[str | None]:
        return mapped_column(default=None, kw_only=True)

    @declared_attr
    def user_agent(self) -> Mapped[str | None]:
        return mapped_column(default=None, kw_only=True)

    @declared_attr
    def user(self) -> Mapped[object]:
        return relationship(
            "User",
            back_populates="sessions",
            lazy="selectin",
            init=False,
        )


class OAuthStateMixin(PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "oauth_state"

    @declared_attr
    def state(self) -> Mapped[str]:
        return mapped_column(unique=True, index=True, kw_only=True)

    @declared_attr
    def user_id(self) -> Mapped[UUID | None]:
        return mapped_column(
            ForeignKey("user.id", ondelete="set null", onupdate="cascade"),
            nullable=True,
            kw_only=True,
        )

    @declared_attr
    def expires_at(self) -> Mapped[datetime]:
        return mapped_column(DateTimeUTC, kw_only=True)

    @declared_attr
    def code_verifier(self) -> Mapped[str | None]:
        return mapped_column(default=None, kw_only=True)

    @declared_attr
    def redirect_url(self) -> Mapped[str | None]:
        return mapped_column(default=None, kw_only=True)

    @declared_attr
    def user(self) -> Mapped[object | None]:
        return relationship(
            "User",
            back_populates="oauth_states",
            lazy="selectin",
            init=False,
        )


class OrganizationMixin(PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "organization"

    @declared_attr
    def name(self) -> Mapped[str]:
        return mapped_column(kw_only=True)

    @declared_attr
    def slug(self) -> Mapped[str]:
        slug_type = Text().with_variant(CITEXT(), "postgresql")
        return mapped_column(slug_type, unique=True, index=True, kw_only=True)

    @declared_attr
    def logo(self) -> Mapped[str | None]:
        return mapped_column(default=None, kw_only=True)

    @declared_attr
    def organization_metadata(self) -> Mapped[dict[str, object] | None]:
        return mapped_column("metadata", Json, default=None, kw_only=True)

    @declared_attr
    def members(self) -> Mapped[list[object]]:
        return relationship(
            "OrganizationMember",
            back_populates="organization",
            cascade="all, delete-orphan",
            init=False,
        )

    @declared_attr
    def invitations(self) -> Mapped[list[object]]:
        return relationship(
            "OrganizationInvitation",
            back_populates="organization",
            cascade="all, delete-orphan",
            init=False,
        )


class OrganizationMemberMixin(PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "organization_member"

    @declared_attr
    def organization_id(self) -> Mapped[UUID]:
        return mapped_column(
            ForeignKey("organization.id", ondelete="cascade", onupdate="cascade"),
            nullable=False,
            kw_only=True,
        )

    @declared_attr
    def user_id(self) -> Mapped[UUID]:
        return mapped_column(
            ForeignKey("user.id", ondelete="cascade", onupdate="cascade"),
            nullable=False,
            kw_only=True,
        )

    @declared_attr
    def role(self) -> Mapped[str]:
        return mapped_column(default="member", kw_only=True)

    @declared_attr
    def organization(self) -> Mapped[object]:
        return relationship(
            "Organization",
            back_populates="members",
            lazy="selectin",
            init=False,
        )

    @declared_attr
    def user(self) -> Mapped[object]:
        return relationship(
            "User",
            lazy="selectin",
            init=False,
        )

    @declared_attr.directive
    def __table_args__(self) -> tuple[UniqueConstraint]:
        return (
            UniqueConstraint(
                "organization_id",
                "user_id",
                name="uq_organization_member_org_user",
            ),
        )


class OrganizationInvitationMixin(PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "organization_invitation"

    @declared_attr
    def organization_id(self) -> Mapped[UUID]:
        return mapped_column(
            ForeignKey("organization.id", ondelete="cascade", onupdate="cascade"),
            nullable=False,
            kw_only=True,
        )

    @declared_attr
    def email(self) -> Mapped[str]:
        email_type = Text().with_variant(CITEXT(), "postgresql")
        return mapped_column(email_type, index=True, kw_only=True)

    @declared_attr
    def role(self) -> Mapped[str]:
        return mapped_column(default="member", kw_only=True)

    @declared_attr
    def status(self) -> Mapped[str]:
        return mapped_column(default="pending", index=True, kw_only=True)

    @declared_attr
    def inviter_id(self) -> Mapped[UUID]:
        return mapped_column(
            ForeignKey("user.id", ondelete="cascade", onupdate="cascade"),
            nullable=False,
            kw_only=True,
        )

    @declared_attr
    def expires_at(self) -> Mapped[datetime]:
        return mapped_column(DateTimeUTC, kw_only=True)

    @declared_attr
    def organization(self) -> Mapped[object]:
        return relationship(
            "Organization",
            back_populates="invitations",
            lazy="selectin",
            init=False,
        )

    @declared_attr
    def inviter(self) -> Mapped[object]:
        return relationship(
            "User",
            lazy="selectin",
            init=False,
        )


class TeamMixin(PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "team"

    @declared_attr
    def name(self) -> Mapped[str]:
        return mapped_column(kw_only=True)

    @declared_attr
    def organization_id(self) -> Mapped[UUID]:
        return mapped_column(
            ForeignKey("organization.id", ondelete="cascade", onupdate="cascade"),
            nullable=False,
            index=True,
            kw_only=True,
        )

    @declared_attr
    def organization(self) -> Mapped[object]:
        return relationship(
            "Organization",
            lazy="selectin",
            init=False,
        )

    @declared_attr
    def members(self) -> Mapped[list[object]]:
        return relationship(
            "TeamMember",
            back_populates="team",
            cascade="all, delete-orphan",
            init=False,
        )

    @declared_attr.directive
    def __table_args__(self) -> tuple[UniqueConstraint]:
        return (
            UniqueConstraint(
                "organization_id",
                "name",
                name="uq_team_org_name",
            ),
        )


class TeamMemberMixin(PrimaryKeyMixin, TimestampMixin):
    __tablename__ = "team_member"

    @declared_attr
    def team_id(self) -> Mapped[UUID]:
        return mapped_column(
            ForeignKey("team.id", ondelete="cascade", onupdate="cascade"),
            nullable=False,
            index=True,
            kw_only=True,
        )

    @declared_attr
    def user_id(self) -> Mapped[UUID]:
        return mapped_column(
            ForeignKey("user.id", ondelete="cascade", onupdate="cascade"),
            nullable=False,
            index=True,
            kw_only=True,
        )

    @declared_attr
    def team(self) -> Mapped[object]:
        return relationship(
            "Team",
            back_populates="members",
            lazy="selectin",
            init=False,
        )

    @declared_attr
    def user(self) -> Mapped[object]:
        return relationship(
            "User",
            lazy="selectin",
            init=False,
        )

    @declared_attr.directive
    def __table_args__(self) -> tuple[UniqueConstraint]:
        return (
            UniqueConstraint(
                "team_id",
                "user_id",
                name="uq_team_member_team_user",
            ),
        )


class OrganizationSessionMixin:
    @declared_attr
    def active_organization_id(self) -> Mapped[UUID | None]:
        return mapped_column(
            ForeignKey("organization.id", ondelete="set null", onupdate="cascade"),
            nullable=True,
            default=None,
            kw_only=True,
        )


class TeamSessionMixin:
    @declared_attr
    def active_team_id(self) -> Mapped[UUID | None]:
        return mapped_column(
            ForeignKey("team.id", ondelete="set null", onupdate="cascade"),
            nullable=True,
            default=None,
            kw_only=True,
        )


__all__ = [
    "AccountMixin",
    "OAuthStateMixin",
    "OrganizationInvitationMixin",
    "OrganizationMemberMixin",
    "OrganizationMixin",
    "OrganizationSessionMixin",
    "SessionMixin",
    "TeamMemberMixin",
    "TeamMixin",
    "TeamSessionMixin",
    "UserMixin",
]
