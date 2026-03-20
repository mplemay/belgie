from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from belgie_proto.organization.invitation import InvitationProtocol
from belgie_proto.organization.member import MemberProtocol
from belgie_proto.organization.organization import OrganizationProtocol
from belgie_proto.team import TeamAdapterProtocol
from belgie_proto.team.member import TeamMemberProtocol
from belgie_proto.team.team import TeamProtocol
from sqlalchemy import delete, select, update

from belgie_alchemy.organization.adapter import OrganizationAdapter

if TYPE_CHECKING:
    from uuid import UUID

    from belgie_proto.core.connection import DBConnection


class TeamAdapter[
    OrganizationT: OrganizationProtocol,
    MemberT: MemberProtocol,
    InvitationT: InvitationProtocol,
    TeamT: TeamProtocol,
    TeamMemberT: TeamMemberProtocol,
](
    OrganizationAdapter[OrganizationT, MemberT, InvitationT],
    TeamAdapterProtocol[OrganizationT, MemberT, InvitationT, TeamT, TeamMemberT],
):
    def __init__(
        self,
        *,
        organization: type[OrganizationT],
        member: type[MemberT],
        invitation: type[InvitationT],
        team: type[TeamT],
        team_member: type[TeamMemberT],
    ) -> None:
        super().__init__(organization=organization, member=member, invitation=invitation)
        self.team_model = team
        self.team_member_model = team_member

    async def remove_member(
        self,
        session: DBConnection,
        *,
        organization_id: UUID,
        user_id: UUID,
    ) -> bool:
        team_ids_stmt = select(self.team_model.id).where(self.team_model.organization_id == organization_id)
        await session.execute(
            delete(self.team_member_model).where(
                self.team_member_model.user_id == user_id,
                self.team_member_model.team_id.in_(team_ids_stmt),
            ),
        )
        member_delete_result = await session.execute(
            delete(self.member_model).where(
                self.member_model.organization_id == organization_id,
                self.member_model.user_id == user_id,
            ),
        )
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return member_delete_result.rowcount > 0  # type: ignore[attr-defined]

    async def create_team(
        self,
        session: DBConnection,
        *,
        organization_id: UUID,
        name: str,
    ) -> TeamT:
        team = self.team_model(
            organization_id=organization_id,
            name=name,
        )
        session.add(team)
        try:
            await session.commit()
            await session.refresh(team)
        except Exception:
            await session.rollback()
            raise
        return team

    async def get_team_by_id(
        self,
        session: DBConnection,
        team_id: UUID,
    ) -> TeamT | None:
        stmt = select(self.team_model).where(self.team_model.id == team_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_teams(
        self,
        session: DBConnection,
        *,
        organization_id: UUID,
    ) -> list[TeamT]:
        stmt = select(self.team_model).where(self.team_model.organization_id == organization_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def update_team(
        self,
        session: DBConnection,
        *,
        team_id: UUID,
        name: str,
    ) -> TeamT | None:
        stmt = (
            update(self.team_model)
            .where(self.team_model.id == team_id)
            .values(name=name, updated_at=datetime.now(UTC))
            .returning(self.team_model)
        )
        try:
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            # If RETURNING is empty, still commit: rollback would drop unrelated pending ORM
            # work that may exist on the same session alongside this call.
            await session.commit()
            if row is None:
                return None
            await session.refresh(row)
        except Exception:
            await session.rollback()
            raise
        return row

    async def remove_team(
        self,
        session: DBConnection,
        *,
        team_id: UUID,
    ) -> bool:
        stmt = delete(self.team_model).where(self.team_model.id == team_id)
        result = await session.execute(stmt)
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return result.rowcount > 0  # type: ignore[attr-defined]

    async def add_team_member(
        self,
        session: DBConnection,
        *,
        team_id: UUID,
        user_id: UUID,
    ) -> TeamMemberT:
        team_member = self.team_member_model(
            team_id=team_id,
            user_id=user_id,
        )
        session.add(team_member)
        try:
            await session.commit()
            await session.refresh(team_member)
        except Exception:
            await session.rollback()
            raise
        return team_member

    async def remove_team_member(
        self,
        session: DBConnection,
        *,
        team_id: UUID,
        user_id: UUID,
    ) -> bool:
        stmt = delete(self.team_member_model).where(
            self.team_member_model.team_id == team_id,
            self.team_member_model.user_id == user_id,
        )
        result = await session.execute(stmt)
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return result.rowcount > 0  # type: ignore[attr-defined]

    async def get_team_member(
        self,
        session: DBConnection,
        *,
        team_id: UUID,
        user_id: UUID,
    ) -> TeamMemberT | None:
        stmt = select(self.team_member_model).where(
            self.team_member_model.team_id == team_id,
            self.team_member_model.user_id == user_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_team_members(
        self,
        session: DBConnection,
        *,
        team_id: UUID,
    ) -> list[TeamMemberT]:
        stmt = select(self.team_member_model).where(self.team_member_model.team_id == team_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def list_teams_for_user(
        self,
        session: DBConnection,
        *,
        user_id: UUID,
    ) -> list[TeamT]:
        stmt = (
            select(self.team_model)
            .join(
                self.team_member_model,
                self.team_member_model.team_id == self.team_model.id,
            )
            .where(self.team_member_model.user_id == user_id)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())
