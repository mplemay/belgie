from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from belgie_alchemy.__tests__.fixtures.core.models import Account, OAuthState, Session, User
from belgie_alchemy.__tests__.fixtures.organization.models import (
    Organization,
    OrganizationInvitation,
    OrganizationMember,
)
from belgie_alchemy.__tests__.fixtures.team.models import Team
from belgie_alchemy.core import BelgieAdapter
from belgie_alchemy.organization import OrganizationAdapter


@pytest_asyncio.fixture
async def core_adapter(alchemy_session: AsyncSession):  # noqa: ARG001
    adapter = BelgieAdapter(
        user=User,
        account=Account,
        session=Session,
        oauth_state=OAuthState,
    )
    yield adapter


@pytest_asyncio.fixture
async def organization_adapter(core_adapter: BelgieAdapter, alchemy_session: AsyncSession):  # noqa: ARG001
    adapter = OrganizationAdapter(
        organization=Organization,
        member=OrganizationMember,
        invitation=OrganizationInvitation,
    )
    yield adapter


@pytest.mark.asyncio
async def test_create_and_list_organizations(
    core_adapter: BelgieAdapter,
    organization_adapter: OrganizationAdapter,
    alchemy_session: AsyncSession,
) -> None:
    user = await core_adapter.create_user(
        alchemy_session,
        email="owner@example.com",
    )

    organization = await organization_adapter.create_organization(
        alchemy_session,
        name="Acme",
        slug="acme",
    )
    member = await organization_adapter.create_member(
        alchemy_session,
        organization_id=organization.id,
        user_id=user.id,
        role="owner",
    )

    listed = await organization_adapter.list_organizations_for_user(
        alchemy_session,
        user.id,
    )
    fetched_member = await organization_adapter.get_member(
        alchemy_session,
        organization_id=organization.id,
        user_id=user.id,
    )

    assert member.organization_id == organization.id
    assert len(listed) == 1
    assert listed[0].id == organization.id
    assert fetched_member is not None
    assert fetched_member.role == "owner"


@pytest.mark.asyncio
async def test_update_organization(
    organization_adapter: OrganizationAdapter,
    alchemy_session: AsyncSession,
) -> None:
    organization = await organization_adapter.create_organization(
        alchemy_session,
        name="Acme",
        slug="acme",
    )
    before = organization.updated_at
    updated = await organization_adapter.update_organization(
        alchemy_session,
        organization.id,
        name="Acme Corp",
        slug="acme-corp",
    )
    assert updated is not None
    assert updated.name == "Acme Corp"
    assert updated.slug == "acme-corp"
    assert updated.updated_at >= before


@pytest.mark.asyncio
async def test_update_organization_missing_returns_none(
    organization_adapter: OrganizationAdapter,
    alchemy_session: AsyncSession,
) -> None:
    missing = await organization_adapter.update_organization(
        alchemy_session,
        uuid4(),
        name="Ghost",
    )
    assert missing is None


@pytest.mark.asyncio
async def test_update_member_role(
    core_adapter: BelgieAdapter,
    organization_adapter: OrganizationAdapter,
    alchemy_session: AsyncSession,
) -> None:
    user = await core_adapter.create_user(
        alchemy_session,
        email="member-role@example.com",
    )
    organization = await organization_adapter.create_organization(
        alchemy_session,
        name="RoleOrg",
        slug="role-org",
    )
    member = await organization_adapter.create_member(
        alchemy_session,
        organization_id=organization.id,
        user_id=user.id,
        role="member",
    )
    updated = await organization_adapter.update_member_role(
        alchemy_session,
        member_id=member.id,
        role="owner",
    )
    assert updated is not None
    assert updated.role == "owner"
    fetched = await organization_adapter.get_member(
        alchemy_session,
        organization_id=organization.id,
        user_id=user.id,
    )
    assert fetched is not None
    assert fetched.role == "owner"


@pytest.mark.asyncio
async def test_invitation_accept_flow(
    core_adapter: BelgieAdapter,
    organization_adapter: OrganizationAdapter,
    alchemy_session: AsyncSession,
) -> None:
    inviter = await core_adapter.create_user(
        alchemy_session,
        email="inviter@example.com",
    )
    invited = await core_adapter.create_user(
        alchemy_session,
        email="invited@example.com",
    )
    organization = await organization_adapter.create_organization(
        alchemy_session,
        name="Org",
        slug="org",
    )
    await organization_adapter.create_member(
        alchemy_session,
        organization_id=organization.id,
        user_id=inviter.id,
        role="owner",
    )

    invitation = await organization_adapter.create_invitation(
        alchemy_session,
        organization_id=organization.id,
        team_id=None,
        email=invited.email,
        role="member",
        inviter_id=inviter.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    pending = await organization_adapter.get_pending_invitation(
        alchemy_session,
        organization_id=organization.id,
        email=invited.email,
    )
    accepted = await organization_adapter.set_invitation_status(
        alchemy_session,
        invitation_id=invitation.id,
        status="accepted",
    )

    assert pending is not None
    assert pending.id == invitation.id
    assert accepted is not None
    assert accepted.status == "accepted"
    assert accepted.updated_at is not None


@pytest.mark.asyncio
async def test_invitation_team_id_and_list_user_invitations(
    core_adapter: BelgieAdapter,
    organization_adapter: OrganizationAdapter,
    alchemy_session: AsyncSession,
) -> None:
    inviter = await core_adapter.create_user(
        alchemy_session,
        email="inviter2@example.com",
    )
    invited = await core_adapter.create_user(
        alchemy_session,
        email="invited2@example.com",
    )
    organization = await organization_adapter.create_organization(
        alchemy_session,
        name="Org3",
        slug="org3",
    )
    await organization_adapter.create_member(
        alchemy_session,
        organization_id=organization.id,
        user_id=inviter.id,
        role="owner",
    )
    team = Team(name=f"team-{uuid4()}", organization_id=organization.id)
    alchemy_session.add(team)
    await alchemy_session.commit()
    await alchemy_session.refresh(team)

    invitation = await organization_adapter.create_invitation(
        alchemy_session,
        organization_id=organization.id,
        team_id=team.id,
        email=invited.email,
        role="member",
        inviter_id=inviter.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    user_invitations = await organization_adapter.list_user_invitations(
        alchemy_session,
        email=invited.email,
    )

    assert invitation.team_id == team.id
    assert len(user_invitations) == 1
    assert user_invitations[0].id == invitation.id


@pytest.mark.asyncio
async def test_expired_pending_invitation_is_reissued(
    core_adapter: BelgieAdapter,
    organization_adapter: OrganizationAdapter,
    alchemy_session: AsyncSession,
) -> None:
    inviter = await core_adapter.create_user(alchemy_session, email="inviter3@example.com")
    organization = await organization_adapter.create_organization(
        alchemy_session,
        name="Org4",
        slug="org4",
    )
    await organization_adapter.create_member(
        alchemy_session,
        organization_id=organization.id,
        user_id=inviter.id,
        role="owner",
    )

    expired_invitation = await organization_adapter.create_invitation(
        alchemy_session,
        organization_id=organization.id,
        team_id=None,
        email="invitee3@example.com",
        role="member",
        inviter_id=inviter.id,
        expires_at=datetime.now(UTC) - timedelta(hours=1),
    )
    replacement_invitation = await organization_adapter.create_invitation(
        alchemy_session,
        organization_id=organization.id,
        team_id=None,
        email="invitee3@example.com",
        role="member",
        inviter_id=inviter.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    invitations = await organization_adapter.list_invitations(
        alchemy_session,
        organization_id=organization.id,
    )

    assert expired_invitation.id != replacement_invitation.id
    assert sorted(invitation.status for invitation in invitations) == ["expired", "pending"]
