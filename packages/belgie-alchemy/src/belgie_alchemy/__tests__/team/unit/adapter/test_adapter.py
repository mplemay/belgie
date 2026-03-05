import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from belgie_alchemy.__tests__.core.fixtures.models import Account, OAuthState, Session, User
from belgie_alchemy.__tests__.organization.fixtures.models import (
    Organization,
    OrganizationInvitation,
    OrganizationMember,
)
from belgie_alchemy.__tests__.team.fixtures.models import Team, TeamMember
from belgie_alchemy.team.adapter import TeamAdapter


@pytest_asyncio.fixture
async def team_adapter(alchemy_session: AsyncSession):  # noqa: ARG001
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
async def test_team_member_cleanup_when_removing_org_member(
    team_adapter: TeamAdapter,
    alchemy_session: AsyncSession,
) -> None:
    owner = await team_adapter.create_user(
        alchemy_session,
        email="owner2@example.com",
    )
    member_user = await team_adapter.create_user(
        alchemy_session,
        email="member@example.com",
    )
    organization = await team_adapter.create_organization(
        alchemy_session,
        name="Org2",
        slug="org2",
    )
    await team_adapter.create_member(
        alchemy_session,
        organization_id=organization.id,
        user_id=owner.id,
        role="owner",
    )
    await team_adapter.create_member(
        alchemy_session,
        organization_id=organization.id,
        user_id=member_user.id,
        role="member",
    )

    team = await team_adapter.create_team(
        alchemy_session,
        organization_id=organization.id,
        name="Eng",
    )
    await team_adapter.add_team_member(
        alchemy_session,
        team_id=team.id,
        user_id=member_user.id,
    )

    removed = await team_adapter.remove_member(
        alchemy_session,
        organization_id=organization.id,
        user_id=member_user.id,
    )
    team_members = await team_adapter.list_team_members(
        alchemy_session,
        team_id=team.id,
    )

    assert removed is True
    assert team_members == []
