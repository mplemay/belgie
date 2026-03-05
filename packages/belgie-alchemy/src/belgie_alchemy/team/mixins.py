from __future__ import annotations

from uuid import UUID  # noqa: TC003

from brussels.mixins import PrimaryKeyMixin, TimestampMixin
from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, declared_attr, mapped_column, relationship


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
    "TeamMemberMixin",
    "TeamMixin",
    "TeamSessionMixin",
]
