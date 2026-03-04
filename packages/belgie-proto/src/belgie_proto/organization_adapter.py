from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from belgie_proto.invitation import InvitationProtocol
from belgie_proto.member import MemberProtocol
from belgie_proto.organization import OrganizationProtocol
from belgie_proto.organization_session import OrganizationSessionProtocol, TeamSessionProtocol
from belgie_proto.team import TeamProtocol
from belgie_proto.team_member import TeamMemberProtocol

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from belgie_proto.connection import DBConnection


@runtime_checkable
class OrganizationAdapterProtocol[
    OrganizationT: OrganizationProtocol,
    MemberT: MemberProtocol,
    InvitationT: InvitationProtocol,
    SessionT: OrganizationSessionProtocol,
](Protocol):
    async def create_organization(
        self,
        session: DBConnection,
        *,
        name: str,
        slug: str,
        logo: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> OrganizationT: ...

    async def get_organization_by_id(
        self,
        session: DBConnection,
        organization_id: UUID,
    ) -> OrganizationT | None: ...

    async def get_organization_by_slug(
        self,
        session: DBConnection,
        slug: str,
    ) -> OrganizationT | None: ...

    async def update_organization(  # noqa: PLR0913
        self,
        session: DBConnection,
        organization_id: UUID,
        *,
        name: str | None = None,
        slug: str | None = None,
        logo: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> OrganizationT | None: ...

    async def delete_organization(
        self,
        session: DBConnection,
        organization_id: UUID,
    ) -> bool: ...

    async def list_organizations_for_user(
        self,
        session: DBConnection,
        user_id: UUID,
    ) -> list[OrganizationT]: ...

    async def create_member(
        self,
        session: DBConnection,
        *,
        organization_id: UUID,
        user_id: UUID,
        role: str,
    ) -> MemberT: ...

    async def get_member(
        self,
        session: DBConnection,
        *,
        organization_id: UUID,
        user_id: UUID,
    ) -> MemberT | None: ...

    async def get_member_by_id(
        self,
        session: DBConnection,
        member_id: UUID,
    ) -> MemberT | None: ...

    async def list_members(
        self,
        session: DBConnection,
        *,
        organization_id: UUID,
    ) -> list[MemberT]: ...

    async def update_member_role(
        self,
        session: DBConnection,
        *,
        member_id: UUID,
        role: str,
    ) -> MemberT | None: ...

    async def remove_member(
        self,
        session: DBConnection,
        *,
        organization_id: UUID,
        user_id: UUID,
    ) -> bool: ...

    async def create_invitation(  # noqa: PLR0913
        self,
        session: DBConnection,
        *,
        organization_id: UUID,
        email: str,
        role: str,
        inviter_id: UUID,
        expires_at: datetime,
    ) -> InvitationT: ...

    async def get_invitation(
        self,
        session: DBConnection,
        invitation_id: UUID,
    ) -> InvitationT | None: ...

    async def get_pending_invitation(
        self,
        session: DBConnection,
        *,
        organization_id: UUID,
        email: str,
    ) -> InvitationT | None: ...

    async def list_invitations(
        self,
        session: DBConnection,
        *,
        organization_id: UUID,
    ) -> list[InvitationT]: ...

    async def set_invitation_status(
        self,
        session: DBConnection,
        *,
        invitation_id: UUID,
        status: str,
    ) -> InvitationT | None: ...

    async def set_active_organization(
        self,
        session: DBConnection,
        *,
        session_id: UUID,
        organization_id: UUID | None,
    ) -> SessionT | None: ...


@runtime_checkable
class TeamAdapterProtocol[
    OrganizationT: OrganizationProtocol,
    MemberT: MemberProtocol,
    InvitationT: InvitationProtocol,
    TeamT: TeamProtocol,
    TeamMemberT: TeamMemberProtocol,
    SessionT: TeamSessionProtocol,
](OrganizationAdapterProtocol[OrganizationT, MemberT, InvitationT, SessionT], Protocol):
    async def create_team(
        self,
        session: DBConnection,
        *,
        organization_id: UUID,
        name: str,
    ) -> TeamT: ...

    async def get_team_by_id(
        self,
        session: DBConnection,
        team_id: UUID,
    ) -> TeamT | None: ...

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

    async def add_team_member(
        self,
        session: DBConnection,
        *,
        team_id: UUID,
        user_id: UUID,
    ) -> TeamMemberT: ...

    async def remove_team_member(
        self,
        session: DBConnection,
        *,
        team_id: UUID,
        user_id: UUID,
    ) -> bool: ...

    async def get_team_member(
        self,
        session: DBConnection,
        *,
        team_id: UUID,
        user_id: UUID,
    ) -> TeamMemberT | None: ...

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

    async def set_active_team(
        self,
        session: DBConnection,
        *,
        session_id: UUID,
        team_id: UUID | None,
    ) -> SessionT | None: ...
