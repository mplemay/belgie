from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import HTTPException, status

if TYPE_CHECKING:
    import builtins
    from uuid import UUID

    from belgie_core import BelgieClient
    from belgie_proto.core.user import UserProtocol
    from belgie_proto.organization.invitation import InvitationProtocol
    from belgie_proto.organization.member import MemberProtocol
    from belgie_proto.organization.organization import OrganizationProtocol
    from belgie_proto.team import TeamAdapterProtocol
    from belgie_proto.team.member import TeamMemberProtocol
    from belgie_proto.team.session import TeamSessionProtocol
    from belgie_proto.team.team import TeamProtocol

    from belgie_team.settings import Team


@dataclass(frozen=True, slots=True, kw_only=True)
class TeamClient:
    client: BelgieClient
    settings: Team
    adapter: TeamAdapterProtocol[
        OrganizationProtocol,
        MemberProtocol,
        InvitationProtocol,
        TeamProtocol,
        TeamMemberProtocol,
        TeamSessionProtocol,
    ]
    current_user: UserProtocol[str]
    current_session: TeamSessionProtocol

    async def create(
        self,
        *,
        name: str,
        organization_id: UUID | None = None,
    ) -> TeamProtocol:
        resolved_organization_id = self._resolve_required_organization_id(organization_id=organization_id)
        await self._require_default_admin_role(organization_id=resolved_organization_id)

        if self.settings.maximum_teams_per_organization is not None and (
            len(
                await self.adapter.list_teams(
                    self.client.db,
                    organization_id=resolved_organization_id,
                ),
            )
            >= self.settings.maximum_teams_per_organization
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="maximum teams reached for this organization",
            )

        team = await self.adapter.create_team(
            self.client.db,
            organization_id=resolved_organization_id,
            name=name,
        )

        if (
            await self.adapter.get_team_member(
                self.client.db,
                team_id=team.id,
                user_id=self.current_user.id,
            )
            is None
        ):
            await self.adapter.add_team_member(
                self.client.db,
                team_id=team.id,
                user_id=self.current_user.id,
            )

        return team

    async def list(self, *, organization_id: UUID | None = None) -> builtins.list[TeamProtocol]:
        resolved_organization_id = self._resolve_required_organization_id(organization_id=organization_id)
        await self._require_organization_membership(organization_id=resolved_organization_id)
        return await self.adapter.list_teams(
            self.client.db,
            organization_id=resolved_organization_id,
        )

    async def set_active(self, *, team_id: UUID | None = None) -> TeamProtocol | None:
        if team_id is None:
            await self.adapter.set_active_team(
                self.client.db,
                session_id=self.current_session.id,
                team_id=None,
            )
            return None

        team = await self.adapter.get_team_by_id(self.client.db, team_id)
        if team is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="team not found",
            )

        await self._require_organization_membership(organization_id=team.organization_id)
        await self._require_team_membership(team_id=team.id)
        await self.adapter.set_active_team(
            self.client.db,
            session_id=self.current_session.id,
            team_id=team.id,
        )
        return team

    async def get_active(self) -> TeamProtocol | None:
        if self.current_session.active_team_id is None:
            return None

        team = await self.adapter.get_team_by_id(self.client.db, self.current_session.active_team_id)
        if team is None:
            return None
        if team.organization_id != self.current_session.active_organization_id:
            return None

        if (
            await self.adapter.get_member(
                self.client.db,
                organization_id=team.organization_id,
                user_id=self.current_user.id,
            )
            is None
        ):
            return None

        if (
            await self.adapter.get_team_member(
                self.client.db,
                team_id=team.id,
                user_id=self.current_user.id,
            )
            is None
        ):
            return None

        return team

    async def update(self, *, team_id: UUID, name: str) -> TeamProtocol:
        team = await self.adapter.get_team_by_id(self.client.db, team_id)
        if team is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="team not found",
            )

        await self._require_default_admin_role(organization_id=team.organization_id)
        if (updated := await self.adapter.update_team(self.client.db, team_id=team_id, name=name)) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="team not found",
            )
        return updated

    async def remove(self, *, team_id: UUID) -> bool:
        team = await self.adapter.get_team_by_id(self.client.db, team_id)
        if team is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="team not found",
            )

        await self._require_default_admin_role(organization_id=team.organization_id)
        removed = await self.adapter.remove_team(self.client.db, team_id=team_id)
        if removed and self.current_session.active_team_id == team_id:
            await self.adapter.set_active_team(
                self.client.db,
                session_id=self.current_session.id,
                team_id=None,
            )
        return removed

    async def list_user_teams(self) -> builtins.list[TeamProtocol]:
        return await self.adapter.list_teams_for_user(self.client.db, user_id=self.current_user.id)

    async def list_members(self, *, team_id: UUID | None = None) -> builtins.list[TeamMemberProtocol]:
        if team_id is None and (active_team := await self.get_active()) is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="team_id is required",
            )
        if team_id is None:
            return await self.adapter.list_team_members(self.client.db, team_id=active_team.id)

        team = await self.adapter.get_team_by_id(self.client.db, team_id)
        if team is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="team not found",
            )
        await self._require_organization_membership(organization_id=team.organization_id)
        await self._require_team_membership(team_id=team.id)
        return await self.adapter.list_team_members(self.client.db, team_id=team.id)

    async def add_member(self, *, team_id: UUID, user_id: UUID) -> TeamMemberProtocol:
        team = await self.adapter.get_team_by_id(self.client.db, team_id)
        if team is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="team not found",
            )

        await self._require_default_admin_role(organization_id=team.organization_id)
        if (
            await self.adapter.get_member(
                self.client.db,
                organization_id=team.organization_id,
                user_id=user_id,
            )
            is None
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="target user is not in the organization",
            )

        if self.settings.maximum_members_per_team is not None and (
            len(
                await self.adapter.list_team_members(
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
            existing := await self.adapter.get_team_member(
                self.client.db,
                team_id=team_id,
                user_id=user_id,
            )
        ) is not None:
            return existing

        return await self.adapter.add_team_member(
            self.client.db,
            team_id=team_id,
            user_id=user_id,
        )

    async def remove_member(self, *, team_id: UUID, user_id: UUID) -> bool:
        team = await self.adapter.get_team_by_id(self.client.db, team_id)
        if team is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="team not found",
            )

        await self._require_default_admin_role(organization_id=team.organization_id)
        return await self.adapter.remove_team_member(
            self.client.db,
            team_id=team_id,
            user_id=user_id,
        )

    def _resolve_required_organization_id(self, *, organization_id: UUID | None) -> UUID:
        if organization_id is not None:
            return organization_id
        if self.current_session.active_organization_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="organization_id is required",
            )
        return self.current_session.active_organization_id

    async def _require_organization_membership(self, *, organization_id: UUID) -> MemberProtocol:
        if (
            member := await self.adapter.get_member(
                self.client.db,
                organization_id=organization_id,
                user_id=self.current_user.id,
            )
        ) is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="you are not a member of this organization",
            )
        return member

    async def _require_default_admin_role(self, *, organization_id: UUID) -> MemberProtocol:
        member = await self._require_organization_membership(organization_id=organization_id)
        if not _has_any_role(member.role, ["owner", "admin"]):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="insufficient organization permissions",
            )
        return member

    async def _require_team_membership(self, *, team_id: UUID) -> TeamMemberProtocol:
        if (
            team_member := await self.adapter.get_team_member(
                self.client.db,
                team_id=team_id,
                user_id=self.current_user.id,
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
