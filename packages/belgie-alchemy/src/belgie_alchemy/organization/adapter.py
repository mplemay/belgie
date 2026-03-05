from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from belgie_proto.core.account import AccountProtocol
from belgie_proto.core.oauth_state import OAuthStateProtocol
from belgie_proto.core.user import UserProtocol
from belgie_proto.organization import OrganizationAdapterProtocol
from belgie_proto.organization.invitation import InvitationProtocol
from belgie_proto.organization.member import MemberProtocol
from belgie_proto.organization.organization import OrganizationProtocol
from belgie_proto.organization.session import OrganizationSessionProtocol
from sqlalchemy import delete, select

from belgie_alchemy.core import BelgieAdapter

if TYPE_CHECKING:
    from uuid import UUID

    from belgie_proto.core.connection import DBConnection


class OrganizationAdapter[
    UserT: UserProtocol,
    AccountT: AccountProtocol,
    SessionT: OrganizationSessionProtocol,
    OAuthStateT: OAuthStateProtocol,
    OrganizationT: OrganizationProtocol,
    MemberT: MemberProtocol,
    InvitationT: InvitationProtocol,
](
    BelgieAdapter[UserT, AccountT, SessionT, OAuthStateT],
    OrganizationAdapterProtocol[OrganizationT, MemberT, InvitationT, SessionT],
):
    def __init__(  # noqa: PLR0913
        self,
        *,
        user: type[UserT],
        account: type[AccountT],
        session: type[SessionT],
        oauth_state: type[OAuthStateT],
        organization: type[OrganizationT],
        member: type[MemberT],
        invitation: type[InvitationT],
    ) -> None:
        super().__init__(
            user=user,
            account=account,
            session=session,
            oauth_state=oauth_state,
        )
        self.organization_model = organization
        self.member_model = member
        self.invitation_model = invitation

    async def create_organization(
        self,
        session: DBConnection,
        *,
        name: str,
        slug: str,
        logo: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> OrganizationT:
        organization = self.organization_model(
            name=name,
            slug=slug,
            logo=logo,
            organization_metadata=metadata,
        )
        session.add(organization)
        try:
            await session.commit()
            await session.refresh(organization)
        except Exception:
            await session.rollback()
            raise
        return organization

    async def get_organization_by_id(
        self,
        session: DBConnection,
        organization_id: UUID,
    ) -> OrganizationT | None:
        stmt = select(self.organization_model).where(self.organization_model.id == organization_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_organization_by_slug(
        self,
        session: DBConnection,
        slug: str,
    ) -> OrganizationT | None:
        stmt = select(self.organization_model).where(self.organization_model.slug == slug)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_organization(  # noqa: PLR0913
        self,
        session: DBConnection,
        organization_id: UUID,
        *,
        name: str | None = None,
        slug: str | None = None,
        logo: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> OrganizationT | None:
        organization = await self.get_organization_by_id(session, organization_id)
        if organization is None:
            return None

        updates: dict[str, Any] = {}
        if name is not None:
            updates["name"] = name
        if slug is not None:
            updates["slug"] = slug
        if logo is not None:
            updates["logo"] = logo
        if metadata is not None:
            updates["organization_metadata"] = metadata

        for key, value in updates.items():
            setattr(organization, key, value)

        organization.updated_at = datetime.now(UTC)
        try:
            await session.commit()
            await session.refresh(organization)
        except Exception:
            await session.rollback()
            raise
        return organization

    async def delete_organization(
        self,
        session: DBConnection,
        organization_id: UUID,
    ) -> bool:
        stmt = delete(self.organization_model).where(self.organization_model.id == organization_id)
        result = await session.execute(stmt)
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return result.rowcount > 0  # type: ignore[attr-defined]

    async def list_organizations_for_user(
        self,
        session: DBConnection,
        user_id: UUID,
    ) -> list[OrganizationT]:
        stmt = (
            select(self.organization_model)
            .join(
                self.member_model,
                self.member_model.organization_id == self.organization_model.id,
            )
            .where(self.member_model.user_id == user_id)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def create_member(
        self,
        session: DBConnection,
        *,
        organization_id: UUID,
        user_id: UUID,
        role: str,
    ) -> MemberT:
        member = self.member_model(
            organization_id=organization_id,
            user_id=user_id,
            role=role,
        )
        session.add(member)
        try:
            await session.commit()
            await session.refresh(member)
        except Exception:
            await session.rollback()
            raise
        return member

    async def get_member(
        self,
        session: DBConnection,
        *,
        organization_id: UUID,
        user_id: UUID,
    ) -> MemberT | None:
        stmt = select(self.member_model).where(
            self.member_model.organization_id == organization_id,
            self.member_model.user_id == user_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_member_by_id(
        self,
        session: DBConnection,
        member_id: UUID,
    ) -> MemberT | None:
        stmt = select(self.member_model).where(self.member_model.id == member_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_members(
        self,
        session: DBConnection,
        *,
        organization_id: UUID,
    ) -> list[MemberT]:
        stmt = select(self.member_model).where(self.member_model.organization_id == organization_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def update_member_role(
        self,
        session: DBConnection,
        *,
        member_id: UUID,
        role: str,
    ) -> MemberT | None:
        member = await self.get_member_by_id(session, member_id)
        if member is None:
            return None
        member.role = role
        member.updated_at = datetime.now(UTC)
        try:
            await session.commit()
            await session.refresh(member)
        except Exception:
            await session.rollback()
            raise
        return member

    async def remove_member(
        self,
        session: DBConnection,
        *,
        organization_id: UUID,
        user_id: UUID,
    ) -> bool:
        stmt = delete(self.member_model).where(
            self.member_model.organization_id == organization_id,
            self.member_model.user_id == user_id,
        )
        result = await session.execute(stmt)
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return result.rowcount > 0  # type: ignore[attr-defined]

    async def create_invitation(  # noqa: PLR0913
        self,
        session: DBConnection,
        *,
        organization_id: UUID,
        email: str,
        role: str,
        inviter_id: UUID,
        expires_at: datetime,
    ) -> InvitationT:
        invitation = self.invitation_model(
            organization_id=organization_id,
            email=email.lower(),
            role=role,
            status="pending",
            inviter_id=inviter_id,
            expires_at=expires_at,
        )
        session.add(invitation)
        try:
            await session.commit()
            await session.refresh(invitation)
        except Exception:
            await session.rollback()
            raise
        return invitation

    async def get_invitation(
        self,
        session: DBConnection,
        invitation_id: UUID,
    ) -> InvitationT | None:
        stmt = select(self.invitation_model).where(self.invitation_model.id == invitation_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_pending_invitation(
        self,
        session: DBConnection,
        *,
        organization_id: UUID,
        email: str,
    ) -> InvitationT | None:
        stmt = select(self.invitation_model).where(
            self.invitation_model.organization_id == organization_id,
            self.invitation_model.email == email.lower(),
            self.invitation_model.status == "pending",
            self.invitation_model.expires_at > datetime.now(UTC),
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_invitations(
        self,
        session: DBConnection,
        *,
        organization_id: UUID,
    ) -> list[InvitationT]:
        stmt = select(self.invitation_model).where(self.invitation_model.organization_id == organization_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def set_invitation_status(
        self,
        session: DBConnection,
        *,
        invitation_id: UUID,
        status: str,
    ) -> InvitationT | None:
        invitation = await self.get_invitation(session, invitation_id)
        if invitation is None:
            return None
        invitation.status = status
        invitation.updated_at = datetime.now(UTC)
        try:
            await session.commit()
            await session.refresh(invitation)
        except Exception:
            await session.rollback()
            raise
        return invitation

    async def set_active_organization(
        self,
        session: DBConnection,
        *,
        session_id: UUID,
        organization_id: UUID | None,
    ) -> SessionT | None:
        session_obj = await self.get_session(session, session_id)
        if session_obj is None:
            return None
        if not hasattr(session_obj, "active_organization_id"):
            msg = (
                "session model is missing 'active_organization_id'. Use OrganizationSessionMixin on your session model."
            )
            raise AttributeError(msg)
        return await self.update_session(
            session,
            session_id,
            active_organization_id=organization_id,
        )
