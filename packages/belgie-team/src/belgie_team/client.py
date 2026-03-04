from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

    from belgie_core import BelgieClient
    from belgie_proto import (
        InvitationProtocol,
        MemberProtocol,
        OrganizationProtocol,
        TeamAdapterProtocol,
        TeamMemberProtocol,
        TeamProtocol,
        TeamSessionProtocol,
    )

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

    async def create_team(
        self,
        *,
        organization_id: UUID,
        name: str,
    ) -> TeamProtocol:
        return await self.adapter.create_team(
            self.client.db,
            organization_id=organization_id,
            name=name,
        )

    async def list_teams(self, *, organization_id: UUID) -> list[TeamProtocol]:
        return await self.adapter.list_teams(
            self.client.db,
            organization_id=organization_id,
        )

    async def set_active_team(
        self,
        *,
        session_id: UUID,
        team_id: UUID | None,
    ) -> TeamSessionProtocol | None:
        return await self.adapter.set_active_team(
            self.client.db,
            session_id=session_id,
            team_id=team_id,
        )

    async def add_team_member(
        self,
        *,
        team_id: UUID,
        user_id: UUID,
    ) -> TeamMemberProtocol:
        return await self.adapter.add_team_member(
            self.client.db,
            team_id=team_id,
            user_id=user_id,
        )

    async def remove_team_member(
        self,
        *,
        team_id: UUID,
        user_id: UUID,
    ) -> bool:
        return await self.adapter.remove_team_member(
            self.client.db,
            team_id=team_id,
            user_id=user_id,
        )
