from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from belgie_proto.organization import OrganizationAdapterProtocol, PendingInvitationConflictError
from belgie_proto.organization.invitation import InvitationProtocol
from belgie_proto.organization.member import MemberProtocol
from belgie_proto.organization.organization import OrganizationProtocol
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError

if TYPE_CHECKING:
    from uuid import UUID

    from belgie_proto.core.connection import DBConnection


class OrganizationAdapter[
    OrganizationT: OrganizationProtocol,
    MemberT: MemberProtocol,
    InvitationT: InvitationProtocol,
](OrganizationAdapterProtocol[OrganizationT, MemberT, InvitationT]):
    def __init__(
        self,
        *,
        organization: type[OrganizationT],
        member: type[MemberT],
        invitation: type[InvitationT],
    ) -> None:
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
    ) -> OrganizationT:
        organization = self.organization_model(
            name=name,
            slug=slug,
            logo=logo,
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
        stripe_customer_id: str | None = None,
    ) -> OrganizationT | None:
        organization = await self.get_organization_by_id(session, organization_id)
        if organization is None:
            return None

        if name is not None:
            organization.name = name
        if slug is not None:
            organization.slug = slug
        if logo is not None:
            organization.logo = logo
        if stripe_customer_id is not None and hasattr(organization, "stripe_customer_id"):
            organization.stripe_customer_id = stripe_customer_id
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
        organization = await self.get_organization_by_id(session, organization_id)
        if organization is None:
            return False

        await session.delete(organization)
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return True

    async def list_organizations_for_individual(
        self,
        session: DBConnection,
        individual_id: UUID,
    ) -> list[OrganizationT]:
        stmt = (
            select(self.organization_model)
            .join(
                self.member_model,
                self.member_model.organization_id == self.organization_model.id,
            )
            .where(self.member_model.individual_id == individual_id)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def create_member(
        self,
        session: DBConnection,
        *,
        organization_id: UUID,
        individual_id: UUID,
        role: str,
    ) -> MemberT:
        member = self.member_model(
            organization_id=organization_id,
            individual_id=individual_id,
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
        individual_id: UUID,
    ) -> MemberT | None:
        stmt = select(self.member_model).where(
            self.member_model.organization_id == organization_id,
            self.member_model.individual_id == individual_id,
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
        stmt = (
            update(self.member_model)
            .where(self.member_model.id == member_id)
            .values(role=role, updated_at=datetime.now(UTC))
            .returning(self.member_model)
        )
        try:
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            # If RETURNING is empty, still commit: rollback would drop unrelated pending ORM
            # work that may exist on the same session alongside this call.
            await session.commit()
            if row is None:
                return None
            await session.refresh(row)
        except Exception:
            await session.rollback()
            raise
        return row

    async def remove_member(
        self,
        session: DBConnection,
        *,
        organization_id: UUID,
        individual_id: UUID,
    ) -> bool:
        stmt = delete(self.member_model).where(
            self.member_model.organization_id == organization_id,
            self.member_model.individual_id == individual_id,
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
        team_id: UUID | None,
        email: str,
        role: str,
        inviter_individual_id: UUID,
        expires_at: datetime,
    ) -> InvitationT:
        normalized_email = email.lower()
        now = datetime.now(UTC)
        await self._expire_pending_invitations(
            session,
            organization_id=organization_id,
            email=normalized_email,
            now=now,
        )
        invitation = self.invitation_model(
            organization_id=organization_id,
            team_id=team_id,
            email=normalized_email,
            role=role,
            status="pending",
            inviter_individual_id=inviter_individual_id,
            expires_at=expires_at,
        )
        session.add(invitation)
        try:
            await session.commit()
            await session.refresh(invitation)
        except IntegrityError as exc:
            await session.rollback()
            if (
                pending_invitation := await self.get_pending_invitation(
                    session,
                    organization_id=organization_id,
                    email=normalized_email,
                )
            ) is not None and pending_invitation.id != invitation.id:
                raise PendingInvitationConflictError from exc
            raise
        except Exception:
            await session.rollback()
            raise
        return invitation

    async def _expire_pending_invitations(
        self,
        session: DBConnection,
        *,
        organization_id: UUID,
        email: str,
        now: datetime,
    ) -> None:
        stmt = (
            update(self.invitation_model)
            .where(
                self.invitation_model.organization_id == organization_id,
                self.invitation_model.email == email,
                self.invitation_model.status == "pending",
                self.invitation_model.expires_at <= now,
            )
            .values(status="expired", updated_at=now)
        )
        await session.execute(stmt)

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

    async def list_individual_invitations(
        self,
        session: DBConnection,
        *,
        email: str,
    ) -> list[InvitationT]:
        stmt = select(self.invitation_model).where(
            self.invitation_model.email == email.lower(),
            self.invitation_model.status == "pending",
            self.invitation_model.expires_at > datetime.now(UTC),
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def set_invitation_status(
        self,
        session: DBConnection,
        *,
        invitation_id: UUID,
        status: str,
    ) -> InvitationT | None:
        stmt = (
            update(self.invitation_model)
            .where(self.invitation_model.id == invitation_id)
            .values(status=status, updated_at=datetime.now(UTC))
            .returning(self.invitation_model)
        )
        try:
            result = await session.execute(stmt)
            row = result.scalar_one_or_none()
            # If RETURNING is empty, still commit: rollback would drop unrelated pending ORM
            # work that may exist on the same session alongside this call.
            await session.commit()
            if row is None:
                return None
            await session.refresh(row)
        except Exception:
            await session.rollback()
            raise
        return row
