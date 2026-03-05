from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from uuid import UUID

    from belgie_core import BelgieClient
    from belgie_proto.organization import OrganizationAdapterProtocol
    from belgie_proto.organization.invitation import InvitationProtocol
    from belgie_proto.organization.member import MemberProtocol
    from belgie_proto.organization.organization import OrganizationProtocol
    from belgie_proto.organization.session import OrganizationSessionProtocol

    from belgie_organization.settings import Organization


@dataclass(frozen=True, slots=True, kw_only=True)
class OrganizationClient:
    client: BelgieClient
    settings: Organization
    adapter: OrganizationAdapterProtocol[
        OrganizationProtocol,
        MemberProtocol,
        InvitationProtocol,
        OrganizationSessionProtocol,
    ]

    async def create_organization(
        self,
        *,
        user_id: UUID,
        name: str,
        slug: str,
        logo: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> tuple[OrganizationProtocol, MemberProtocol]:
        organization = await self.adapter.create_organization(
            self.client.db,
            name=name,
            slug=slug,
            logo=logo,
            metadata=metadata,
        )
        member = await self.adapter.create_member(
            self.client.db,
            organization_id=organization.id,
            user_id=user_id,
            role=self.settings.creator_role,
        )
        return organization, member

    async def list_organizations_for_user(self, user_id: UUID) -> list[OrganizationProtocol]:
        return await self.adapter.list_organizations_for_user(self.client.db, user_id)

    async def set_active_organization(
        self,
        *,
        session_id: UUID,
        organization_id: UUID | None,
    ) -> OrganizationSessionProtocol | None:
        return await self.adapter.set_active_organization(
            self.client.db,
            session_id=session_id,
            organization_id=organization_id,
        )

    async def get_full_organization(
        self,
        *,
        organization_id: UUID,
    ) -> (
        tuple[
            OrganizationProtocol,
            list[MemberProtocol],
            list[InvitationProtocol],
        ]
        | None
    ):
        organization = await self.adapter.get_organization_by_id(self.client.db, organization_id)
        if organization is None:
            return None
        members = await self.adapter.list_members(
            self.client.db,
            organization_id=organization_id,
        )
        invitations = await self.adapter.list_invitations(
            self.client.db,
            organization_id=organization_id,
        )
        return organization, members, invitations

    async def create_invitation(
        self,
        *,
        organization_id: UUID,
        email: str,
        role: str,
        inviter_id: UUID,
    ) -> InvitationProtocol:
        expires_at = datetime.now(UTC) + timedelta(seconds=self.settings.invitation_expires_in_seconds)
        return await self.adapter.create_invitation(
            self.client.db,
            organization_id=organization_id,
            email=email,
            role=role,
            inviter_id=inviter_id,
            expires_at=expires_at,
        )
