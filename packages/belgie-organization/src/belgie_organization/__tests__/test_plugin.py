from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import TYPE_CHECKING
from uuid import uuid4

from belgie_core.core.settings import BelgieSettings
from belgie_proto.organization import OrganizationAdapterProtocol
from fastapi import FastAPI
from fastapi.testclient import TestClient

from belgie_organization.plugin import OrganizationPlugin
from belgie_organization.settings import Organization

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable


class DummyBelgie:
    def __init__(self, client: FakeBelgieClient) -> None:
        self._client = client
        self.plugins: list[OrganizationPlugin] = []

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
    def __init__(self, *, organization, member) -> None:
        self._organization = organization
        self._member = member

    async def get_organization_by_id(self, _session, _organization_id):
        return self._organization

    async def get_member(self, _session, *, organization_id, user_id):  # noqa: ARG002
        return self._member

    def __getattr__(self, name: str) -> Callable[..., Awaitable[None]]:
        async def _unexpected(*_args: int, **_kwargs: int) -> None:
            msg = f"unexpected adapter call: {name}"
            raise AssertionError(msg)

        return _unexpected


def _create_client(*, member) -> tuple[TestClient, SimpleNamespace]:
    settings = BelgieSettings(secret="test-secret", base_url="http://localhost:8000")
    organization_row = SimpleNamespace(
        id=uuid4(),
        name="Acme",
        slug="acme",
        logo=None,
        organization_metadata=None,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    user = SimpleNamespace(id=uuid4())
    session = SimpleNamespace(id=uuid4(), active_organization_id=organization_row.id)
    adapter = FakeOrganizationAdapter(organization=organization_row, member=member)
    plugin = OrganizationPlugin(settings, Organization(adapter=adapter))
    belgie_client = FakeBelgieClient(user=user, session=session)
    assert not hasattr(belgie_client, "adapter")
    belgie = DummyBelgie(belgie_client)

    app = FastAPI()
    app.include_router(plugin.router(belgie))
    return TestClient(app), organization_row


def test_get_active_organization_returns_null_when_user_not_member() -> None:
    client, _organization = _create_client(member=None)

    response = client.get("/organization/active")

    assert response.status_code == 200
    assert response.json() is None


def test_get_active_organization_returns_org_when_user_is_member() -> None:
    client, organization = _create_client(member=SimpleNamespace(id=uuid4()))

    response = client.get("/organization/active")

    assert response.status_code == 200
    assert response.json() == {
        "id": str(organization.id),
        "name": organization.name,
        "slug": organization.slug,
        "logo": organization.logo,
        "metadata": organization.organization_metadata,
        "created_at": organization.created_at.isoformat().replace("+00:00", "Z"),
        "updated_at": organization.updated_at.isoformat().replace("+00:00", "Z"),
    }


def test_plugin_dependency_uses_settings_adapter_not_client_adapter() -> None:
    client, _organization = _create_client(member=SimpleNamespace(id=uuid4()))

    response = client.get("/organization/active")

    assert response.status_code == 200
