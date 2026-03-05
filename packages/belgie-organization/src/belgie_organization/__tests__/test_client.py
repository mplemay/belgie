from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from belgie_organization.client import OrganizationClient


class OrganizationRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


@pytest.mark.asyncio
async def test_create_requires_explicit_role() -> None:
    organization_client = OrganizationClient(
        client=SimpleNamespace(db=SimpleNamespace(), adapter=SimpleNamespace()),
        settings=SimpleNamespace(
            allow_user_to_create_organization=True,
            invitation_expires_in_seconds=3600,
            send_invitation_email=None,
        ),
        adapter=SimpleNamespace(),
        current_user=SimpleNamespace(id=uuid4(), email="owner@example.com"),
        current_session=SimpleNamespace(id=uuid4(), active_organization_id=None),
    )

    with pytest.raises(TypeError, match="missing 1 required keyword-only argument: 'role'"):
        await organization_client.create(name="Acme", slug="acme")


@pytest.mark.asyncio
async def test_invite_normalizes_roles_and_supports_team_id() -> None:
    organization_id = uuid4()
    inviter_id = uuid4()
    team_id = uuid4()
    invitation = SimpleNamespace(
        id=uuid4(),
        organization_id=organization_id,
        team_id=team_id,
        email="member@example.com",
        role="member",
        status="pending",
        inviter_id=inviter_id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    adapter = SimpleNamespace(
        get_member=AsyncMock(return_value=SimpleNamespace(role="owner")),
        get_user_by_email=AsyncMock(return_value=None),
        get_pending_invitation=AsyncMock(return_value=None),
        create_invitation=AsyncMock(return_value=invitation),
        get_organization_by_id=AsyncMock(return_value=SimpleNamespace(id=organization_id)),
        get_team_by_id=AsyncMock(return_value=SimpleNamespace(id=team_id, organization_id=organization_id)),
        get_team_member=AsyncMock(return_value=None),
        add_team_member=AsyncMock(),
    )
    send_invitation_email = AsyncMock()

    organization_client = OrganizationClient(
        client=SimpleNamespace(
            db=SimpleNamespace(),
            adapter=SimpleNamespace(get_user_by_email=adapter.get_user_by_email),
        ),
        settings=SimpleNamespace(
            allow_user_to_create_organization=True,
            invitation_expires_in_seconds=3600,
            send_invitation_email=send_invitation_email,
        ),
        adapter=adapter,
        current_user=SimpleNamespace(id=inviter_id, email="owner@example.com"),
        current_session=SimpleNamespace(id=uuid4(), active_organization_id=organization_id),
    )

    result = await organization_client.invite(
        email="member@example.com",
        role=[OrganizationRole.MEMBER],
        team_id=team_id,
    )

    assert result.id == invitation.id
    adapter.create_invitation.assert_awaited_once()
    assert adapter.create_invitation.await_args.kwargs["role"] == "member"
    assert adapter.create_invitation.await_args.kwargs["team_id"] == team_id
    send_invitation_email.assert_awaited_once()


@pytest.mark.asyncio
async def test_accept_invitation_adds_team_membership() -> None:
    organization_id = uuid4()
    team_id = uuid4()
    user_id = uuid4()
    now = datetime.now(UTC)

    pending_invitation = SimpleNamespace(
        id=uuid4(),
        organization_id=organization_id,
        team_id=team_id,
        email="member@example.com",
        role="member",
        status="pending",
        inviter_id=uuid4(),
        expires_at=now + timedelta(hours=1),
        created_at=now,
        updated_at=now,
    )
    accepted_invitation = SimpleNamespace(**{**pending_invitation.__dict__, "status": "accepted"})
    created_member = SimpleNamespace(
        id=uuid4(),
        organization_id=organization_id,
        user_id=user_id,
        role="member",
        created_at=now,
        updated_at=now,
    )

    adapter = SimpleNamespace(
        get_invitation=AsyncMock(return_value=pending_invitation),
        get_member=AsyncMock(return_value=None),
        create_member=AsyncMock(return_value=created_member),
        get_team_by_id=AsyncMock(return_value=SimpleNamespace(id=team_id, organization_id=organization_id)),
        get_team_member=AsyncMock(return_value=None),
        add_team_member=AsyncMock(),
        set_invitation_status=AsyncMock(return_value=accepted_invitation),
        set_active_organization=AsyncMock(),
    )

    organization_client = OrganizationClient(
        client=SimpleNamespace(db=SimpleNamespace(), adapter=SimpleNamespace()),
        settings=SimpleNamespace(
            allow_user_to_create_organization=True,
            invitation_expires_in_seconds=3600,
            send_invitation_email=None,
        ),
        adapter=adapter,
        current_user=SimpleNamespace(id=user_id, email="member@example.com"),
        current_session=SimpleNamespace(id=uuid4(), active_organization_id=None),
    )

    accepted, member = await organization_client.accept_invitation(invitation_id=pending_invitation.id)

    assert accepted.status == "accepted"
    assert member.id == created_member.id
    adapter.add_team_member.assert_awaited_once_with(
        organization_client.client.db,
        team_id=team_id,
        user_id=user_id,
    )
    adapter.set_active_organization.assert_awaited_once()
