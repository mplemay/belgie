from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from belgie_proto.core.account import AccountProtocol
from belgie_proto.core.oauth_state import OAuthStateProtocol
from belgie_proto.core.session import SessionProtocol
from belgie_proto.core.user import UserProtocol
from belgie_proto.organization.invitation import InvitationProtocol
from belgie_proto.organization.member import MemberProtocol
from belgie_proto.organization.organization import OrganizationProtocol
from belgie_proto.team import TeamAdapterProtocol
from belgie_proto.team.member import TeamMemberProtocol
from belgie_proto.team.team import TeamProtocol
from sqlalchemy import delete, select

if TYPE_CHECKING:
    from uuid import UUID

    from belgie_proto.core import AdapterProtocol
    from belgie_proto.core.connection import DBConnection

    from belgie_alchemy.organization import OrganizationAdapter


class TeamAdapter[
    UserT: UserProtocol,
    AccountT: AccountProtocol,
    SessionT: SessionProtocol,
    OAuthStateT: OAuthStateProtocol,
    OrganizationT: OrganizationProtocol,
    MemberT: MemberProtocol,
    InvitationT: InvitationProtocol,
    TeamT: TeamProtocol,
    TeamMemberT: TeamMemberProtocol,
](
    TeamAdapterProtocol[
        OrganizationT,
        MemberT,
        InvitationT,
        TeamT,
        TeamMemberT,
        SessionT,
    ],
):
    def __init__(
        self,
        *,
        core: AdapterProtocol[UserT, AccountT, SessionT, OAuthStateT],
        organization_adapter: OrganizationAdapter[
            UserT,
            AccountT,
            SessionT,
            OAuthStateT,
            OrganizationT,
            MemberT,
            InvitationT,
        ],
        team: type[TeamT],
        team_member: type[TeamMemberT],
    ) -> None:
        self.core = core
        self.organization_adapter = organization_adapter
        self.team_model = team
        self.team_member_model = team_member

    async def create_organization(
        self,
        session: DBConnection,
        *,
        name: str,
        slug: str,
        logo: str | None = None,
        metadata: dict[str, object] | None = None,
    ) -> OrganizationT:
        return await self.organization_adapter.create_organization(
            session,
            name=name,
            slug=slug,
            logo=logo,
            metadata=metadata,
        )

    async def get_organization_by_id(
        self,
        session: DBConnection,
        organization_id: UUID,
    ) -> OrganizationT | None:
        return await self.organization_adapter.get_organization_by_id(session, organization_id)

    async def get_organization_by_slug(
        self,
        session: DBConnection,
        slug: str,
    ) -> OrganizationT | None:
        return await self.organization_adapter.get_organization_by_slug(session, slug)

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
        return await self.organization_adapter.update_organization(
            session,
            organization_id,
            name=name,
            slug=slug,
            logo=logo,
            metadata=metadata,
        )

    async def delete_organization(
        self,
        session: DBConnection,
        organization_id: UUID,
    ) -> bool:
        return await self.organization_adapter.delete_organization(session, organization_id)

    async def list_organizations_for_user(
        self,
        session: DBConnection,
        user_id: UUID,
    ) -> list[OrganizationT]:
        return await self.organization_adapter.list_organizations_for_user(session, user_id)

    async def create_member(
        self,
        session: DBConnection,
        *,
        organization_id: UUID,
        user_id: UUID,
        role: str,
    ) -> MemberT:
        return await self.organization_adapter.create_member(
            session,
            organization_id=organization_id,
            user_id=user_id,
            role=role,
        )

    async def get_member(
        self,
        session: DBConnection,
        *,
        organization_id: UUID,
        user_id: UUID,
    ) -> MemberT | None:
        return await self.organization_adapter.get_member(
            session,
            organization_id=organization_id,
            user_id=user_id,
        )

    async def get_member_by_id(
        self,
        session: DBConnection,
        member_id: UUID,
    ) -> MemberT | None:
        return await self.organization_adapter.get_member_by_id(session, member_id)

    async def list_members(
        self,
        session: DBConnection,
        *,
        organization_id: UUID,
    ) -> list[MemberT]:
        return await self.organization_adapter.list_members(session, organization_id=organization_id)

    async def update_member_role(
        self,
        session: DBConnection,
        *,
        member_id: UUID,
        role: str,
    ) -> MemberT | None:
        return await self.organization_adapter.update_member_role(
            session,
            member_id=member_id,
            role=role,
        )

    async def remove_member(
        self,
        session: DBConnection,
        *,
        organization_id: UUID,
        user_id: UUID,
    ) -> bool:
        team_ids_stmt = select(self.team_model.id).where(self.team_model.organization_id == organization_id)
        await session.execute(
            delete(self.team_member_model).where(
                self.team_member_model.user_id == user_id,
                self.team_member_model.team_id.in_(team_ids_stmt),
            ),
        )
        member_delete_result = await session.execute(
            delete(self.organization_adapter.member_model).where(
                self.organization_adapter.member_model.organization_id == organization_id,
                self.organization_adapter.member_model.user_id == user_id,
            ),
        )
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return member_delete_result.rowcount > 0  # type: ignore[attr-defined]

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
    ) -> InvitationT:
        return await self.organization_adapter.create_invitation(
            session,
            organization_id=organization_id,
            team_id=team_id,
            email=email,
            role=role,
            inviter_id=inviter_id,
            expires_at=expires_at,
        )

    async def get_invitation(
        self,
        session: DBConnection,
        invitation_id: UUID,
    ) -> InvitationT | None:
        return await self.organization_adapter.get_invitation(session, invitation_id)

    async def get_pending_invitation(
        self,
        session: DBConnection,
        *,
        organization_id: UUID,
        email: str,
    ) -> InvitationT | None:
        return await self.organization_adapter.get_pending_invitation(
            session,
            organization_id=organization_id,
            email=email,
        )

    async def list_invitations(
        self,
        session: DBConnection,
        *,
        organization_id: UUID,
    ) -> list[InvitationT]:
        return await self.organization_adapter.list_invitations(session, organization_id=organization_id)

    async def list_user_invitations(
        self,
        session: DBConnection,
        *,
        email: str,
    ) -> list[InvitationT]:
        return await self.organization_adapter.list_user_invitations(session, email=email)

    async def set_invitation_status(
        self,
        session: DBConnection,
        *,
        invitation_id: UUID,
        status: str,
    ) -> InvitationT | None:
        return await self.organization_adapter.set_invitation_status(
            session,
            invitation_id=invitation_id,
            status=status,
        )

    async def create_team(
        self,
        session: DBConnection,
        *,
        organization_id: UUID,
        name: str,
    ) -> TeamT:
        team = self.team_model(
            organization_id=organization_id,
            name=name,
        )
        session.add(team)
        try:
            await session.commit()
            await session.refresh(team)
        except Exception:
            await session.rollback()
            raise
        return team

    async def get_team_by_id(
        self,
        session: DBConnection,
        team_id: UUID,
    ) -> TeamT | None:
        stmt = select(self.team_model).where(self.team_model.id == team_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_teams(
        self,
        session: DBConnection,
        *,
        organization_id: UUID,
    ) -> list[TeamT]:
        stmt = select(self.team_model).where(self.team_model.organization_id == organization_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def update_team(
        self,
        session: DBConnection,
        *,
        team_id: UUID,
        name: str,
    ) -> TeamT | None:
        team = await self.get_team_by_id(session, team_id)
        if team is None:
            return None
        team.name = name
        team.updated_at = datetime.now(UTC)
        try:
            await session.commit()
            await session.refresh(team)
        except Exception:
            await session.rollback()
            raise
        return team

    async def remove_team(
        self,
        session: DBConnection,
        *,
        team_id: UUID,
    ) -> bool:
        stmt = delete(self.team_model).where(self.team_model.id == team_id)
        result = await session.execute(stmt)
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return result.rowcount > 0  # type: ignore[attr-defined]

    async def add_team_member(
        self,
        session: DBConnection,
        *,
        team_id: UUID,
        user_id: UUID,
    ) -> TeamMemberT:
        team_member = self.team_member_model(
            team_id=team_id,
            user_id=user_id,
        )
        session.add(team_member)
        try:
            await session.commit()
            await session.refresh(team_member)
        except Exception:
            await session.rollback()
            raise
        return team_member

    async def remove_team_member(
        self,
        session: DBConnection,
        *,
        team_id: UUID,
        user_id: UUID,
    ) -> bool:
        stmt = delete(self.team_member_model).where(
            self.team_member_model.team_id == team_id,
            self.team_member_model.user_id == user_id,
        )
        result = await session.execute(stmt)
        try:
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        return result.rowcount > 0  # type: ignore[attr-defined]

    async def get_team_member(
        self,
        session: DBConnection,
        *,
        team_id: UUID,
        user_id: UUID,
    ) -> TeamMemberT | None:
        stmt = select(self.team_member_model).where(
            self.team_member_model.team_id == team_id,
            self.team_member_model.user_id == user_id,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_team_members(
        self,
        session: DBConnection,
        *,
        team_id: UUID,
    ) -> list[TeamMemberT]:
        stmt = select(self.team_member_model).where(self.team_member_model.team_id == team_id)
        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def list_teams_for_user(
        self,
        session: DBConnection,
        *,
        user_id: UUID,
    ) -> list[TeamT]:
        stmt = (
            select(self.team_model)
            .join(
                self.team_member_model,
                self.team_member_model.team_id == self.team_model.id,
            )
            .where(self.team_member_model.user_id == user_id)
        )
        result = await session.execute(stmt)
        return list(result.scalars().all())
