from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from belgie_proto.organization.adapter import OrganizationAdapterProtocol
from belgie_proto.organization.invitation import InvitationProtocol
from belgie_proto.organization.member import MemberProtocol
from belgie_proto.organization.organization import OrganizationProtocol

if TYPE_CHECKING:
    from uuid import UUID

    from belgie_proto.core.connection import DBConnection


@runtime_checkable
class OrganizationTeamAdapterProtocol[
    OrganizationT: OrganizationProtocol,
    MemberT: MemberProtocol,
    InvitationT: InvitationProtocol,
    TeamT,
    TeamMemberT,
](OrganizationAdapterProtocol[OrganizationT, MemberT, InvitationT], Protocol):
    async def get_team_by_id(
        self,
        session: DBConnection,
        team_id: UUID,
    ) -> TeamT | None: ...

    async def get_team_member(
        self,
        session: DBConnection,
        *,
        team_id: UUID,
        individual_id: UUID,
    ) -> TeamMemberT | None: ...

    async def add_team_member(
        self,
        session: DBConnection,
        *,
        team_id: UUID,
        individual_id: UUID,
    ) -> TeamMemberT: ...
