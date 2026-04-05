import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from belgie_alchemy.__tests__.fixtures.core.models import Account, Individual, OAuthAccount, OAuthState, Session
from belgie_alchemy.__tests__.fixtures.organization.models import (
    Organization,
    OrganizationInvitation,
    OrganizationMember,
)
from belgie_alchemy.__tests__.fixtures.team.models import Team, TeamMember
from belgie_alchemy.core import BelgieAdapter
from belgie_alchemy.team import TeamAdapter


@pytest_asyncio.fixture
async def core_adapter(alchemy_session: AsyncSession):  # noqa: ARG001
    adapter = BelgieAdapter(
        account=Account,
        individual=Individual,
        oauth_account=OAuthAccount,
        session=Session,
        oauth_state=OAuthState,
    )
    yield adapter


@pytest.fixture
def team_adapter() -> TeamAdapter:
    return TeamAdapter(
        organization=Organization,
        member=OrganizationMember,
        invitation=OrganizationInvitation,
        team=Team,
        team_member=TeamMember,
    )


@pytest.mark.asyncio
async def test_update_team(
    core_adapter: BelgieAdapter,
    team_adapter: TeamAdapter,
    alchemy_session: AsyncSession,
) -> None:
    owner = await core_adapter.create_individual(
        alchemy_session,
        email="team-update@example.com",
    )
    organization = await team_adapter.create_organization(
        alchemy_session,
        name="TeamOrg",
        slug="team-org",
    )
    await team_adapter.create_member(
        alchemy_session,
        organization_id=organization.id,
        individual_id=owner.id,
        role="owner",
    )
    team = await team_adapter.create_team(
        alchemy_session,
        organization_id=organization.id,
        name="Eng",
    )
    before = team.updated_at
    updated = await team_adapter.update_team(
        alchemy_session,
        team_id=team.id,
        name="Engineering",
    )
    assert updated is not None
    assert updated.name == "Engineering"
    assert updated.updated_at >= before
    fetched = await team_adapter.get_team_by_id(alchemy_session, team.id)
    assert fetched is not None
    assert fetched.name == "Engineering"


@pytest.mark.asyncio
async def test_team_member_cleanup_when_removing_org_member(
    core_adapter: BelgieAdapter,
    team_adapter: TeamAdapter,
    alchemy_session: AsyncSession,
) -> None:
    owner = await core_adapter.create_individual(
        alchemy_session,
        email="owner2@example.com",
    )
    member_user = await core_adapter.create_individual(
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
        individual_id=owner.id,
        role="owner",
    )
    await team_adapter.create_member(
        alchemy_session,
        organization_id=organization.id,
        individual_id=member_user.id,
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
        individual_id=member_user.id,
    )

    removed = await team_adapter.remove_member(
        alchemy_session,
        organization_id=organization.id,
        individual_id=member_user.id,
    )
    team_members = await team_adapter.list_team_members(
        alchemy_session,
        team_id=team.id,
    )

    assert removed is True
    assert team_members == []
