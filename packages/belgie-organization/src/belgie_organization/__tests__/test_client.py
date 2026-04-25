from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from belgie_proto.organization import (
    OrganizationAdapterProtocol,
    OrganizationTeamAdapterProtocol,
    PendingInvitationConflictError,
)
from fastapi import HTTPException

from belgie_organization.__tests__.fakes import (
    FakeInvitationRow,
    FakeMemberRow,
    FakeOrganizationRow,
    FakeTeamMemberRow,
    FakeTeamRow,
)
from belgie_organization.client import OrganizationClient
from belgie_organization.settings import Organization


class OrganizationRole(StrEnum):
    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"


class FakeOrganizationAdapter(OrganizationAdapterProtocol[FakeOrganizationRow, FakeMemberRow, FakeInvitationRow]):
    def __init__(self, **methods: AsyncMock) -> None:
        self._methods: dict[str, AsyncMock] = methods
        for name, method in methods.items():
            setattr(self, name, method)

    def __getattr__(self, name: str) -> AsyncMock:
        if name in self._methods:
            return self._methods[name]
        return AsyncMock(side_effect=AssertionError(f"unexpected adapter call: {name}"))


class FakeOrganizationTeamAdapter(
    OrganizationTeamAdapterProtocol[
        FakeOrganizationRow,
        FakeMemberRow,
        FakeInvitationRow,
        FakeTeamRow,
        FakeTeamMemberRow,
    ],
):
    def __init__(self, **methods: AsyncMock) -> None:
        self._methods: dict[str, AsyncMock] = methods
        for name, method in methods.items():
            setattr(self, name, method)

    def __getattr__(self, name: str) -> AsyncMock:
        if name in self._methods:
            return self._methods[name]
        return AsyncMock(side_effect=AssertionError(f"unexpected adapter call: {name}"))


def _build_client(
    *,
    adapter,
    current_individual=None,
    core_adapter=None,
    send_invitation_email=None,
    maximum_members_per_team=None,
) -> OrganizationClient:
    user = current_individual or SimpleNamespace(id=uuid4(), email="owner@example.com")
    client_adapter = core_adapter or SimpleNamespace(
        get_individual_by_email=AsyncMock(return_value=None),
        get_individual_by_id=AsyncMock(return_value=None),
    )
    return OrganizationClient(
        client=SimpleNamespace(db=SimpleNamespace(), adapter=client_adapter),
        settings=Organization(
            adapter=adapter,
            allow_user_to_create_organization=True,
            invitation_expires_in_seconds=3600,
            send_invitation_email=send_invitation_email,
        ),
        current_individual=user,
        maximum_members_per_team=maximum_members_per_team,
    )


@pytest.mark.asyncio
async def test_create_requires_explicit_role() -> None:
    organization_client = _build_client(adapter=FakeOrganizationAdapter())

    with pytest.raises(TypeError, match="missing 1 required keyword-only argument: 'role'"):
        await organization_client.create(name="Acme", slug="acme")


@pytest.mark.asyncio
async def test_create_does_not_accept_removed_active_organization_flag() -> None:
    organization_client = _build_client(adapter=FakeOrganizationAdapter())

    with pytest.raises(TypeError, match="unexpected keyword argument 'keep_current_active_organization'"):
        await organization_client.create(
            name="Acme",
            slug="acme",
            role="owner",
            keep_current_active_organization=True,
        )


@pytest.mark.asyncio
async def test_for_individual_uses_current_individual() -> None:
    user = SimpleNamespace(id=uuid4(), email="owner@example.com")
    adapter = FakeOrganizationAdapter(list_organizations_for_individual=AsyncMock(return_value=[]))
    organization_client = _build_client(adapter=adapter, current_individual=user)

    await organization_client.for_individual()

    adapter.list_organizations_for_individual.assert_awaited_once_with(organization_client.client.db, user.id)


@pytest.mark.asyncio
async def test_details_requires_explicit_selector() -> None:
    organization_client = _build_client(adapter=FakeOrganizationAdapter())

    with pytest.raises(HTTPException, match="organization_id or organization_slug is required"):
        await organization_client.details()


@pytest.mark.asyncio
async def test_details_requires_admin_role() -> None:
    organization_id = uuid4()
    adapter = FakeOrganizationAdapter(
        get_member=AsyncMock(return_value=SimpleNamespace(role="member")),
    )
    organization_client = _build_client(adapter=adapter)

    with pytest.raises(HTTPException, match="insufficient organization permissions"):
        await organization_client.details(organization_id=organization_id)


@pytest.mark.asyncio
async def test_invite_normalizes_roles_and_supports_team_id() -> None:
    organization_id = uuid4()
    inviter_individual_id = uuid4()
    team_id = uuid4()
    invitation = SimpleNamespace(
        id=uuid4(),
        organization_id=organization_id,
        team_id=team_id,
        email="member@example.com",
        role="member",
        status="pending",
        inviter_individual_id=inviter_individual_id,
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    adapter = FakeOrganizationTeamAdapter(
        get_member=AsyncMock(return_value=SimpleNamespace(role="owner")),
        get_pending_invitation=AsyncMock(return_value=None),
        create_invitation=AsyncMock(return_value=invitation),
        get_organization_by_id=AsyncMock(return_value=SimpleNamespace(id=organization_id)),
        get_team_by_id=AsyncMock(return_value=SimpleNamespace(id=team_id, organization_id=organization_id)),
        get_team_member=AsyncMock(return_value=None),
        add_team_member=AsyncMock(),
    )
    send_invitation_email = AsyncMock()

    organization_client = _build_client(
        adapter=adapter,
        core_adapter=SimpleNamespace(
            get_individual_by_email=AsyncMock(return_value=None),
            get_individual_by_id=AsyncMock(return_value=None),
        ),
        current_individual=SimpleNamespace(id=inviter_individual_id, email="owner@example.com"),
        send_invitation_email=send_invitation_email,
    )

    result = await organization_client.invite(
        email="member@example.com",
        role=[OrganizationRole.MEMBER],
        organization_id=organization_id,
        team_id=team_id,
    )

    assert result.id == invitation.id
    adapter.create_invitation.assert_awaited_once()
    assert adapter.create_invitation.await_args.kwargs["role"] == "member"
    assert adapter.create_invitation.await_args.kwargs["team_id"] == team_id
    send_invitation_email.assert_awaited_once()


@pytest.mark.asyncio
async def test_invite_with_team_id_requires_team_capable_adapter() -> None:
    organization_id = uuid4()
    adapter = FakeOrganizationAdapter(
        get_member=AsyncMock(return_value=SimpleNamespace(role="owner")),
        get_pending_invitation=AsyncMock(return_value=None),
    )
    organization_client = _build_client(adapter=adapter)

    with pytest.raises(HTTPException, match="team operations are not enabled"):
        await organization_client.invite(
            email="member@example.com",
            role="member",
            organization_id=organization_id,
            team_id=uuid4(),
        )


@pytest.mark.asyncio
async def test_invite_translates_pending_invitation_conflict() -> None:
    organization_id = uuid4()
    adapter = FakeOrganizationAdapter(
        get_member=AsyncMock(return_value=SimpleNamespace(role="owner")),
        get_pending_invitation=AsyncMock(return_value=None),
        create_invitation=AsyncMock(side_effect=PendingInvitationConflictError),
    )
    organization_client = _build_client(adapter=adapter)

    with pytest.raises(HTTPException, match="individual is already invited to this organization"):
        await organization_client.invite(
            email="member@example.com",
            role="member",
            organization_id=organization_id,
        )


@pytest.mark.asyncio
async def test_accept_invitation_adds_team_membership() -> None:
    organization_id = uuid4()
    team_id = uuid4()
    individual_id = uuid4()
    now = datetime.now(UTC)

    pending_invitation = SimpleNamespace(
        id=uuid4(),
        organization_id=organization_id,
        team_id=team_id,
        email="member@example.com",
        role="member",
        status="pending",
        inviter_individual_id=uuid4(),
        expires_at=now + timedelta(hours=1),
        created_at=now,
        updated_at=now,
    )
    accepted_invitation = SimpleNamespace(**{**pending_invitation.__dict__, "status": "accepted"})
    created_member = SimpleNamespace(
        id=uuid4(),
        organization_id=organization_id,
        individual_id=individual_id,
        role="member",
        created_at=now,
        updated_at=now,
    )

    adapter = FakeOrganizationTeamAdapter(
        get_invitation=AsyncMock(return_value=pending_invitation),
        get_member=AsyncMock(return_value=None),
        create_member=AsyncMock(return_value=created_member),
        get_team_by_id=AsyncMock(return_value=SimpleNamespace(id=team_id, organization_id=organization_id)),
        get_team_member=AsyncMock(return_value=None),
        add_team_member=AsyncMock(),
        set_invitation_status=AsyncMock(return_value=accepted_invitation),
    )

    organization_client = _build_client(
        adapter=adapter,
        current_individual=SimpleNamespace(id=individual_id, email="member@example.com"),
    )

    accepted, member = await organization_client.accept_invitation(invitation_id=pending_invitation.id)

    assert accepted.status == "accepted"
    assert member.id == created_member.id
    adapter.add_team_member.assert_awaited_once_with(
        organization_client.client.db,
        team_id=team_id,
        individual_id=individual_id,
    )


@pytest.mark.asyncio
async def test_add_member_rejects_full_team() -> None:
    organization_id = uuid4()
    team_id = uuid4()
    individual_id = uuid4()
    adapter = FakeOrganizationTeamAdapter(
        get_member=AsyncMock(side_effect=[SimpleNamespace(role="owner"), None]),
        get_team_by_id=AsyncMock(return_value=SimpleNamespace(id=team_id, organization_id=organization_id)),
        get_team_member=AsyncMock(return_value=None),
        list_team_members=AsyncMock(return_value=[SimpleNamespace(id=uuid4())]),
        create_member=AsyncMock(),
        add_team_member=AsyncMock(),
    )
    organization_client = _build_client(
        adapter=adapter,
        core_adapter=SimpleNamespace(
            get_individual_by_email=AsyncMock(return_value=None),
            get_individual_by_id=AsyncMock(return_value=SimpleNamespace(id=individual_id)),
        ),
        maximum_members_per_team=1,
    )

    with pytest.raises(HTTPException, match="team member limit reached"):
        await organization_client.add_member(
            individual_id=individual_id,
            role="member",
            organization_id=organization_id,
            team_id=team_id,
        )

    adapter.create_member.assert_not_awaited()
    adapter.add_team_member.assert_not_awaited()


@pytest.mark.asyncio
async def test_accept_invitation_rejects_full_team() -> None:
    organization_id = uuid4()
    team_id = uuid4()
    individual_id = uuid4()
    now = datetime.now(UTC)
    pending_invitation = SimpleNamespace(
        id=uuid4(),
        organization_id=organization_id,
        team_id=team_id,
        email="member@example.com",
        role="member",
        status="pending",
        inviter_individual_id=uuid4(),
        expires_at=now + timedelta(hours=1),
        created_at=now,
        updated_at=now,
    )
    adapter = FakeOrganizationTeamAdapter(
        get_invitation=AsyncMock(return_value=pending_invitation),
        get_team_by_id=AsyncMock(return_value=SimpleNamespace(id=team_id, organization_id=organization_id)),
        get_team_member=AsyncMock(return_value=None),
        list_team_members=AsyncMock(return_value=[SimpleNamespace(id=uuid4())]),
        get_member=AsyncMock(return_value=None),
        create_member=AsyncMock(),
        add_team_member=AsyncMock(),
        set_invitation_status=AsyncMock(),
    )
    organization_client = _build_client(
        adapter=adapter,
        current_individual=SimpleNamespace(id=individual_id, email="member@example.com"),
        maximum_members_per_team=1,
    )

    with pytest.raises(HTTPException, match="team member limit reached"):
        await organization_client.accept_invitation(invitation_id=pending_invitation.id)

    adapter.create_member.assert_not_awaited()
    adapter.add_team_member.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_runs_after_update_hook() -> None:
    organization_id = uuid4()
    updated = SimpleNamespace(id=organization_id, name="Acme", slug="acme", logo=None)
    hook = AsyncMock()
    adapter = FakeOrganizationAdapter(
        get_member=AsyncMock(return_value=SimpleNamespace(role="owner")),
        get_organization_by_slug=AsyncMock(return_value=None),
        update_organization=AsyncMock(return_value=updated),
    )
    organization_client = OrganizationClient(
        client=SimpleNamespace(db=SimpleNamespace(), adapter=SimpleNamespace()),
        settings=Organization(
            adapter=adapter,
            after_update=hook,
        ),
        current_individual=SimpleNamespace(id=uuid4(), email="owner@example.com"),
    )

    result = await organization_client.update(organization_id=organization_id, name="Acme")

    assert result is updated
    hook.assert_awaited_once_with(organization_client, updated)


@pytest.mark.asyncio
async def test_delete_runs_before_delete_hook() -> None:
    organization_id = uuid4()
    organization = SimpleNamespace(id=organization_id, name="Acme", slug="acme", logo=None)
    hook = AsyncMock()
    adapter = FakeOrganizationAdapter(
        get_member=AsyncMock(return_value=SimpleNamespace(role="owner")),
        get_organization_by_id=AsyncMock(return_value=organization),
        delete_organization=AsyncMock(return_value=True),
    )
    organization_client = OrganizationClient(
        client=SimpleNamespace(db=SimpleNamespace(), adapter=SimpleNamespace()),
        settings=Organization(
            adapter=adapter,
            before_delete=hook,
        ),
        current_individual=SimpleNamespace(id=uuid4(), email="owner@example.com"),
    )

    deleted = await organization_client.delete(organization_id=organization_id)

    assert deleted is True
    hook.assert_awaited_once_with(organization_client, organization)


@pytest.mark.asyncio
async def test_add_member_runs_after_member_add_hook() -> None:
    organization_id = uuid4()
    individual_id = uuid4()
    organization = SimpleNamespace(id=organization_id, name="Acme", slug="acme", logo=None)
    member = SimpleNamespace(
        id=uuid4(),
        organization_id=organization_id,
        individual_id=individual_id,
        role="member",
    )
    hook = AsyncMock()
    adapter = FakeOrganizationAdapter(
        get_member=AsyncMock(side_effect=[SimpleNamespace(role="owner"), None]),
        create_member=AsyncMock(return_value=member),
        get_organization_by_id=AsyncMock(return_value=organization),
    )
    organization_client = _build_client(
        adapter=adapter,
        core_adapter=SimpleNamespace(
            get_individual_by_email=AsyncMock(return_value=None),
            get_individual_by_id=AsyncMock(return_value=SimpleNamespace(id=individual_id)),
        ),
    )
    object.__setattr__(
        organization_client,
        "settings",
        organization_client.settings.model_copy(
            update={"after_member_add": hook},
        ),
    )

    result = await organization_client.add_member(
        individual_id=individual_id,
        role="member",
        organization_id=organization_id,
    )

    assert result is member
    hook.assert_awaited_once_with(organization_client, organization, member)


@pytest.mark.asyncio
async def test_remove_member_runs_after_member_remove_hook() -> None:
    organization_id = uuid4()
    member = SimpleNamespace(
        id=uuid4(),
        organization_id=organization_id,
        individual_id=uuid4(),
        role="member",
    )
    organization = SimpleNamespace(id=organization_id, name="Acme", slug="acme", logo=None)
    hook = AsyncMock()
    adapter = FakeOrganizationAdapter(
        get_member=AsyncMock(side_effect=[SimpleNamespace(role="owner"), member]),
        get_organization_by_id=AsyncMock(return_value=organization),
        remove_member=AsyncMock(return_value=True),
    )
    organization_client = _build_client(
        adapter=adapter,
        core_adapter=SimpleNamespace(
            get_individual_by_email=AsyncMock(return_value=SimpleNamespace(id=member.individual_id)),
            get_individual_by_id=AsyncMock(return_value=None),
        ),
    )
    object.__setattr__(
        organization_client,
        "settings",
        organization_client.settings.model_copy(
            update={"after_member_remove": hook},
        ),
    )

    removed = await organization_client.remove_member(
        member_id_or_email="member@example.com",
        organization_id=organization_id,
    )

    assert removed is True
    hook.assert_awaited_once_with(organization_client, organization, member)


@pytest.mark.asyncio
async def test_accept_invitation_runs_after_invitation_accept_hook() -> None:
    organization_id = uuid4()
    team_id = uuid4()
    individual_id = uuid4()
    now = datetime.now(UTC)
    pending_invitation = SimpleNamespace(
        id=uuid4(),
        organization_id=organization_id,
        team_id=team_id,
        email="member@example.com",
        role="member",
        status="pending",
        inviter_individual_id=uuid4(),
        expires_at=now + timedelta(hours=1),
        created_at=now,
        updated_at=now,
    )
    accepted_invitation = SimpleNamespace(**{**pending_invitation.__dict__, "status": "accepted"})
    created_member = SimpleNamespace(
        id=uuid4(),
        organization_id=organization_id,
        individual_id=individual_id,
        role="member",
        created_at=now,
        updated_at=now,
    )
    organization = SimpleNamespace(id=organization_id, name="Acme", slug="acme", logo=None)
    hook = AsyncMock()
    adapter = FakeOrganizationTeamAdapter(
        get_invitation=AsyncMock(return_value=pending_invitation),
        get_member=AsyncMock(return_value=None),
        create_member=AsyncMock(return_value=created_member),
        get_team_by_id=AsyncMock(return_value=SimpleNamespace(id=team_id, organization_id=organization_id)),
        get_team_member=AsyncMock(return_value=None),
        add_team_member=AsyncMock(),
        set_invitation_status=AsyncMock(return_value=accepted_invitation),
        get_organization_by_id=AsyncMock(return_value=organization),
    )
    organization_client = _build_client(
        adapter=adapter,
        current_individual=SimpleNamespace(id=individual_id, email="member@example.com"),
    )
    object.__setattr__(
        organization_client,
        "settings",
        organization_client.settings.model_copy(
            update={"after_invitation_accept": hook},
        ),
    )

    accepted, member = await organization_client.accept_invitation(invitation_id=pending_invitation.id)

    assert accepted is accepted_invitation
    assert member is created_member
    hook.assert_awaited_once_with(organization_client, organization, accepted_invitation, created_member)
    adapter.set_invitation_status.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_invitation_rejects_non_admin_member() -> None:
    organization_id = uuid4()
    invitation = SimpleNamespace(
        id=uuid4(),
        organization_id=organization_id,
        team_id=None,
        email="member@example.com",
        role="member",
        status="pending",
        inviter_individual_id=uuid4(),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    adapter = FakeOrganizationAdapter(
        get_invitation=AsyncMock(return_value=invitation),
        get_member=AsyncMock(return_value=SimpleNamespace(role="member")),
    )
    organization_client = _build_client(
        adapter=adapter,
        current_individual=SimpleNamespace(id=uuid4(), email="viewer@example.com"),
    )

    with pytest.raises(HTTPException, match="insufficient organization permissions"):
        await organization_client.invitation(invitation_id=invitation.id)


@pytest.mark.asyncio
async def test_list_invitations_requires_admin_role() -> None:
    organization_id = uuid4()
    adapter = FakeOrganizationAdapter(
        get_member=AsyncMock(return_value=SimpleNamespace(role="member")),
    )
    organization_client = _build_client(adapter=adapter)

    with pytest.raises(HTTPException, match="insufficient organization permissions"):
        await organization_client.invitations(organization_id=organization_id)


@pytest.mark.asyncio
async def test_remove_member_blocks_last_owner_removal() -> None:
    organization_id = uuid4()
    owner = SimpleNamespace(id=uuid4(), organization_id=organization_id, individual_id=uuid4(), role="owner")
    adapter = FakeOrganizationAdapter(
        get_member=AsyncMock(side_effect=[owner, owner]),
        list_members=AsyncMock(return_value=[owner]),
    )
    organization_client = _build_client(
        adapter=adapter,
        current_individual=SimpleNamespace(id=owner.individual_id, email="owner@example.com"),
    )

    with pytest.raises(HTTPException, match="organization must keep at least one owner"):
        await organization_client.remove_member(
            member_id_or_email=str(owner.individual_id),
            organization_id=organization_id,
        )


@pytest.mark.asyncio
async def test_update_member_role_blocks_last_owner_demotion() -> None:
    organization_id = uuid4()
    owner = SimpleNamespace(id=uuid4(), organization_id=organization_id, individual_id=uuid4(), role="owner")
    adapter = FakeOrganizationAdapter(
        get_member=AsyncMock(return_value=SimpleNamespace(role="owner")),
        get_member_by_id=AsyncMock(return_value=owner),
        list_members=AsyncMock(return_value=[owner]),
    )
    organization_client = _build_client(adapter=adapter)

    with pytest.raises(HTTPException, match="organization must keep at least one owner"):
        await organization_client.update_member_role(
            member_id=owner.id,
            role="admin",
            organization_id=organization_id,
        )


@pytest.mark.asyncio
async def test_leave_blocks_last_owner() -> None:
    organization_id = uuid4()
    owner = SimpleNamespace(id=uuid4(), organization_id=organization_id, individual_id=uuid4(), role="owner")
    adapter = FakeOrganizationAdapter(
        get_member=AsyncMock(return_value=owner),
        list_members=AsyncMock(return_value=[owner]),
    )
    organization_client = _build_client(
        adapter=adapter,
        current_individual=SimpleNamespace(id=owner.individual_id, email="owner@example.com"),
    )

    with pytest.raises(HTTPException, match="organization must keep at least one owner"):
        await organization_client.leave(organization_id=organization_id)
