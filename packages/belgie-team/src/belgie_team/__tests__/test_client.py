from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from belgie_proto.team import TeamAdapterProtocol

from belgie_team.__tests__.fakes import (
    FakeInvitationRow,
    FakeMemberRow,
    FakeOrganizationRow,
    FakeTeamMemberRow,
    FakeTeamRow,
)
from belgie_team.client import TeamClient
from belgie_team.settings import Team


class FakeTeamAdapter(
    TeamAdapterProtocol[
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


def _build_client(*, adapter, current_individual=None) -> TeamClient:
    user = current_individual or SimpleNamespace(id=uuid4(), email="owner@example.com")
    return TeamClient(
        client=SimpleNamespace(db=SimpleNamespace()),
        settings=Team(
            adapter=adapter,
            maximum_teams_per_organization=None,
            maximum_members_per_team=None,
        ),
        current_individual=user,
    )


@pytest.mark.asyncio
async def test_create_requires_explicit_organization_id() -> None:
    team_client = _build_client(adapter=FakeTeamAdapter())

    with pytest.raises(TypeError, match="missing 1 required keyword-only argument: 'organization_id'"):
        await team_client.create(name="Platform")


@pytest.mark.asyncio
async def test_create_auto_adds_creator_to_team() -> None:
    organization_id = uuid4()
    individual_id = uuid4()
    team = SimpleNamespace(
        id=uuid4(),
        organization_id=organization_id,
        name="Platform",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    adapter = FakeTeamAdapter(
        get_member=AsyncMock(return_value=SimpleNamespace(role="owner")),
        list_teams=AsyncMock(return_value=[]),
        create_team=AsyncMock(return_value=team),
        get_team_member=AsyncMock(return_value=None),
        add_team_member=AsyncMock(),
    )

    team_client = _build_client(
        adapter=adapter,
        current_individual=SimpleNamespace(id=individual_id, email="owner@example.com"),
    )

    created = await team_client.create(name="Platform", organization_id=organization_id)

    assert created.id == team.id
    adapter.add_team_member.assert_awaited_once_with(
        team_client.client.db,
        team_id=team.id,
        individual_id=individual_id,
    )


@pytest.mark.asyncio
async def test_teams_require_explicit_organization_id() -> None:
    team_client = _build_client(adapter=FakeTeamAdapter())

    with pytest.raises(TypeError, match="missing 1 required keyword-only argument: 'organization_id'"):
        await team_client.teams()


@pytest.mark.asyncio
async def test_for_individual_uses_current_individual() -> None:
    user = SimpleNamespace(id=uuid4(), email="member@example.com")
    adapter = FakeTeamAdapter(list_teams_for_individual=AsyncMock(return_value=[]))
    team_client = _build_client(adapter=adapter, current_individual=user)

    await team_client.for_individual()

    adapter.list_teams_for_individual.assert_awaited_once_with(team_client.client.db, individual_id=user.id)


@pytest.mark.asyncio
async def test_members_require_explicit_team_id() -> None:
    team_client = _build_client(adapter=FakeTeamAdapter())

    with pytest.raises(TypeError, match="missing 1 required keyword-only argument: 'team_id'"):
        await team_client.members()
