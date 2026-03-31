from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from belgie_proto.organization.invitation import InvitationProtocol
from belgie_proto.organization.member import MemberProtocol
from belgie_proto.organization.organization import OrganizationProtocol
from belgie_proto.team import TeamAdapterProtocol
from belgie_proto.team.member import TeamMemberProtocol
from belgie_proto.team.team import TeamProtocol
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

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

    async def _get_team_by_org_and_name(
        self,
        session: DBConnection,
        *,
        organization_id: UUID,
        name: str,
    ) -> TeamT | None:
        stmt = select(self.team_model).where(
            self.team_model.organization_id == organization_id,
            self.team_model.name == name,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def remove_member(
        self,
        session: DBConnection,
        *,
        organization_id: UUID,
        individual_id: UUID,
    ) -> bool:
        team_ids_stmt = select(self.team_model.id).where(self.team_model.organization_id == organization_id)
        await session.execute(
            delete(self.team_member_model).where(
                self.team_member_model.individual_id == individual_id,
                self.team_member_model.team_id.in_(team_ids_stmt),
            ),
        )
        member_delete_result = await session.execute(
            delete(self.member_model).where(
                self.member_model.organization_id == organization_id,
                self.member_model.individual_id == individual_id,
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
        if await self._get_team_by_org_and_name(session, organization_id=organization_id, name=name):
            msg = "team name must be unique per organization"
            raise IntegrityError(msg, params=None, orig=None)

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
        team = await self.get_team_by_id(session, team_id)
        if team is None:
            return None

        if (
            existing_team := await self._get_team_by_org_and_name(
                session,
                organization_id=team.organization_id,
                name=name,
            )
        ) is not None and existing_team.id != team.id:
            msg = "team name must be unique per organization"
            raise IntegrityError(msg, params=None, orig=None)

        team.name = name
        team.updated_at = datetime.now(UTC)
        try:
            await session.commit()
            await session.refresh(team)
        except Exception:
            await session.rollback()
            raise
        return team

    async def remove_team(
        self,
        session: DBConnection,
        *,
        team_id: UUID,
    ) -> bool:
        if not (team := await self.get_team_by_id(session, team_id)):
            return False

        await session.delete(team)
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return True

    async def add_team_member(
        self,
        session: DBConnection,
        *,
        team_id: UUID,
        individual_id: UUID,
    ) -> TeamMemberT:
        team_member = self.team_member_model(
            team_id=team_id,
            individual_id=individual_id,
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
        individual_id: UUID,
    ) -> bool:
        stmt = delete(self.team_member_model).where(
            self.team_member_model.team_id == team_id,
            self.team_member_model.individual_id == individual_id,
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
        individual_id: UUID,
    ) -> TeamMemberT | None:
        stmt = select(self.team_member_model).where(
            self.team_member_model.team_id == team_id,
            self.team_member_model.individual_id == individual_id,
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

    async def list_teams_for_individual(
        self,
        session: DBConnection,
        *,
        individual_id: UUID,
    ) -> list[TeamT]:
        stmt = (
            select(self.team_model)
            .join(
                self.team_member_model,
                self.team_member_model.team_id == self.team_model.id,
            )
            .where(self.team_member_model.individual_id == individual_id)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())
