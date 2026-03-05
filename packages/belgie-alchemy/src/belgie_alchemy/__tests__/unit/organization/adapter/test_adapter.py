from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from belgie_alchemy.__tests__.fixtures.core.models import Account, OAuthState, Session, User
from belgie_alchemy.__tests__.fixtures.organization.models import (
    Organization,
    OrganizationInvitation,
    OrganizationMember,
)
from belgie_alchemy.organization import OrganizationAdapter


@pytest_asyncio.fixture
async def organization_adapter(alchemy_session: AsyncSession):  # noqa: ARG001
    adapter = OrganizationAdapter(
        user=User,
        account=Account,
        session=Session,
        oauth_state=OAuthState,
        organization=Organization,
        member=OrganizationMember,
        invitation=OrganizationInvitation,
    )
    yield adapter


@pytest.mark.asyncio
async def test_create_and_list_organizations(
    organization_adapter: OrganizationAdapter,
    alchemy_session: AsyncSession,
) -> None:
    user = await organization_adapter.create_user(
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
async def test_invitation_accept_flow(
    organization_adapter: OrganizationAdapter,
    alchemy_session: AsyncSession,
) -> None:
    inviter = await organization_adapter.create_user(
        alchemy_session,
        email="inviter@example.com",
    )
    invited = await organization_adapter.create_user(
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
