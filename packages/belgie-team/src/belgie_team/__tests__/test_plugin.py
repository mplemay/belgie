from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING
from uuid import uuid4

from belgie_core.core.settings import BelgieSettings
from belgie_proto.team import TeamAdapterProtocol

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

from belgie_organization.plugin import OrganizationPlugin
from belgie_organization.settings import Organization as OrganizationSettings
from fastapi import FastAPI
from fastapi.testclient import TestClient

from belgie_team.plugin import TeamPlugin
from belgie_team.settings import Team


class DummyBelgie:
    def __init__(self, client: FakeBelgieClient, *, plugins: list[OrganizationPlugin | TeamPlugin]) -> None:
        self._client = client
        self.plugins = plugins

    async def __call__(self) -> FakeBelgieClient:
        return self._client


class FakeBelgieClient:
    def __init__(self, *, user, session) -> None:
        self.user = user
        self.session = session
        self.db = SimpleNamespace()

    async def get_user(self, _security_scopes, _request):
        return self.user

    async def get_session(self, _request):
        return self.session


class FakeTeamAdapter(TeamAdapterProtocol):
    def __init__(self, *, active_team, organization_member, team_member) -> None:
        self._active_team = active_team
        self._organization_member = organization_member
        self._team_member = team_member

    async def get_team_by_id(self, _session, _team_id):
        return self._active_team

    async def get_member(self, _session, *, organization_id, user_id):  # noqa: ARG002
        return self._organization_member

    async def get_team_member(self, _session, *, team_id, user_id):  # noqa: ARG002
        return self._team_member

    def __getattr__(self, name: str) -> Callable[..., Awaitable[None]]:
        async def _unexpected(*_args: int, **_kwargs: int) -> None:
            msg = f"unexpected adapter call: {name}"
            raise AssertionError(msg)

        return _unexpected


def _create_client(*, organization_member, team_member) -> tuple[TestClient, SimpleNamespace]:
    settings = BelgieSettings(secret="test-secret", base_url="http://localhost:8000")
    team = SimpleNamespace(
        id=uuid4(),
        organization_id=uuid4(),
        name="Engineering",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    user = SimpleNamespace(id=uuid4())
    session = SimpleNamespace(id=uuid4(), active_organization_id=team.organization_id, active_team_id=team.id)
    adapter = FakeTeamAdapter(
        active_team=team,
        organization_member=organization_member,
        team_member=team_member,
    )
    organization_plugin = OrganizationPlugin(settings, OrganizationSettings(adapter=adapter))
    team_plugin = TeamPlugin(settings, Team(adapter=adapter))
    belgie_client = FakeBelgieClient(user=user, session=session)
    belgie = DummyBelgie(belgie_client, plugins=[organization_plugin, team_plugin])

    app = FastAPI()
    app.include_router(team_plugin.router(belgie))
    return TestClient(app), team


def test_get_active_team_returns_null_when_user_not_in_team() -> None:
    client, _team = _create_client(
        organization_member=SimpleNamespace(id=uuid4()),
        team_member=None,
    )

    response = client.get("/team/active")

    assert response.status_code == 200
    assert response.json() is None


def test_get_active_team_returns_null_when_user_not_in_organization() -> None:
    client, _team = _create_client(
        organization_member=None,
        team_member=SimpleNamespace(id=uuid4()),
    )

    response = client.get("/team/active")

    assert response.status_code == 200
    assert response.json() is None


def test_get_active_team_returns_team_when_user_is_still_authorized() -> None:
    client, team = _create_client(
        organization_member=SimpleNamespace(id=uuid4()),
        team_member=SimpleNamespace(id=uuid4()),
    )

    response = client.get("/team/active")

    assert response.status_code == 200
    assert response.json() == {
        "id": str(team.id),
        "organization_id": str(team.organization_id),
        "name": team.name,
        "created_at": team.created_at.isoformat().replace("+00:00", "Z"),
        "updated_at": team.updated_at.isoformat().replace("+00:00", "Z"),
    }
