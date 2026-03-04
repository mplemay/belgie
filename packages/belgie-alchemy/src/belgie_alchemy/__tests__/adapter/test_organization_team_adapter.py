from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from belgie_alchemy import TeamAdapter
from belgie_alchemy.__tests__.fixtures.org_models import (
    Account,
    OAuthState,
    Organization,
    OrganizationInvitation,
    OrganizationMember,
    Session,
    Team,
    TeamMember,
    User,
)


@pytest_asyncio.fixture
async def organization_team_adapter(alchemy_session: AsyncSession):  # noqa: ARG001
    adapter = TeamAdapter(
        user=User,
        account=Account,
        session=Session,
        oauth_state=OAuthState,
        organization=Organization,
        member=OrganizationMember,
        invitation=OrganizationInvitation,
        team=Team,
        team_member=TeamMember,
    )
    yield adapter


@pytest.mark.asyncio
async def test_create_and_list_organizations(
    organization_team_adapter: TeamAdapter,
    alchemy_session: AsyncSession,
) -> None:
    user = await organization_team_adapter.create_user(
        alchemy_session,
        email="owner@example.com",
    )

    organization = await organization_team_adapter.create_organization(
        alchemy_session,
        name="Acme",
        slug="acme",
    )
    member = await organization_team_adapter.create_member(
        alchemy_session,
        organization_id=organization.id,
        user_id=user.id,
        role="owner",
    )

    listed = await organization_team_adapter.list_organizations_for_user(
        alchemy_session,
        user.id,
    )
    fetched_member = await organization_team_adapter.get_member(
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
async def test_invitation_accept_flow(
    organization_team_adapter: TeamAdapter,
    alchemy_session: AsyncSession,
) -> None:
    inviter = await organization_team_adapter.create_user(
        alchemy_session,
        email="inviter@example.com",
    )
    invited = await organization_team_adapter.create_user(
        alchemy_session,
        email="invited@example.com",
    )
    organization = await organization_team_adapter.create_organization(
        alchemy_session,
        name="Org",
        slug="org",
    )
    await organization_team_adapter.create_member(
        alchemy_session,
        organization_id=organization.id,
        user_id=inviter.id,
        role="owner",
    )

    invitation = await organization_team_adapter.create_invitation(
        alchemy_session,
        organization_id=organization.id,
        email=invited.email,
        role="member",
        inviter_id=inviter.id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
    )
    pending = await organization_team_adapter.get_pending_invitation(
        alchemy_session,
        organization_id=organization.id,
        email=invited.email,
    )
    accepted = await organization_team_adapter.set_invitation_status(
        alchemy_session,
        invitation_id=invitation.id,
        status="accepted",
    )

    assert pending is not None
    assert pending.id == invitation.id
    assert accepted is not None
    assert accepted.status == "accepted"


@pytest.mark.asyncio
async def test_team_member_cleanup_when_removing_org_member(
    organization_team_adapter: TeamAdapter,
    alchemy_session: AsyncSession,
) -> None:
    owner = await organization_team_adapter.create_user(
        alchemy_session,
        email="owner2@example.com",
    )
    member_user = await organization_team_adapter.create_user(
        alchemy_session,
        email="member@example.com",
    )
    organization = await organization_team_adapter.create_organization(
        alchemy_session,
        name="Org2",
        slug="org2",
    )
    await organization_team_adapter.create_member(
        alchemy_session,
        organization_id=organization.id,
        user_id=owner.id,
        role="owner",
    )
    await organization_team_adapter.create_member(
        alchemy_session,
        organization_id=organization.id,
        user_id=member_user.id,
        role="member",
    )

    team = await organization_team_adapter.create_team(
        alchemy_session,
        organization_id=organization.id,
        name="Eng",
    )
    await organization_team_adapter.add_team_member(
        alchemy_session,
        team_id=team.id,
        user_id=member_user.id,
    )

    removed = await organization_team_adapter.remove_member(
        alchemy_session,
        organization_id=organization.id,
        user_id=member_user.id,
    )
    team_members = await organization_team_adapter.list_team_members(
        alchemy_session,
        team_id=team.id,
    )

    assert removed is True
    assert team_members == []
