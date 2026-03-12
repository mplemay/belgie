from __future__ import annotations

from types import SimpleNamespace
from typing import TYPE_CHECKING
from uuid import uuid4

import pytest
from belgie_core.core.settings import BelgieSettings
from belgie_proto.organization import OrganizationAdapterProtocol
from belgie_proto.team import TeamAdapterProtocol
from belgie_team.plugin import TeamPlugin
from belgie_team.settings import Team
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from belgie_organization.plugin import OrganizationPlugin
from belgie_organization.settings import Organization

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from belgie_organization.client import OrganizationClient


class DummyBelgie:
    def __init__(self, client: FakeBelgieClient) -> None:
        self._client = client
        self.plugins: list[OrganizationPlugin | TeamPlugin] = []

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


class FakeOrganizationAdapter(OrganizationAdapterProtocol):
    def __getattr__(self, _name: str) -> Callable[..., Awaitable[None]]:
        async def _unexpected(*_args: int, **_kwargs: int) -> None:
            return None

        return _unexpected


class FakeOrganizationTeamAdapter(TeamAdapterProtocol):
    def __getattr__(self, _name: str) -> Callable[..., Awaitable[None]]:
        async def _unexpected(*_args: int, **_kwargs: int) -> None:
            return None

        return _unexpected


def _build_fixture() -> tuple[TestClient, FakeBelgieClient]:
    settings = BelgieSettings(secret="test-secret", base_url="http://localhost:8000")
    user = SimpleNamespace(id=uuid4(), email="member@example.com")
    session = SimpleNamespace(id=uuid4(), active_organization_id=None)
    belgie_client = FakeBelgieClient(user=user, session=session)
    belgie = DummyBelgie(belgie_client)

    plugin = OrganizationPlugin(settings, Organization(adapter=FakeOrganizationAdapter()))

    app = FastAPI()
    app.include_router(plugin.router(belgie))

    @app.get("/organization-client")
    async def get_org_client(
        organization: OrganizationClient = Depends(plugin),
    ) -> dict[str, str]:
        return {
            "user_id": str(organization.current_user.id),
            "session_id": str(organization.current_session.id),
        }

    return TestClient(app), belgie_client


def test_plugin_injects_organization_client() -> None:
    client, belgie_client = _build_fixture()

    response = client.get("/organization-client")

    assert response.status_code == 200
    assert response.json() == {
        "user_id": str(belgie_client.user.id),
        "session_id": str(belgie_client.session.id),
    }


def test_legacy_plugin_routes_removed() -> None:
    client, _ = _build_fixture()

    response = client.get("/organization/active")

    assert response.status_code == 404


def test_plugin_injects_team_member_limit_from_team_plugin() -> None:
    settings = BelgieSettings(secret="test-secret", base_url="http://localhost:8000")
    user = SimpleNamespace(id=uuid4(), email="member@example.com")
    session = SimpleNamespace(id=uuid4(), active_organization_id=None)
    belgie_client = FakeBelgieClient(user=user, session=session)
    belgie = DummyBelgie(belgie_client)
    adapter = FakeOrganizationTeamAdapter()

    organization_plugin = OrganizationPlugin(settings, Organization(adapter=adapter))
    team_plugin = TeamPlugin(settings, Team(adapter=adapter, maximum_members_per_team=3))
    belgie.plugins = [organization_plugin, team_plugin]

    app = FastAPI()
    app.include_router(organization_plugin.router(belgie))

    @app.get("/organization-limit")
    async def get_org_limit(
        organization: OrganizationClient = Depends(organization_plugin),
    ) -> dict[str, int | None]:
        return {"maximum_members_per_team": organization.maximum_members_per_team}

    client = TestClient(app)
    response = client.get("/organization-limit")

    assert response.status_code == 200
    assert response.json() == {"maximum_members_per_team": 3}


@pytest.mark.asyncio
async def test_dependency_requires_router_initialization() -> None:
    settings = BelgieSettings(secret="test-secret", base_url="http://localhost:8000")
    plugin = OrganizationPlugin(settings, Organization(adapter=FakeOrganizationAdapter()))

    with pytest.raises(RuntimeError, match="router initialization"):
        await plugin(SimpleNamespace(), SimpleNamespace())
