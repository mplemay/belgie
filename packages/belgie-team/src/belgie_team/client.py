from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from belgie_proto.organization.invitation import InvitationProtocol
from belgie_proto.organization.member import MemberProtocol
from belgie_proto.organization.organization import OrganizationProtocol
from belgie_proto.team.member import TeamMemberProtocol
from belgie_proto.team.team import TeamProtocol
from fastapi import HTTPException, status

if TYPE_CHECKING:
    import builtins
    from uuid import UUID

    from belgie_core import BelgieClient
    from belgie_proto.core.individual import IndividualProtocol

    from belgie_team.settings import Team


@dataclass(frozen=True, slots=True, kw_only=True)
class TeamClient[
    OrganizationT: OrganizationProtocol,
    MemberT: MemberProtocol,
    InvitationT: InvitationProtocol,
    TeamT: TeamProtocol,
    TeamMemberT: TeamMemberProtocol,
]:
    client: BelgieClient
    settings: Team[OrganizationT, MemberT, InvitationT, TeamT, TeamMemberT]
    current_individual: IndividualProtocol[str]

    async def create(
        self,
        *,
        name: str,
        organization_id: UUID,
    ) -> TeamT:
        await self._require_default_admin_role(organization_id=organization_id)

        if self.settings.maximum_teams_per_organization is not None and (
            len(
                await self.settings.adapter.list_teams(
                    self.client.db,
                    organization_id=organization_id,
                ),
            )
            >= self.settings.maximum_teams_per_organization
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="maximum teams reached for this organization",
            )

        team = await self.settings.adapter.create_team(
            self.client.db,
            organization_id=organization_id,
            name=name,
        )

        if (
            await self.settings.adapter.get_team_member(
                self.client.db,
                team_id=team.id,
                individual_id=self.current_individual.id,
            )
            is None
        ):
            await self.settings.adapter.add_team_member(
                self.client.db,
                team_id=team.id,
                individual_id=self.current_individual.id,
            )

        return team

    async def teams(self, *, organization_id: UUID) -> builtins.list[TeamT]:
        await self._require_organization_membership(organization_id=organization_id)
        return await self.settings.adapter.list_teams(
            self.client.db,
            organization_id=organization_id,
        )

    async def update(self, *, team_id: UUID, name: str) -> TeamT:
        team = await self.settings.adapter.get_team_by_id(self.client.db, team_id)
        if team is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="team not found",
            )

        await self._require_default_admin_role(organization_id=team.organization_id)
        if (updated := await self.settings.adapter.update_team(self.client.db, team_id=team_id, name=name)) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="team not found",
            )
        return updated

    async def delete(self, *, team_id: UUID) -> bool:
        team = await self.settings.adapter.get_team_by_id(self.client.db, team_id)
        if team is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="team not found",
            )

        await self._require_default_admin_role(organization_id=team.organization_id)
        return await self.settings.adapter.remove_team(self.client.db, team_id=team_id)

    async def for_individual(self) -> builtins.list[TeamT]:
        return await self.settings.adapter.list_teams_for_individual(
            self.client.db,
            individual_id=self.current_individual.id,
        )

    async def members(self, *, team_id: UUID) -> builtins.list[TeamMemberT]:
        team = await self.settings.adapter.get_team_by_id(self.client.db, team_id)
        if team is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="team not found",
            )
        await self._require_organization_membership(organization_id=team.organization_id)
        await self._require_team_membership(team_id=team.id)
        return await self.settings.adapter.list_team_members(self.client.db, team_id=team.id)

    async def add_member(self, *, team_id: UUID, individual_id: UUID) -> TeamMemberT:
        team = await self.settings.adapter.get_team_by_id(self.client.db, team_id)
        if team is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="team not found",
            )

        await self._require_default_admin_role(organization_id=team.organization_id)
        if (
            await self.settings.adapter.get_member(
                self.client.db,
                organization_id=team.organization_id,
                individual_id=individual_id,
            )
            is None
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="target user is not in the organization",
            )

        if self.settings.maximum_members_per_team is not None and (
            len(
                await self.settings.adapter.list_team_members(
                    self.client.db,
                    team_id=team_id,
                ),
            )
            >= self.settings.maximum_members_per_team
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="team member limit reached",
            )

        if (
            existing := await self.settings.adapter.get_team_member(
                self.client.db,
                team_id=team_id,
                individual_id=individual_id,
            )
        ) is not None:
            return existing

        return await self.settings.adapter.add_team_member(
            self.client.db,
            team_id=team_id,
            individual_id=individual_id,
        )

    async def remove_member(self, *, team_id: UUID, individual_id: UUID) -> bool:
        team = await self.settings.adapter.get_team_by_id(self.client.db, team_id)
        if team is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="team not found",
            )

        await self._require_default_admin_role(organization_id=team.organization_id)
        return await self.settings.adapter.remove_team_member(
            self.client.db,
            team_id=team_id,
            individual_id=individual_id,
        )

    async def _require_organization_membership(self, *, organization_id: UUID) -> MemberT:
        if (
            member := await self.settings.adapter.get_member(
                self.client.db,
                organization_id=organization_id,
                individual_id=self.current_individual.id,
            )
        ) is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="you are not a member of this organization",
            )
        return member

    async def _require_default_admin_role(self, *, organization_id: UUID) -> MemberT:
        member = await self._require_organization_membership(organization_id=organization_id)
        if not _has_any_role(member.role, ["owner", "admin"]):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="insufficient organization permissions",
            )
        return member

    async def _require_team_membership(self, *, team_id: UUID) -> TeamMemberT:
        if (
            team_member := await self.settings.adapter.get_team_member(
                self.client.db,
                team_id=team_id,
                individual_id=self.current_individual.id,
            )
        ) is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="you are not a member of this team",
            )
        return team_member


def _has_any_role(role_value: str, required_roles: builtins.list[str]) -> bool:
    parsed_roles = {role.strip().lower() for role in role_value.split(",") if role.strip()}
    return any(required.lower() in parsed_roles for required in required_roles)
