from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from belgie_team.client import TeamClient


@pytest.mark.asyncio
async def test_create_auto_adds_creator_to_team() -> None:
    organization_id = uuid4()
    user_id = uuid4()
    team = SimpleNamespace(
        id=uuid4(),
        organization_id=organization_id,
        name="Platform",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )

    adapter = SimpleNamespace(
        get_member=AsyncMock(return_value=SimpleNamespace(role="owner")),
        list_teams=AsyncMock(return_value=[]),
        create_team=AsyncMock(return_value=team),
        get_team_member=AsyncMock(return_value=None),
        add_team_member=AsyncMock(),
    )

    team_client = TeamClient(
        client=SimpleNamespace(db=SimpleNamespace()),
        settings=SimpleNamespace(
            maximum_teams_per_organization=None,
            maximum_members_per_team=None,
        ),
        adapter=adapter,
        current_user=SimpleNamespace(id=user_id, email="owner@example.com"),
        current_session=SimpleNamespace(id=uuid4(), active_organization_id=organization_id, active_team_id=None),
    )

    created = await team_client.create(name="Platform")

    assert created.id == team.id
    adapter.add_team_member.assert_awaited_once_with(
        team_client.client.db,
        team_id=team.id,
        user_id=user_id,
    )
