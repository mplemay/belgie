from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

from belgie_proto.organization.invitation import InvitationProtocol
from belgie_proto.organization.member import MemberProtocol
from belgie_proto.organization.organization import OrganizationProtocol
from belgie_proto.organization.session import OrganizationSessionProtocol

if TYPE_CHECKING:
    from datetime import datetime
    from uuid import UUID

    from belgie_proto.core.connection import DBConnection


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
        team_id: UUID | None,
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

    async def list_user_invitations(
        self,
        session: DBConnection,
        *,
        email: str,
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
