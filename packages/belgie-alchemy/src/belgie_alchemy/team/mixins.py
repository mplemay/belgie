from __future__ import annotations

from uuid import UUID  # noqa: TC003

from belgie_proto.core.account import AccountType
from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, MappedAsDataclass, declarative_mixin, declared_attr, mapped_column, relationship

from belgie_alchemy.core.mixins import _account_pk_uuid


@declarative_mixin
class TeamMixin(MappedAsDataclass):
    __tablename__ = "team"

    @declared_attr
    def id(self) -> Mapped[UUID]:
        return mapped_column(
            ForeignKey("account.id", ondelete="cascade", onupdate="cascade"),
            primary_key=True,
            default_factory=_account_pk_uuid,
            insert_default=_account_pk_uuid,
            init=False,
        )

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
            foreign_keys=lambda: [self.organization_id],
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
    def __mapper_args__(self) -> dict[str, object]:
        return {"polymorphic_identity": AccountType.TEAM}


@declarative_mixin
class TeamMemberMixin(MappedAsDataclass):
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
    def individual_id(self) -> Mapped[UUID]:
        return mapped_column(
            ForeignKey("individual.id", ondelete="cascade", onupdate="cascade"),
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
    def individual(self) -> Mapped[object]:
        return relationship(
            "Individual",
            lazy="selectin",
            init=False,
        )

    @declared_attr.directive
    def __table_args__(self) -> tuple[UniqueConstraint]:
        return (
            UniqueConstraint(
                "team_id",
                "individual_id",
                name="uq_team_member_team_individual",
            ),
        )


__all__ = [
    "TeamMemberMixin",
    "TeamMixin",
]
