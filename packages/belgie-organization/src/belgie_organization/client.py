from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from belgie_proto.organization import (
    OrganizationAdapterProtocol,
    OrganizationTeamAdapterProtocol,
    PendingInvitationConflictError,
)
from belgie_proto.organization.invitation import InvitationProtocol
from belgie_proto.organization.member import MemberProtocol
from belgie_proto.organization.organization import OrganizationProtocol
from fastapi import HTTPException, status

from belgie_organization.roles import RoleValue, has_any_role, has_role, normalize_roles

if TYPE_CHECKING:
    from belgie_core import BelgieClient
    from belgie_proto.core.user import UserProtocol
    from belgie_proto.team.member import TeamMemberProtocol
    from belgie_proto.team.team import TeamProtocol

    from belgie_organization.settings import Organization


@dataclass(frozen=True, slots=True, kw_only=True)
class OrganizationClient[
    OrganizationT: OrganizationProtocol,
    MemberT: MemberProtocol,
    InvitationT: InvitationProtocol,
]:
    client: BelgieClient
    settings: Organization[OrganizationT, MemberT, InvitationT]
    adapter: OrganizationAdapterProtocol[OrganizationT, MemberT, InvitationT]
    current_user: UserProtocol[str]
    maximum_members_per_team: int | None = None

    async def create(  # noqa: PLR0913
        self,
        *,
        name: str,
        slug: str,
        role: RoleValue[str],
        logo: str | None = None,
        metadata: dict[str, object] | None = None,
        user_id: UUID | None = None,
    ) -> tuple[OrganizationT, MemberT]:
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
        return organization, member

    async def check_slug(self, *, slug: str) -> bool:
        return await self.adapter.get_organization_by_slug(self.client.db, slug) is not None

    async def for_user(self) -> list[OrganizationT]:
        return await self.adapter.list_organizations_for_user(self.client.db, self.current_user.id)

    async def details(
        self,
        *,
        organization_id: UUID | None = None,
        organization_slug: str | None = None,
    ) -> tuple[OrganizationT, list[MemberT], list[InvitationT]] | None:
        resolved_organization_id = await self._resolve_organization_id(
            organization_id=organization_id,
            organization_slug=organization_slug,
        )

        await self._require_default_admin_role(organization_id=resolved_organization_id)
        organization = await self.adapter.get_organization_by_id(self.client.db, resolved_organization_id)
        if organization is None:
            return None
        members = await self.adapter.list_members(self.client.db, organization_id=resolved_organization_id)
        invitations = await self.adapter.list_invitations(self.client.db, organization_id=resolved_organization_id)
        return organization, members, invitations

    async def update(
        self,
        *,
        organization_id: UUID,
        name: str | None = None,
        slug: str | None = None,
        logo: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> OrganizationT:
        await self._require_default_admin_role(organization_id=organization_id)

        if (
            slug is not None
            and (existing := await self.adapter.get_organization_by_slug(self.client.db, slug))
            and existing.id != organization_id
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="organization slug already taken",
            )

        if (
            updated := await self.adapter.update_organization(
                self.client.db,
                organization_id,
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
        return await self.adapter.delete_organization(self.client.db, organization_id)

    async def members(self, *, organization_id: UUID) -> list[MemberT]:
        await self._require_organization_membership(organization_id=organization_id)
        return await self.adapter.list_members(self.client.db, organization_id=organization_id)

    async def add_member(
        self,
        *,
        user_id: UUID,
        role: RoleValue[str],
        organization_id: UUID,
        team_id: UUID | None = None,
    ) -> MemberT:
        await self._require_default_admin_role(organization_id=organization_id)

        if await self.client.adapter.get_user_by_id(self.client.db, user_id) is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="user not found",
            )

        team_membership = None
        if team_id is not None:
            team_membership = await self._prepare_team_membership(
                organization_id=organization_id,
                team_id=team_id,
                user_id=user_id,
            )

        if (
            existing_member := await self.adapter.get_member(
                self.client.db,
                organization_id=organization_id,
                user_id=user_id,
            )
        ) is not None:
            member = existing_member
        else:
            member = await self.adapter.create_member(
                self.client.db,
                organization_id=organization_id,
                user_id=user_id,
                role=normalize_roles(role),
            )

        if team_membership is not None:
            team_adapter, existing_team_member = team_membership
            if existing_team_member is None:
                await team_adapter.add_team_member(self.client.db, team_id=team_id, user_id=user_id)
        return member

    async def remove_member(
        self,
        *,
        member_id_or_email: str,
        organization_id: UUID,
    ) -> bool:
        acting_member = await self._require_default_admin_role(organization_id=organization_id)

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
            organization_id=organization_id,
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
        await self._require_owner_membership_can_change(
            organization_id=organization_id,
            target_member=target_member,
        )

        return await self.adapter.remove_member(
            self.client.db,
            organization_id=organization_id,
            user_id=target_user_id,
        )

    async def update_member_role(
        self,
        *,
        member_id: UUID,
        role: RoleValue[str],
        organization_id: UUID,
    ) -> MemberT:
        acting_member = await self._require_default_admin_role(organization_id=organization_id)

        target_member = await self.adapter.get_member_by_id(self.client.db, member_id)
        if target_member is None or target_member.organization_id != organization_id:
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
        await self._require_owner_membership_can_change(
            organization_id=organization_id,
            target_member=target_member,
            next_role=normalized_role,
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
        await self._require_owner_membership_can_change(
            organization_id=organization_id,
            target_member=member,
        )

        return await self.adapter.remove_member(
            self.client.db,
            organization_id=organization_id,
            user_id=self.current_user.id,
        )

    async def invite(
        self,
        *,
        email: str,
        role: RoleValue[str],
        organization_id: UUID,
        resend: bool = False,
        team_id: UUID | None = None,
    ) -> InvitationT:
        await self._require_default_admin_role(organization_id=organization_id)

        if team_id is not None:
            await self._validate_team_for_organization(
                organization_id=organization_id,
                team_id=team_id,
            )

        if (existing_user := await self.client.adapter.get_user_by_email(self.client.db, email)) is not None and (
            await self.adapter.get_member(
                self.client.db,
                organization_id=organization_id,
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
            organization_id=organization_id,
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
        try:
            invitation = await self.adapter.create_invitation(
                self.client.db,
                organization_id=organization_id,
                team_id=team_id,
                email=email,
                role=normalize_roles(role),
                inviter_id=self.current_user.id,
                expires_at=expires_at,
            )
        except PendingInvitationConflictError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="user is already invited to this organization",
            ) from exc

        organization = await self.adapter.get_organization_by_id(self.client.db, organization_id)
        if self.settings.send_invitation_email and organization is not None:
            await self.settings.send_invitation_email(invitation, organization)

        return invitation

    async def accept_invitation(
        self,
        *,
        invitation_id: UUID,
    ) -> tuple[InvitationT, MemberT]:
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

        team_membership = None
        if invitation.team_id is not None:
            team_membership = await self._prepare_team_membership(
                organization_id=invitation.organization_id,
                team_id=invitation.team_id,
                user_id=self.current_user.id,
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

        if team_membership is not None:
            team_adapter, existing_team_member = team_membership
            if existing_team_member is None:
                await team_adapter.add_team_member(
                    self.client.db,
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

        return accepted_invitation, member

    async def cancel_invitation(self, *, invitation_id: UUID) -> InvitationT:
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

    async def reject_invitation(self, *, invitation_id: UUID) -> InvitationT:
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

    async def invitation(self, *, invitation_id: UUID) -> InvitationT:
        invitation = await self.adapter.get_invitation(self.client.db, invitation_id)
        if invitation is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="invitation not found",
            )

        if invitation.email.lower() == self.current_user.email.lower():
            return invitation

        await self._require_default_admin_role(organization_id=invitation.organization_id)
        return invitation

    async def invitations(self, *, organization_id: UUID) -> list[InvitationT]:
        await self._require_default_admin_role(organization_id=organization_id)
        return await self.adapter.list_invitations(self.client.db, organization_id=organization_id)

    async def user_invitations(self, *, email: str | None = None) -> list[InvitationT]:
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
    ) -> UUID:
        if organization_id is not None:
            return organization_id
        if organization_slug is not None:
            organization = await self.adapter.get_organization_by_slug(self.client.db, organization_slug)
            if organization is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="organization not found",
                )
            return organization.id
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="organization_id or organization_slug is required",
        )

    async def _require_organization_membership(self, *, organization_id: UUID) -> MemberT:
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

    async def _require_default_admin_role(self, *, organization_id: UUID) -> MemberT:
        member = await self._require_organization_membership(organization_id=organization_id)
        if not has_any_role(member.role, ["owner", "admin"]):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="insufficient organization permissions",
            )
        return member

    async def _require_owner_role(self, *, organization_id: UUID) -> MemberT:
        member = await self._require_organization_membership(organization_id=organization_id)
        if not has_role(member.role, "owner"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="only owners can perform this action",
            )
        return member

    def _require_team_adapter(
        self,
    ) -> OrganizationTeamAdapterProtocol[
        OrganizationT,
        MemberT,
        InvitationT,
        TeamProtocol,
        TeamMemberProtocol,
    ]:
        if not isinstance(self.adapter, OrganizationTeamAdapterProtocol):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="team operations are not enabled for this adapter",
            )
        return self.adapter

    async def _require_owner_membership_can_change(
        self,
        *,
        organization_id: UUID,
        target_member: MemberT,
        next_role: str | None = None,
    ) -> None:
        if not has_role(target_member.role, "owner"):
            return
        if next_role is None:
            if await self._organization_owner_count(organization_id=organization_id) > 1:
                return
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="organization must keep at least one owner",
            )
        if has_role(next_role, "owner"):
            return
        if await self._organization_owner_count(organization_id=organization_id) > 1:
            return
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="organization must keep at least one owner",
        )

    async def _organization_owner_count(self, *, organization_id: UUID) -> int:
        members = await self.adapter.list_members(self.client.db, organization_id=organization_id)
        return sum(1 for member in members if has_role(member.role, "owner"))

    async def _validate_team_for_organization(self, *, organization_id: UUID, team_id: UUID) -> None:
        team_adapter = self._require_team_adapter()
        team = await team_adapter.get_team_by_id(self.client.db, team_id)
        if team is None or team.organization_id != organization_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="team not found in organization",
            )

    async def _prepare_team_membership(
        self,
        *,
        organization_id: UUID,
        team_id: UUID,
        user_id: UUID,
    ) -> tuple[
        OrganizationTeamAdapterProtocol[
            OrganizationT,
            MemberT,
            InvitationT,
            TeamProtocol,
            TeamMemberProtocol,
        ],
        TeamMemberProtocol | None,
    ]:
        team_adapter = self._require_team_adapter()
        team = await team_adapter.get_team_by_id(self.client.db, team_id)
        if team is None or team.organization_id != organization_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="team not found in organization",
            )

        if (
            existing_team_member := await team_adapter.get_team_member(
                self.client.db,
                team_id=team_id,
                user_id=user_id,
            )
        ) is not None:
            return team_adapter, existing_team_member

        if self.maximum_members_per_team is not None and (
            len(await team_adapter.list_team_members(self.client.db, team_id=team_id)) >= self.maximum_members_per_team
        ):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="team member limit reached",
            )

        return team_adapter, None


def _coerce_uuid(value: str) -> UUID | None:
    try:
        return UUID(value)
    except ValueError:
        return None
