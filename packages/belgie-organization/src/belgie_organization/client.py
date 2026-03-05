from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from fastapi import HTTPException, status

from belgie_organization.roles import RoleValue, has_any_role, has_role, normalize_roles

if TYPE_CHECKING:
    from belgie_core import BelgieClient
    from belgie_proto.core.user import UserProtocol
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
    current_user: UserProtocol[str]
    current_session: OrganizationSessionProtocol

    async def create(  # noqa: PLR0913
        self,
        *,
        name: str,
        slug: str,
        role: RoleValue[str],
        logo: str | None = None,
        metadata: dict[str, object] | None = None,
        user_id: UUID | None = None,
        keep_current_active_organization: bool = False,
    ) -> tuple[OrganizationProtocol, MemberProtocol]:
        creator_user_id = user_id or self.current_user.id
        if user_id is not None and user_id != self.current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="cannot create organization for another user from client session",
            )
        if not self.settings.allow_user_to_create_organization:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="organization creation is disabled",
            )
        if await self.check_slug(slug=slug):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="organization slug already taken",
            )

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
            user_id=creator_user_id,
            role=normalize_roles(role),
        )
        if not keep_current_active_organization:
            await self.set_active(organization_id=organization.id)
        return organization, member

    async def check_slug(self, *, slug: str) -> bool:
        return await self.adapter.get_organization_by_slug(self.client.db, slug) is not None

    async def list_for_user(self, *, user_id: UUID | None = None) -> list[OrganizationProtocol]:
        resolved_user_id = user_id or self.current_user.id
        return await self.adapter.list_organizations_for_user(self.client.db, resolved_user_id)

    async def set_active(
        self,
        *,
        organization_id: UUID | None = None,
        organization_slug: str | None = None,
    ) -> OrganizationProtocol | None:
        if organization_id is None and organization_slug is None:
            await self.adapter.set_active_organization(
                self.client.db,
                session_id=self.current_session.id,
                organization_id=None,
            )
            return None

        resolved_organization_id = organization_id
        if resolved_organization_id is None and organization_slug is not None:
            by_slug = await self.adapter.get_organization_by_slug(self.client.db, organization_slug)
            if by_slug is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="organization not found",
                )
            resolved_organization_id = by_slug.id

        if resolved_organization_id is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="organization_id or organization_slug is required",
            )

        await self._require_organization_membership(organization_id=resolved_organization_id)
        await self.adapter.set_active_organization(
            self.client.db,
            session_id=self.current_session.id,
            organization_id=resolved_organization_id,
        )
        return await self.adapter.get_organization_by_id(self.client.db, resolved_organization_id)

    async def get_active(self) -> OrganizationProtocol | None:
        if (active_organization_id := self.current_session.active_organization_id) is None:
            return None
        organization = await self.adapter.get_organization_by_id(self.client.db, active_organization_id)
        if organization is None:
            return None
        if (
            await self.adapter.get_member(
                self.client.db,
                organization_id=organization.id,
                user_id=self.current_user.id,
            )
            is None
        ):
            return None
        return organization

    async def get_full(
        self,
        *,
        organization_id: UUID | None = None,
        organization_slug: str | None = None,
    ) -> tuple[OrganizationProtocol, list[MemberProtocol], list[InvitationProtocol]] | None:
        resolved_organization_id = await self._resolve_organization_id(
            organization_id=organization_id,
            organization_slug=organization_slug,
        )
        if resolved_organization_id is None:
            return None

        await self._require_organization_membership(organization_id=resolved_organization_id)
        organization = await self.adapter.get_organization_by_id(self.client.db, resolved_organization_id)
        if organization is None:
            return None
        members = await self.adapter.list_members(self.client.db, organization_id=resolved_organization_id)
        invitations = await self.adapter.list_invitations(self.client.db, organization_id=resolved_organization_id)
        return organization, members, invitations

    async def update(
        self,
        *,
        organization_id: UUID | None = None,
        name: str | None = None,
        slug: str | None = None,
        logo: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> OrganizationProtocol:
        resolved_organization_id = await self._resolve_required_organization_id(organization_id=organization_id)
        await self._require_default_admin_role(organization_id=resolved_organization_id)

        if (
            slug is not None
            and (existing := await self.adapter.get_organization_by_slug(self.client.db, slug))
            and existing.id != resolved_organization_id
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="organization slug already taken",
            )

        if (
            updated := await self.adapter.update_organization(
                self.client.db,
                resolved_organization_id,
                name=name,
                slug=slug,
                logo=logo,
                metadata=metadata,
            )
        ) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="organization not found",
            )
        return updated

    async def delete(self, *, organization_id: UUID) -> bool:
        await self._require_owner_role(organization_id=organization_id)
        deleted = await self.adapter.delete_organization(self.client.db, organization_id)
        if deleted and self.current_session.active_organization_id == organization_id:
            await self.adapter.set_active_organization(
                self.client.db,
                session_id=self.current_session.id,
                organization_id=None,
            )
        return deleted

    async def list_members(self, *, organization_id: UUID | None = None) -> list[MemberProtocol]:
        resolved_organization_id = await self._resolve_required_organization_id(organization_id=organization_id)
        await self._require_organization_membership(organization_id=resolved_organization_id)
        return await self.adapter.list_members(self.client.db, organization_id=resolved_organization_id)

    async def add_member(
        self,
        *,
        user_id: UUID,
        role: RoleValue[str],
        organization_id: UUID | None = None,
        team_id: UUID | None = None,
    ) -> MemberProtocol:
        resolved_organization_id = await self._resolve_required_organization_id(organization_id=organization_id)
        await self._require_default_admin_role(organization_id=resolved_organization_id)

        if await self.client.adapter.get_user_by_id(self.client.db, user_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="user not found",
            )

        if (
            existing_member := await self.adapter.get_member(
                self.client.db,
                organization_id=resolved_organization_id,
                user_id=user_id,
            )
        ) is not None:
            member = existing_member
        else:
            member = await self.adapter.create_member(
                self.client.db,
                organization_id=resolved_organization_id,
                user_id=user_id,
                role=normalize_roles(role),
            )

        if team_id is not None:
            await self._add_user_to_team(
                organization_id=resolved_organization_id,
                team_id=team_id,
                user_id=user_id,
            )
        return member

    async def remove_member(
        self,
        *,
        member_id_or_email: str,
        organization_id: UUID | None = None,
    ) -> bool:
        resolved_organization_id = await self._resolve_required_organization_id(organization_id=organization_id)
        acting_member = await self._require_default_admin_role(organization_id=resolved_organization_id)

        if (target_user_id := _coerce_uuid(member_id_or_email)) is None:
            user = await self.client.adapter.get_user_by_email(self.client.db, member_id_or_email)
            if user is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="member not found",
                )
            target_user_id = user.id

        target_member = await self.adapter.get_member(
            self.client.db,
            organization_id=resolved_organization_id,
            user_id=target_user_id,
        )
        if target_member is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="member not found",
            )

        if has_role(target_member.role, "owner") and not has_role(acting_member.role, "owner"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="only owners can remove owners",
            )

        removed = await self.adapter.remove_member(
            self.client.db,
            organization_id=resolved_organization_id,
            user_id=target_user_id,
        )

        if (
            removed
            and target_user_id == self.current_user.id
            and self.current_session.active_organization_id == resolved_organization_id
        ):
            await self.adapter.set_active_organization(
                self.client.db,
                session_id=self.current_session.id,
                organization_id=None,
            )

        return removed

    async def update_member_role(
        self,
        *,
        member_id: UUID,
        role: RoleValue[str],
        organization_id: UUID | None = None,
    ) -> MemberProtocol:
        resolved_organization_id = await self._resolve_required_organization_id(organization_id=organization_id)
        acting_member = await self._require_default_admin_role(organization_id=resolved_organization_id)

        target_member = await self.adapter.get_member_by_id(self.client.db, member_id)
        if target_member is None or target_member.organization_id != resolved_organization_id:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="member not found",
            )

        normalized_role = normalize_roles(role)
        if has_role(target_member.role, "owner") and not has_role(acting_member.role, "owner"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="only owners can update owner roles",
            )
        if has_role(normalized_role, "owner") and not has_role(acting_member.role, "owner"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="only owners can grant owner role",
            )

        if (
            updated := await self.adapter.update_member_role(
                self.client.db,
                member_id=member_id,
                role=normalized_role,
            )
        ) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="member not found",
            )
        return updated

    async def get_active_member(self) -> MemberProtocol:
        if (organization_id := self.current_session.active_organization_id) is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="no active organization",
            )

        if (
            member := await self.adapter.get_member(
                self.client.db,
                organization_id=organization_id,
                user_id=self.current_user.id,
            )
        ) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="member not found",
            )
        return member

    async def leave(self, *, organization_id: UUID) -> bool:
        member = await self.adapter.get_member(
            self.client.db,
            organization_id=organization_id,
            user_id=self.current_user.id,
        )
        if member is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="member not found",
            )

        removed = await self.adapter.remove_member(
            self.client.db,
            organization_id=organization_id,
            user_id=self.current_user.id,
        )
        if removed and self.current_session.active_organization_id == organization_id:
            await self.adapter.set_active_organization(
                self.client.db,
                session_id=self.current_session.id,
                organization_id=None,
            )
        return removed

    async def invite(
        self,
        *,
        email: str,
        role: RoleValue[str],
        organization_id: UUID | None = None,
        resend: bool = False,
        team_id: UUID | None = None,
    ) -> InvitationProtocol:
        resolved_organization_id = await self._resolve_required_organization_id(organization_id=organization_id)
        await self._require_default_admin_role(organization_id=resolved_organization_id)

        if team_id is not None:
            await self._validate_team_for_organization(
                organization_id=resolved_organization_id,
                team_id=team_id,
            )

        if (existing_user := await self.client.adapter.get_user_by_email(self.client.db, email)) is not None and (
            await self.adapter.get_member(
                self.client.db,
                organization_id=resolved_organization_id,
                user_id=existing_user.id,
            )
            is not None
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="user is already a member of this organization",
            )

        existing_invitation = await self.adapter.get_pending_invitation(
            self.client.db,
            organization_id=resolved_organization_id,
            email=email,
        )
        if existing_invitation is not None:
            if not resend:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="user is already invited to this organization",
                )
            await self.adapter.set_invitation_status(
                self.client.db,
                invitation_id=existing_invitation.id,
                status="canceled",
            )

        expires_at = datetime.now(UTC) + timedelta(seconds=self.settings.invitation_expires_in_seconds)
        invitation = await self.adapter.create_invitation(
            self.client.db,
            organization_id=resolved_organization_id,
            team_id=team_id,
            email=email,
            role=normalize_roles(role),
            inviter_id=self.current_user.id,
            expires_at=expires_at,
        )

        organization = await self.adapter.get_organization_by_id(self.client.db, resolved_organization_id)
        if self.settings.send_invitation_email and organization is not None:
            await self.settings.send_invitation_email(invitation, organization)

        return invitation

    async def accept_invitation(
        self,
        *,
        invitation_id: UUID,
    ) -> tuple[InvitationProtocol, MemberProtocol]:
        invitation = await self.adapter.get_invitation(self.client.db, invitation_id)
        if invitation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="invitation not found",
            )
        if invitation.status != "pending" or invitation.expires_at < datetime.now(UTC):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invitation is no longer valid",
            )
        if invitation.email.lower() != self.current_user.email.lower():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="you are not the recipient of this invitation",
            )

        member = await self.adapter.get_member(
            self.client.db,
            organization_id=invitation.organization_id,
            user_id=self.current_user.id,
        )
        if member is None:
            member = await self.adapter.create_member(
                self.client.db,
                organization_id=invitation.organization_id,
                user_id=self.current_user.id,
                role=normalize_roles(invitation.role),
            )

        if invitation.team_id is not None:
            await self._add_user_to_team(
                organization_id=invitation.organization_id,
                team_id=invitation.team_id,
                user_id=self.current_user.id,
            )

        if (
            accepted_invitation := await self.adapter.set_invitation_status(
                self.client.db,
                invitation_id=invitation.id,
                status="accepted",
            )
        ) is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="failed to update invitation status",
            )

        await self.adapter.set_active_organization(
            self.client.db,
            session_id=self.current_session.id,
            organization_id=invitation.organization_id,
        )

        return accepted_invitation, member

    async def cancel_invitation(self, *, invitation_id: UUID) -> InvitationProtocol:
        invitation = await self.adapter.get_invitation(self.client.db, invitation_id)
        if invitation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="invitation not found",
            )
        await self._require_default_admin_role(organization_id=invitation.organization_id)

        if invitation.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invitation is no longer pending",
            )

        if (
            canceled := await self.adapter.set_invitation_status(
                self.client.db,
                invitation_id=invitation_id,
                status="canceled",
            )
        ) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="invitation not found",
            )
        return canceled

    async def reject_invitation(self, *, invitation_id: UUID) -> InvitationProtocol:
        invitation = await self.adapter.get_invitation(self.client.db, invitation_id)
        if invitation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="invitation not found",
            )
        if invitation.status != "pending":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="invitation is no longer pending",
            )
        if invitation.email.lower() != self.current_user.email.lower():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="you are not the recipient of this invitation",
            )

        if (
            rejected := await self.adapter.set_invitation_status(
                self.client.db,
                invitation_id=invitation_id,
                status="rejected",
            )
        ) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="invitation not found",
            )
        return rejected

    async def get_invitation(self, *, invitation_id: UUID) -> InvitationProtocol:
        invitation = await self.adapter.get_invitation(self.client.db, invitation_id)
        if invitation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="invitation not found",
            )

        if invitation.email.lower() == self.current_user.email.lower():
            return invitation

        if (
            await self.adapter.get_member(
                self.client.db,
                organization_id=invitation.organization_id,
                user_id=self.current_user.id,
            )
            is None
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="you are not allowed to access this invitation",
            )

        return invitation

    async def list_invitations(self, *, organization_id: UUID | None = None) -> list[InvitationProtocol]:
        resolved_organization_id = await self._resolve_required_organization_id(organization_id=organization_id)
        await self._require_organization_membership(organization_id=resolved_organization_id)
        return await self.adapter.list_invitations(self.client.db, organization_id=resolved_organization_id)

    async def list_user_invitations(self, *, email: str | None = None) -> list[InvitationProtocol]:
        resolved_email = email or self.current_user.email
        if resolved_email.lower() != self.current_user.email.lower():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="cannot list invitations for another user",
            )
        return await self.adapter.list_user_invitations(self.client.db, email=resolved_email)

    async def _resolve_organization_id(
        self,
        *,
        organization_id: UUID | None,
        organization_slug: str | None,
    ) -> UUID | None:
        resolved_organization_id = organization_id
        if resolved_organization_id is None and organization_slug is not None:
            organization = await self.adapter.get_organization_by_slug(self.client.db, organization_slug)
            if organization is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="organization not found",
                )
            resolved_organization_id = organization.id
        if resolved_organization_id is None:
            resolved_organization_id = self.current_session.active_organization_id
        return resolved_organization_id

    async def _resolve_required_organization_id(self, *, organization_id: UUID | None) -> UUID:
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
        if not has_any_role(member.role, ["owner", "admin"]):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="insufficient organization permissions",
            )
        return member

    async def _require_owner_role(self, *, organization_id: UUID) -> MemberProtocol:
        member = await self._require_organization_membership(organization_id=organization_id)
        if not has_role(member.role, "owner"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="only owners can perform this action",
            )
        return member

    def _supports_team_adapter(self) -> bool:
        return all(hasattr(self.adapter, method) for method in ("get_team_by_id", "get_team_member", "add_team_member"))

    async def _validate_team_for_organization(self, *, organization_id: UUID, team_id: UUID) -> None:
        if not self._supports_team_adapter():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="team operations are not enabled for this adapter",
            )

        team = await self.adapter.get_team_by_id(self.client.db, team_id)  # type: ignore[attr-defined]
        if team is None or team.organization_id != organization_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="team not found in organization",
            )

    async def _add_user_to_team(
        self,
        *,
        organization_id: UUID,
        team_id: UUID,
        user_id: UUID,
    ) -> None:
        if not self._supports_team_adapter():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="team operations are not enabled for this adapter",
            )

        team = await self.adapter.get_team_by_id(self.client.db, team_id)  # type: ignore[attr-defined]
        if team is None or team.organization_id != organization_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="team not found in organization",
            )

        if await self.adapter.get_team_member(self.client.db, team_id=team_id, user_id=user_id) is None:  # type: ignore[attr-defined]
            await self.adapter.add_team_member(self.client.db, team_id=team_id, user_id=user_id)  # type: ignore[attr-defined]


def _coerce_uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except ValueError:
        return None
