from __future__ import annotations

from datetime import datetime  # noqa: TC003
from uuid import UUID  # noqa: TC003

from brussels.types import DateTimeUTC, Json
from sqlalchemy import ForeignKey, Index, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import CITEXT
from sqlalchemy.orm import Mapped, MappedAsDataclass, declarative_mixin, declared_attr, mapped_column, relationship


@declarative_mixin
class OrganizationMixin(MappedAsDataclass):
    __tablename__ = "organization"

    @declared_attr
    def name(self) -> Mapped[str]:
        return mapped_column(Text, kw_only=True)

    @declared_attr
    def slug(self) -> Mapped[str]:
        slug_type = Text().with_variant(CITEXT(), "postgresql")
        return mapped_column(slug_type, unique=True, index=True, kw_only=True)

    @declared_attr
    def logo(self) -> Mapped[str | None]:
        return mapped_column(Text, default=None, kw_only=True)

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


@declarative_mixin
class OrganizationMemberMixin(MappedAsDataclass):
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
        return mapped_column(Text, kw_only=True)

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


@declarative_mixin
class OrganizationInvitationMixin(MappedAsDataclass):
    __tablename__ = "organization_invitation"

    @declared_attr
    def organization_id(self) -> Mapped[UUID]:
        return mapped_column(
            ForeignKey("organization.id", ondelete="cascade", onupdate="cascade"),
            nullable=False,
            kw_only=True,
        )

    @declared_attr
    def team_id(self) -> Mapped[UUID | None]:
        return mapped_column(
            ForeignKey("team.id", ondelete="set null", onupdate="cascade"),
            nullable=True,
            default=None,
            index=True,
            kw_only=True,
        )

    @declared_attr
    def email(self) -> Mapped[str]:
        email_type = Text().with_variant(CITEXT(), "postgresql")
        return mapped_column(email_type, index=True, kw_only=True)

    @declared_attr
    def role(self) -> Mapped[str]:
        return mapped_column(Text, kw_only=True)

    @declared_attr
    def status(self) -> Mapped[str]:
        return mapped_column(Text, default="pending", index=True, kw_only=True)

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

    @declared_attr.directive
    def __table_args__(self) -> tuple[Index]:
        pending_condition = self.status == "pending"
        return (
            Index(
                "uq_organization_invitation_pending_org_email",
                self.organization_id,
                self.email,
                unique=True,
                postgresql_where=pending_condition,
                sqlite_where=pending_condition,
            ),
        )


__all__ = [
    "OrganizationInvitationMixin",
    "OrganizationMemberMixin",
    "OrganizationMixin",
]
