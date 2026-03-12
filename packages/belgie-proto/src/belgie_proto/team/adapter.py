from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from belgie_proto.core.session import SessionProtocol
from belgie_proto.organization import OrganizationTeamAdapterProtocol
from belgie_proto.organization.invitation import InvitationProtocol
from belgie_proto.organization.member import MemberProtocol
from belgie_proto.organization.organization import OrganizationProtocol
from belgie_proto.team.member import TeamMemberProtocol
from belgie_proto.team.team import TeamProtocol

if TYPE_CHECKING:
    from uuid import UUID

    from belgie_proto.core.connection import DBConnection


@runtime_checkable
class TeamAdapterProtocol[
    OrganizationT: OrganizationProtocol,
    MemberT: MemberProtocol,
    InvitationT: InvitationProtocol,
    TeamT: TeamProtocol,
    TeamMemberT: TeamMemberProtocol,
    SessionT: SessionProtocol,
](OrganizationTeamAdapterProtocol[OrganizationT, MemberT, InvitationT, TeamT, TeamMemberT, SessionT], Protocol):
    async def create_team(
        self,
        session: DBConnection,
        *,
        organization_id: UUID,
        name: str,
    ) -> TeamT: ...

    async def list_teams(
        self,
        session: DBConnection,
        *,
        organization_id: UUID,
    ) -> list[TeamT]: ...

    async def update_team(
        self,
        session: DBConnection,
        *,
        team_id: UUID,
        name: str,
    ) -> TeamT | None: ...

    async def remove_team(
        self,
        session: DBConnection,
        *,
        team_id: UUID,
    ) -> bool: ...

    async def remove_team_member(
        self,
        session: DBConnection,
        *,
        team_id: UUID,
        user_id: UUID,
    ) -> bool: ...

    async def list_team_members(
        self,
        session: DBConnection,
        *,
        team_id: UUID,
    ) -> list[TeamMemberT]: ...

    async def list_teams_for_user(
        self,
        session: DBConnection,
        *,
        user_id: UUID,
    ) -> list[TeamT]: ...
