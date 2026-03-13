from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from belgie_core.core.settings import BelgieSettings
from belgie_organization.plugin import OrganizationPlugin
from belgie_organization.settings import Organization as OrganizationSettings
from belgie_proto.organization import OrganizationAdapterProtocol
from belgie_proto.team import TeamAdapterProtocol
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from belgie_team.__tests__.fakes import (
    FakeInvitationRow,
    FakeMemberRow,
    FakeOrganizationRow,
    FakeTeamMemberRow,
    FakeTeamRow,
)
from belgie_team.plugin import TeamPlugin
from belgie_team.settings import Team

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from belgie_team.client import TeamClient


class DummyBelgie:
    def __init__(self, client: FakeBelgieClient, *, plugins: list[OrganizationPlugin | TeamPlugin]) -> None:
        self._client = client
        self.plugins = plugins

    async def __call__(self) -> FakeBelgieClient:
        return self._client


class FakeBelgieClient:
    def __init__(self, *, user) -> None:
        self.user = user
        self.db = SimpleNamespace()

    async def get_user(self, _security_scopes, _request):
        return self.user


class FakeTeamAdapter(
    TeamAdapterProtocol[
        FakeOrganizationRow,
        FakeMemberRow,
        FakeInvitationRow,
        FakeTeamRow,
        FakeTeamMemberRow,
    ],
):
    def __getattr__(self, _name: str) -> Callable[..., Awaitable[None]]:
        async def _unexpected(*_args: int, **_kwargs: int) -> None:
            return None

        return _unexpected


class FakeOrganizationAdapter(OrganizationAdapterProtocol[FakeOrganizationRow, FakeMemberRow, FakeInvitationRow]):
    def __getattr__(self, _name: str) -> Callable[..., Awaitable[None]]:
        async def _unexpected(*_args: int, **_kwargs: int) -> None:
            return None

        return _unexpected


def _build_fixture() -> tuple[TestClient, FakeBelgieClient]:
    settings = BelgieSettings(secret="test-secret", base_url="http://localhost:8000")
    user = SimpleNamespace(id=uuid4(), email="member@example.com")
    belgie_client = FakeBelgieClient(user=user)
    adapter = FakeTeamAdapter()

    organization_plugin = OrganizationPlugin(settings, OrganizationSettings(adapter=adapter))
    team_plugin = TeamPlugin(settings, Team(adapter=adapter))
    belgie = DummyBelgie(belgie_client, plugins=[organization_plugin, team_plugin])

    app = FastAPI()
    app.include_router(team_plugin.router(belgie))

    @app.get("/team-client")
    async def get_team_client(
        team: TeamClient[FakeOrganizationRow, FakeMemberRow, FakeInvitationRow, FakeTeamRow, FakeTeamMemberRow] = (
            Depends(team_plugin)
        ),
    ) -> dict[str, str]:
        return {"user_id": str(team.current_user.id)}

    return TestClient(app), belgie_client


def test_plugin_injects_team_client() -> None:
    client, belgie_client = _build_fixture()

    response = client.get("/team-client")

    assert response.status_code == 200
    assert response.json() == {"user_id": str(belgie_client.user.id)}


def test_legacy_team_routes_removed() -> None:
    client, _ = _build_fixture()

    response = client.get("/team/active")

    assert response.status_code == 404


def test_team_plugin_requires_organization_plugin_registration() -> None:
    settings = BelgieSettings(secret="test-secret", base_url="http://localhost:8000")
    team_plugin = TeamPlugin(settings, Team(adapter=FakeTeamAdapter()))
    belgie = DummyBelgie(
        FakeBelgieClient(user=SimpleNamespace(id=uuid4(), email="member@example.com")),
        plugins=[team_plugin],
    )

    with pytest.raises(RuntimeError, match="requires organization plugin"):
        team_plugin.router(belgie)


def test_team_plugin_requires_team_capable_organization_adapter() -> None:
    settings = BelgieSettings(secret="test-secret", base_url="http://localhost:8000")
    organization_plugin = OrganizationPlugin(settings, OrganizationSettings(adapter=FakeOrganizationAdapter()))
    team_plugin = TeamPlugin(settings, Team(adapter=FakeTeamAdapter()))
    belgie = DummyBelgie(
        FakeBelgieClient(user=SimpleNamespace(id=uuid4(), email="member@example.com")),
        plugins=[organization_plugin, team_plugin],
    )

    with pytest.raises(TypeError, match="team-capable adapter"):
        team_plugin.router(belgie)


@pytest.mark.asyncio
async def test_dependency_requires_router_initialization() -> None:
    settings = BelgieSettings(secret="test-secret", base_url="http://localhost:8000")
    team_plugin = TeamPlugin(settings, Team(adapter=FakeTeamAdapter()))

    with pytest.raises(RuntimeError, match="router initialization"):
        await team_plugin(SimpleNamespace(), SimpleNamespace())
